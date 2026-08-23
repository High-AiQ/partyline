import unittest

from pydantic import ValidationError

from partyline.contracts import (
    AdapterMetadataResponse,
    ConversationResponse,
    HelloEvent,
    MessageEvent,
    MessageResponse,
    ReattachCandidateResponse,
    ReattachCommand,
    ReattachDecisionEvent,
    ReattachOfferEvent,
    RestartPlanResponse,
    ShutdownResponse,
)


class ContractTest(unittest.TestCase):
    def test_conversation_response_keeps_database_shape(self):
        conversation = ConversationResponse(
            id="line",
            name="Line",
            created_at=12.5,
            topic="standing brief",
            archived_at=None,
        )

        self.assertEqual(
            conversation.model_dump(),
            {
                "id": "line",
                "name": "Line",
                "created_at": 12.5,
                "topic": "standing brief",
                "archived_at": None,
            },
        )

    def test_adapter_metadata_keeps_additive_manifest_fields(self):
        adapter = AdapterMetadataResponse.model_validate(
            {"id": "raw", "name": "raw", "capabilities": {"resume": False}}
        )

        self.assertEqual(adapter.model_dump()["capabilities"], {"resume": False})

    def test_adapter_metadata_has_explicit_source_override_fields(self):
        bundled = AdapterMetadataResponse(id="raw")
        self.assertEqual(bundled.source, "bundled")
        self.assertFalse(bundled.overrides_bundled)
        imported = AdapterMetadataResponse(
            id="raw", source="/tmp/adapters/raw", overrides_bundled=True
        )
        self.assertTrue(imported.overrides_bundled)

    def test_adapter_metadata_exposes_compact_paste(self):
        adapter = AdapterMetadataResponse(id="cursor", compact_paste="/summarize\n")

        self.assertEqual(adapter.model_dump()["compact_paste"], "/summarize\n")

    def test_wire_events_match_existing_payloads(self):
        message = MessageResponse(
            id=1,
            conv_id="line",
            sender="greg",
            sender_type="human",
            body="hello",
            created_at=12.5,
        )

        self.assertEqual(
            MessageEvent(message=message).model_dump(),
            {"type": "message", "message": message.model_dump()},
        )
        self.assertEqual(
            HelloEvent(conversation_id="line", handle="greg", version="0.21.4")
            .model_dump(exclude_none=True),
            {
                "type": "hello",
                "conversation_id": "line",
                "handle": "greg",
                "version": "0.21.4",
            },
        )
        self.assertEqual(
            HelloEvent(
                conversation_id="line",
                handle="greg",
                version="0.21.4",
                instance_name="Cockpit",
            ).model_dump(exclude_none=True)["instance_name"],
            "Cockpit",
        )

    def test_hello_requires_release_version(self):
        with self.assertRaises(ValidationError):
            HelloEvent(conversation_id="line", handle="greg")

    def test_restart_contracts_keep_the_offer_token_and_exact_candidate_shape(self):
        candidate = ReattachCandidateResponse(id="att-1", name="sol", adapter="codex")
        plan = RestartPlanResponse(
            conversation_id="line",
            token="offer-token",
            attachments=[candidate],
            debrief="Continue the review.",
        )

        self.assertEqual(
            ShutdownResponse(ok=True, stopping=["sol"], reattach=plan).model_dump(),
            {
                "ok": True,
                "stopping": ["sol"],
                "reattach": {
                    "conversation_id": "line",
                    "token": "offer-token",
                    "attachments": [{"id": "att-1", "name": "sol", "adapter": "codex"}],
                    "debrief": "Continue the review.",
                },
            },
        )
        offer = ReattachOfferEvent(
            conversation_id="line",
            token="offer-token",
            attachments=[candidate],
            debrief="Continue the review.",
        )
        self.assertEqual(
            offer.model_dump(),
            {
                "type": "reattach_offer",
                "conversation_id": "line",
                "token": "offer-token",
                "attachments": [{"id": "att-1", "name": "sol", "adapter": "codex"}],
                "debrief": "Continue the review.",
            },
        )
        self.assertEqual(
            ReattachDecisionEvent(
                conversation_id="line",
                token="offer-token",
                action="started",
            ).model_dump(),
            {
                "type": "reattach_decision",
                "conversation_id": "line",
                "token": "offer-token",
                "action": "started",
            },
        )

    def test_reattach_command_requires_an_explicit_supported_action(self):
        command = ReattachCommand.model_validate(
            {"type": "reattach", "token": "offer-token", "action": "accept"}
        )

        self.assertEqual(command.action, "accept")
        with self.assertRaises(ValueError):
            ReattachCommand.model_validate(
                {"type": "reattach", "token": "offer-token", "action": "later"}
            )
