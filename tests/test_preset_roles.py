"""Staffing roles are decided solely by preset traits."""

import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from partyline.attachment_start import start_attachment
from partyline.orchestrator_store import validate_policy
from partyline.preset_roles import attachment_preset, require_named_role, require_role


class PresetRolesTest(unittest.TestCase):
    def test_matrix(self):
        for implements in (False, True):
            for manage in (False, True):
                preset = {'name': 'sample', 'implements': implements, 'can_manage': manage}
                for role, allowed, label in (('implementer', implements, 'Fast implementer'),
                                             ('captain', manage, 'Can manage a line'),
                                             ('reviewer', manage, 'Can manage a line')):
                    with self.subTest(implements=implements, manage=manage, role=role):
                        if allowed:
                            self.assertIs(require_role(preset, role), preset)
                        else:
                            with self.assertRaises(HTTPException) as error:
                                require_role(preset, role)
                            self.assertEqual(error.exception.status_code, 403)
                            for part in ('sample', role, label, 'Settings → Presets'):
                                self.assertIn(part, error.exception.detail)

    def test_launch_boundary_refuses_an_invalid_machine_before_start(self):
        preset = {'name': 'sample', 'adapter': 'fake', 'command': 'fake',
                  'implements': False, 'can_manage': True}
        db = SimpleNamespace(list_presets=lambda: [preset])
        att = {'name': 'sample', 'adapter': 'fake', 'command': ['fake']}
        runtime = SimpleNamespace(db=db)
        with patch('partyline.attachment_start.rollback_start', new=AsyncMock()) as rollback:
            with self.assertRaises(HTTPException) as error:
                asyncio.run(start_attachment(att, runtime=runtime, presence=None, make_adapter=None,
                                             hook_url=None, staffing_role='implementer'))
            rollback.assert_awaited_once_with(runtime, att)
        self.assertEqual(error.exception.status_code, 403)
        self.assertIn('Fast implementer', error.exception.detail)

    def test_missing_or_ambiguous_named_preset_is_actionable(self):
        for rows in ([], [{'name': 'sample'}, {'name': 'sample'}]):
            with self.subTest(rows=rows), self.assertRaises(HTTPException) as error:
                require_named_role(SimpleNamespace(list_presets=lambda rows=rows: rows), 'sample', 'reviewer')
            self.assertEqual(error.exception.status_code, 400)
            self.assertIn('sample', error.exception.detail)
            self.assertIn('Can manage a line', error.exception.detail)

    def test_recorded_preset_retains_its_traits_after_command_edit(self):
        preset = {'name': 'sample', 'adapter': 'fake', 'command': 'fake --new',
                  'implements': True, 'can_manage': False}
        db = SimpleNamespace(list_presets=lambda: [preset])
        attachment = {'preset': 'sample', 'name': 'worker', 'adapter': 'fake', 'command': ['fake']}
        self.assertIs(attachment_preset(db, attachment), preset)
        self.assertIs(require_role(attachment_preset(db, attachment), 'implementer'), preset)

    def test_policy_special_cases_and_named(self):
        preset = {'name': 'sample', 'implements': True, 'can_manage': False}
        db = SimpleNamespace(list_presets=lambda: [preset])
        for policy in ('captain', 'none'):
            self.assertEqual(validate_policy(db, policy), policy)
        with self.assertRaises(HTTPException):
            validate_policy(db, 'sample')
        preset['can_manage'] = True
        self.assertEqual(validate_policy(db, 'sample'), 'sample')

    def test_launch_and_role_boundaries_are_accounted_for(self):
        # Enumerate the low-level launch and assignment callers. Adding a path
        # requires deliberate review and a corresponding policy assertion.
        root = Path(__file__).resolve().parents[1] / 'partyline'
        names = {'_start_attachment', 'start_attachment', '_resume_adapter', 'resume_adapter',
                 'resume_with_backlog', 'set_lead', 'spawn', 'start_staffed', 'seat_captain'}
        actual = set()
        references = set()
        targets = {'_start_attachment', 'start_attachment', '_resume_adapter',
                   'resume_adapter', 'resume_with_backlog'}
        trees = {}
        for path in root.rglob('*.py'):
            source = path.read_text()
            if not any(name in source for name in names):
                continue
            tree = trees[path.relative_to(root).as_posix()] = ast.parse(source)
            for node in ast.walk(tree):
                ref = node.id if isinstance(node, ast.Name) else (
                    node.attr if isinstance(node, ast.Attribute) else '')
                if ref in targets:
                    references.add((path.relative_to(root).as_posix(), ref))
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                        node.func.id if isinstance(node.func, ast.Name) else '')
                    if name in names:
                        actual.add((path.relative_to(root).as_posix(), name))
        expected = {
            ('server.py', 'start_attachment'), ('server.py', '_start_attachment'),
            ('server.py', 'resume_with_backlog'), ('server.py', '_resume_adapter'),
            ('server.py', 'resume_adapter'), ('memory_requests.py', 'resume_with_backlog'),
            ('write_set_requests.py', 'resume_with_backlog'),
            ('orchestrator_staff.py', '_start_attachment'), ('orchestrator_staff.py', '_resume_adapter'),
            ('orchestrator_staff.py', 'spawn'), ('orchestrator_service.py', 'spawn'),
            ('hierarchy_routes.py', 'set_lead'), ('conversation_routes.py', 'start_staffed'),
            ('preset_roles.py', 'seat_captain'), ('adapters/windows_runtime.py', 'spawn'),
            ('windows_probe.py', 'spawn'),
        }
        self.assertEqual(actual, expected)
        self.assertEqual(references, {
            ('server.py', '_start_attachment'), ('server.py', 'start_attachment'),
            ('server.py', '_resume_adapter'), ('server.py', 'resume_adapter'),
            ('server.py', 'resume_with_backlog'), ('conversation_routes.py', '_start_attachment'),
            ('orchestrator_staff.py', '_start_attachment'), ('orchestrator_staff.py', '_resume_adapter'),
            ('memory_requests.py', 'resume_with_backlog'), ('write_set_requests.py', 'resume_with_backlog'),
        })
        # Memory and write-set approvals resume live processes; server restart
        # recovery also continues live processes, rather than staffing new ones.
        boundaries = {
            'attachment_start.py': {'start_attachment': {'require_role'}},
            'orchestrator_staff.py': {'spawn': {'require_named_role'},
                                      'restart': {'require_named_role'},
                                      'ensure_reviewer': {'require_named_role'}},
            'orchestrator_service.py': {'_create_task': {'require_named_role', 'validate_policy'}},
            'orchestrator_reopen.py': {'reopen_task': {'require_named_role'}},
            'orchestrator_revive.py': {'restart_implementer': {'require_named_role'}},
            'hierarchy_routes.py': {'appoint_lead': {'require_captain_assignment'}},
            'captain_handover.py': {'accept': {'require_role'}},
            'conversation_routes.py': {'attach': {'require_role', 'start_staffed'}},
            'server.py': {'resume_attachment': {'require_resume'}},
            'attachment_lifecycle_routes.py': {'_start_replacement': {'require_resume'},
                                                'replace_attachment': {'require_resume'}},
            'preset_roles.py': {'require_named_role': {'require_role'},
                                'require_captain_assignment': {'require_role'},
                                'require_resume': {'require_role', 'require_named_role'},
                                'seat_captain': {'require_role'}},
            'orchestrator_store.py': {'validate_policy': {'require_named_role'}},
        }
        for filename, functions in boundaries.items():
            tree = trees.get(filename) or ast.parse((root / filename).read_text())
            found = {n.name: n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for function, required in functions.items():
                calls = {n.func.id for n in ast.walk(found[function])
                         if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                self.assertTrue(required <= calls, f'{filename}:{function} missing {required - calls}')
