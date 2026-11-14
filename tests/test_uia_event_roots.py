"""Persistent UIA handlers stay on explicit roots; popup lifecycle work happens outside callbacks."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from partyline_helper.uia_event_roots import WindowHandlers
from tests.test_uia_events import AutomationContract, HandlerBase


class RootsAutomation(AutomationContract):
    def __init__(self):
        super().__init__()
        self.ElementFromHandle = Mock(side_effect=lambda hwnd: hwnd)


class WindowHandlerTests(unittest.TestCase):
    def roots(self, automation, scope, changed):
        uia = SimpleNamespace(IUIAutomationPropertyChangedEventHandler=object,
                              IUIAutomationStructureChangedEventHandler=object)
        return WindowHandlers(automation, uia, 1, scope, changed, HandlerBase)

    def test_persistent_roots_follow_popup_lifecycle_without_desktop_or_sender_reads(self):
        automation, changed = RootsAutomation(), Mock()
        scope = SimpleNamespace(popups=Mock(return_value=[]))
        roots = self.roots(automation, scope, changed)
        roots.start()
        self.assertEqual([1], [item[1] for item in automation.added if item[0] == "structure"])
        # Sender can be any COM object: a scoped handler does not touch its properties or parents.
        sender = Mock()
        handler = automation.added[0][4]
        handler.HandlePropertyChangedEvent(sender, 30010, False)
        sender.assert_not_called()
        self.assertEqual([], sender.mock_calls)
        changed.assert_called_once_with()
        scope.popups.assert_called_once_with()
        automation.ElementFromHandle.assert_called_once_with(1)
        # The posted WinEvent message reconciles roots outside the UIA callback.
        scope.popups.return_value = [2]
        roots.refresh()
        self.assertEqual({1, 2}, set(roots.roots))
        self.assertEqual([1, 2], [item[1] for item in automation.added if item[0] == "structure"])
        scope.popups.return_value = []
        roots.refresh()
        self.assertEqual({1}, set(roots.roots))
        self.assertEqual({2}, {item[1] for item in automation.removed})
        roots.close()
        self.assertEqual({}, roots.roots)
        self.assertEqual({1, 2}, {item[1] for item in automation.removed})

    def test_popup_registration_and_unregistration_failures_preserve_other_roots(self):
        automation, changed = RootsAutomation(), Mock()
        scope = SimpleNamespace(popups=Mock(return_value=[2]))
        automation.ElementFromHandle.side_effect = lambda hwnd: 1 if hwnd == 1 else (_ for _ in ()).throw(
            RuntimeError("popup disappeared"))
        roots = self.roots(automation, scope, changed)
        roots.start()
        self.assertEqual({1}, set(roots.roots))
        automation.ElementFromHandle.side_effect = lambda hwnd: hwnd
        roots.refresh()
        self.assertEqual({1, 2}, set(roots.roots))
        automation.RemoveStructureChangedEventHandler = Mock(side_effect=RuntimeError("destroyed root"))
        roots.close()
        self.assertEqual({}, roots.roots)
        self.assertEqual({1, 2}, {item[1] for item in automation.removed})
