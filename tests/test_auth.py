"""Accounts, tokens, and the guard: the whole credential lifecycle."""

import tempfile
import unittest
from datetime import timedelta

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from partyline import auth_store, auth_tokens
from partyline.auth_guard import (
    WS_POLICY_VIOLATION,
    UserSocketRegistry,
    exempt,
    install_auth_guard,
    resolve_principal,
    websocket_principal,
)
from partyline.auth_routes import auth_router
from partyline.adapters.briefing import child_env
from partyline.db import Db


REGISTRATION = {"email": "greg@example.com", "password": "hunter2222", "handle": "greg"}


class PasswordHashTest(unittest.TestCase):
    def test_roundtrip_and_rejection(self):
        stored = auth_tokens.hash_password("correct horse")
        self.assertTrue(auth_tokens.verify_password("correct horse", stored))
        self.assertFalse(auth_tokens.verify_password("wrong horse", stored))

    def test_two_hashes_of_one_password_differ_by_salt(self):
        first = auth_tokens.hash_password("same")
        second = auth_tokens.hash_password("same")
        self.assertNotEqual(first, second)
        self.assertTrue(auth_tokens.verify_password("same", second))

    def test_malformed_stored_hashes_never_verify(self):
        for stored in ("", "plaintext", "bcrypt$x$y", "scrypt$a$b$c$zz$zz"):
            self.assertFalse(auth_tokens.verify_password("anything", stored))


class DbBackedTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Db(f"{self.directory.name}/auth.db")
        self.addCleanup(self.db.close)


class TokenTest(DbBackedTest):
    def test_secret_survives_a_reopen(self):
        first = auth_tokens.signing_secret(self.db)
        self.db.close()
        self.db = Db(f"{self.directory.name}/auth.db")
        self.assertEqual(first, auth_tokens.signing_secret(self.db))

    def test_access_token_roundtrip(self):
        secret = auth_tokens.signing_secret(self.db)
        token = auth_tokens.create_access_token(secret, 7)
        self.assertEqual(
            7, auth_tokens.decode_token(secret, token, auth_tokens.TOKEN_TYPE_ACCESS)
        )

    def test_a_refresh_token_is_not_an_access_token(self):
        secret = auth_tokens.signing_secret(self.db)
        refresh = auth_tokens.create_refresh_token(secret, 7)
        with self.assertRaises(auth_tokens.TokenError):
            auth_tokens.decode_token(secret, refresh, auth_tokens.TOKEN_TYPE_ACCESS)

    def test_expired_and_garbage_tokens_are_refused(self):
        secret = auth_tokens.signing_secret(self.db)
        expired = auth_tokens._encode(
            secret, 7, auth_tokens.TOKEN_TYPE_ACCESS, timedelta(minutes=-1)
        )
        for token in (expired, "not-a-jwt", ""):
            with self.assertRaises(auth_tokens.TokenError):
                auth_tokens.decode_token(secret, token, auth_tokens.TOKEN_TYPE_ACCESS)

    def test_a_token_without_a_usable_subject_is_refused(self):
        import jwt as pyjwt
        from datetime import UTC, datetime

        secret = auth_tokens.signing_secret(self.db)
        now = datetime.now(UTC)
        unsubjected = pyjwt.encode(
            {"iat": now, "exp": now + timedelta(minutes=5), "type": "access"},
            secret, algorithm=auth_tokens.ALGORITHM,
        )
        with self.assertRaises(auth_tokens.TokenError):
            auth_tokens.decode_token(secret, unsubjected, auth_tokens.TOKEN_TYPE_ACCESS)


class MachineTokenTest(DbBackedTest):
    def setUp(self):
        super().setUp()
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("a1", "line", "opus", "claude", ["claude"], "/tmp")

    def test_token_is_minted_once_and_stable(self):
        first = auth_store.ensure_api_token(self.db, "a1")
        self.assertEqual(first, auth_store.ensure_api_token(self.db, "a1"))
        self.assertEqual(first, self.db.get_attachment("a1")["api_token"])

    def test_minting_for_a_missing_attachment_refuses(self):
        with self.assertRaises(KeyError):
            auth_store.ensure_api_token(self.db, "ghost")

    def test_machine_token_resolves_to_its_attachment(self):
        token = auth_store.ensure_api_token(self.db, "a1")
        principal = resolve_principal(self.db, token)
        self.assertEqual(("machine", "opus"), (principal.kind, principal.name))

    def test_child_env_carries_the_token(self):
        token = auth_store.ensure_api_token(self.db, "a1")
        env = child_env({}, self.db.get_attachment("a1"))
        self.assertEqual(token, env["PARTYLINE_TOKEN"])

    def test_child_env_omits_an_unminted_token(self):
        env = child_env({}, {"name": "opus", "conv_id": "line"})
        self.assertNotIn("PARTYLINE_TOKEN", env)


class RecordingSocket:
    def __init__(self):
        self.closed = None

    async def close(self, code, reason=""):
        self.closed = (code, reason)


class GuardTest(DbBackedTest):
    def setUp(self):
        super().setUp()
        self.registry = UserSocketRegistry()
        app = FastAPI()
        install_auth_guard(app, self.db)
        app.include_router(auth_router(self.db, on_handle_change=self.registry.close_all))

        @app.get("/api/probe")
        async def probe():
            return {"ok": True}

        @app.get("/api/version")
        async def version():
            return {"version": "test"}

        @app.websocket("/ws/probe")
        async def ws_probe(ws: WebSocket):
            principal = await websocket_principal(self.db, ws)
            if principal is None:
                return
            await ws.accept()
            await ws.send_json({"handle": principal.name})

        self.client = TestClient(app)

    def register(self, **overrides):
        return self.client.post(
            "/api/auth/register", json={**REGISTRATION, **overrides})

    def access_token(self):
        return self.register().json()["access_token"]

    def test_exemptions_are_exact(self):
        for path in ("/", "/api/version", "/api/auth/login", "/api/hooks/a/b",
                     "/assets/app.js"):
            self.assertTrue(exempt(path), path)
        for path in ("/api/conversations", "/api/probe", "/docs", "/api/authx"):
            self.assertFalse(exempt(path), path)

    def test_protected_route_requires_a_credential(self):
        self.assertEqual(401, self.client.get("/api/probe").status_code)
        self.assertEqual(200, self.client.get("/api/version").status_code)

    def test_user_token_passes_by_header_and_by_query(self):
        token = self.access_token()
        by_header = self.client.get(
            "/api/probe", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(200, by_header.status_code)
        by_query = self.client.get(f"/api/probe?token={token}")
        self.assertEqual(200, by_query.status_code)

    def test_machine_token_passes(self):
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("a1", "line", "opus", "claude", ["claude"], "/tmp")
        token = auth_store.ensure_api_token(self.db, "a1")
        response = self.client.get(
            "/api/probe", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(200, response.status_code)

    def test_junk_credentials_are_401(self):
        for header in ("Bearer nope", "Basic abc", "Bearer "):
            response = self.client.get(
                "/api/probe", headers={"Authorization": header})
            self.assertEqual(401, response.status_code, header)

    def test_a_token_for_a_deleted_user_is_refused(self):
        token = self.access_token()
        with self.db.lock:
            self.db.conn.execute("DELETE FROM users")
            self.db.conn.commit()
        response = self.client.get(
            "/api/probe", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(401, response.status_code)

    def test_websocket_without_a_token_closes_4401(self):
        with self.assertRaises(WebSocketDisconnect) as closed:
            with self.client.websocket_connect("/ws/probe") as ws:
                ws.receive_json()
        self.assertEqual(WS_POLICY_VIOLATION, closed.exception.code)

    def test_websocket_with_a_token_knows_the_handle(self):
        token = self.access_token()
        with self.client.websocket_connect(f"/ws/probe?token={token}") as ws:
            self.assertEqual({"handle": "greg"}, ws.receive_json())


class AuthApiTest(GuardTest):
    def test_register_logs_you_in(self):
        response = self.register()
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual("bearer", body["token_type"])
        self.assertEqual(
            {"id": 1, "email": "greg@example.com", "handle": "greg"}, body["user"])
        me = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {body['access_token']}"})
        self.assertEqual("greg", me.json()["handle"])

    def test_registration_validation(self):
        cases = [
            ({"email": "not-an-email"}, "email"),
            ({"password": "short"}, "password"),
            ({"handle": "bad handle!"}, "alphanumeric"),
            ({"handle": "all"}, "reserved"),
        ]
        for overrides, expected in cases:
            response = self.register(**overrides)
            self.assertEqual(400, response.status_code, overrides)
            self.assertIn(expected, response.json()["detail"])

    def test_duplicates_are_409_case_insensitively(self):
        self.register()
        dup_email = self.register(email="GREG@example.com", handle="other")
        self.assertEqual(409, dup_email.status_code)
        self.assertIn("email", dup_email.json()["detail"])
        dup_handle = self.register(email="two@example.com", handle="GREG")
        self.assertEqual(409, dup_handle.status_code)
        self.assertIn("handle", dup_handle.json()["detail"])

    def test_login_and_its_refusals(self):
        self.register()
        good = self.client.post(
            "/api/auth/login",
            json={"email": "Greg@Example.com", "password": "hunter2222"})
        self.assertEqual(200, good.status_code)
        self.assertEqual("greg", good.json()["user"]["handle"])
        for email, password in (
            ("greg@example.com", "wrong password"),
            ("nobody@example.com", "hunter2222"),
        ):
            refused = self.client.post(
                "/api/auth/login", json={"email": email, "password": password})
            self.assertEqual(401, refused.status_code)

    def test_refresh_rotates_and_refuses_the_wrong_kind(self):
        issued = self.register().json()
        refreshed = self.client.post(
            "/api/auth/refresh", json={"refresh_token": issued["refresh_token"]})
        self.assertEqual(200, refreshed.status_code)
        self.assertNotEqual(
            issued["refresh_token"], refreshed.json()["refresh_token"])
        wrong_kind = self.client.post(
            "/api/auth/refresh", json={"refresh_token": issued["access_token"]})
        self.assertEqual(401, wrong_kind.status_code)

    def test_refresh_for_a_deleted_user_is_refused(self):
        issued = self.register().json()
        with self.db.lock:
            self.db.conn.execute("DELETE FROM users")
            self.db.conn.commit()
        response = self.client.post(
            "/api/auth/refresh", json={"refresh_token": issued["refresh_token"]})
        self.assertEqual(401, response.status_code)

    def test_me_requires_a_user_token(self):
        self.assertEqual(401, self.client.get("/api/auth/me").status_code)
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("a1", "line", "opus", "claude", ["claude"], "/tmp")
        machine = auth_store.ensure_api_token(self.db, "a1")
        response = self.client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {machine}"})
        self.assertEqual(401, response.status_code)

    def test_handle_change_lifecycle(self):
        token = self.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        changed = self.client.patch(
            "/api/auth/me", json={"handle": "gregory"}, headers=headers)
        self.assertEqual(200, changed.status_code)
        self.assertEqual("gregory", changed.json()["handle"])
        # The token still works: it carries the user id, not the handle.
        self.assertEqual(
            "gregory", self.client.get("/api/auth/me", headers=headers).json()["handle"])
        recased = self.client.patch(
            "/api/auth/me", json={"handle": "Gregory"}, headers=headers)
        self.assertEqual(200, recased.status_code)

    def test_registration_refuses_a_handle_owned_by_an_attachment(self):
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("a1", "line", "opus", "claude", ["claude"], "/tmp")
        taken = self.register(handle="OPUS")
        self.assertEqual(409, taken.status_code)
        self.assertIn("handle", taken.json()["detail"])

    def test_handle_change_refuses_an_attachment_name(self):
        self.db.create_conversation("line", "Line")
        self.db.add_attachment("a1", "line", "opus", "claude", ["claude"], "/tmp")
        headers = {"Authorization": f"Bearer {self.access_token()}"}
        taken = self.client.patch(
            "/api/auth/me", json={"handle": "Opus"}, headers=headers)
        self.assertEqual(409, taken.status_code)

    def test_handle_change_closes_every_socket_the_user_holds(self):
        issued = self.register().json()
        first, second, other = RecordingSocket(), RecordingSocket(), RecordingSocket()
        self.registry.add(issued["user"]["id"], first)
        self.registry.add(issued["user"]["id"], second)
        self.registry.add(issued["user"]["id"] + 1, other)
        headers = {"Authorization": f"Bearer {issued['access_token']}"}
        changed = self.client.patch(
            "/api/auth/me", json={"handle": "gregory"}, headers=headers)
        self.assertEqual(200, changed.status_code)
        # Both of this user's tabs get the 4401 close and reconnect under the
        # new handle; other accounts' sockets are untouched.
        self.assertEqual(WS_POLICY_VIOLATION, first.closed[0])
        self.assertEqual(WS_POLICY_VIOLATION, second.closed[0])
        self.assertIsNone(other.closed)

    def test_socket_registry_ignores_machines_and_forgets_on_discard(self):
        ws = RecordingSocket()
        self.registry.add(None, ws)  # machine principals are never tracked
        self.registry.discard(None, ws)
        self.registry.add(7, ws)
        self.registry.discard(7, ws)
        self.arun_close_all(7)
        self.assertIsNone(ws.closed)

    def arun_close_all(self, user_id):
        import asyncio

        asyncio.run(self.registry.close_all(user_id))

    def test_handle_change_refusals(self):
        self.register(email="other@example.com", handle="other")
        token = self.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        taken = self.client.patch(
            "/api/auth/me", json={"handle": "Other"}, headers=headers)
        self.assertEqual(409, taken.status_code)
        invalid = self.client.patch(
            "/api/auth/me", json={"handle": "no spaces"}, headers=headers)
        self.assertEqual(400, invalid.status_code)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
