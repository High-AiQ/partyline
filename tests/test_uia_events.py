"""UIA event registration follows the generated COM interface contract."""
import unittest
from types import SimpleNamespace

from partyline_helper.uia_events import (PROPERTIES, UIAEventSubscription, register_handlers,
                                         remove_handlers)


class HandlerBase:
    def __init__(self):
        self._com_interfaces_ = type(self)._com_interfaces_


class AutomationContract:
    def __init__(self):
        self.added = []
        self.removed = []

    def AddPropertyChangedEventHandler(self, element, scope, cache, handler, property_ids):
        self.added.append(("property", element, scope, cache, handler, property_ids))

    def AddStructureChangedEventHandler(self, element, scope, cache, handler):
        self.added.append(("structure", element, scope, cache, handler))

    def RemovePropertyChangedEventHandler(self, element, handler):
        self.removed.append(("property", element, handler))

    def RemoveStructureChangedEventHandler(self, element, handler):
        self.removed.append(("structure", element, handler))


class UIAEventContractTests(unittest.TestCase):
    def test_revocation_after_startup_timeout_prevents_late_message_loop(self):
        subscription = UIAEventSubscription(42, lambda: None)
        self.assertFalse(subscription.ready.wait(0))  # startup has not signalled within its wait

        subscription.close()  # grant ends while COM startup is still pending

        self.assertTrue(subscription.cancelled.is_set())
        self.assertFalse(subscription._mark_started(123, object(), []))
        self.assertFalse(subscription.started)
        self.assertTrue(subscription.ready.is_set())

    def test_property_and_structure_handlers_use_ui_automation_signatures(self):
        automation = AutomationContract()
        uia = SimpleNamespace(IUIAutomationPropertyChangedEventHandler=object,
                              IUIAutomationStructureChangedEventHandler=object)
        changes = []
        handlers = register_handlers(automation, uia, "window", lambda: changes.append("changed"),
                                     HandlerBase)

        kind, element, scope, cache, property_handler, properties = automation.added[0]
        self.assertEqual(("property", "window", 7, None), (kind, element, scope, cache))
        self.assertEqual(list(PROPERTIES), properties)
        property_handler.HandlePropertyChangedEvent("element", 30010, True)
        structure_handler = automation.added[1][-1]
        structure_handler.HandleStructureChangedEvent("element", 0, [1, 2])
        self.assertEqual(["changed", "changed"], changes)

        remove_handlers(automation, handlers)
        self.assertEqual({"property", "structure"}, {event[0] for event in automation.removed})

    def test_partial_registration_is_unsubscribed_when_structure_subscription_fails(self):
        class PartialAutomation(AutomationContract):
            def AddStructureChangedEventHandler(self, element, scope, cache, handler):
                raise RuntimeError("structure events unavailable")

        automation = PartialAutomation()
        uia = SimpleNamespace(IUIAutomationPropertyChangedEventHandler=object,
                              IUIAutomationStructureChangedEventHandler=object)
        with self.assertRaisesRegex(RuntimeError, "structure events unavailable"):
            register_handlers(automation, uia, "window", lambda: None, HandlerBase)
        self.assertEqual("property", automation.removed[0][0])


    def test_structure_only_subscription_filters_unrelated_senders(self):
        automation = AutomationContract()
        uia = SimpleNamespace(IUIAutomationPropertyChangedEventHandler=object,
                              IUIAutomationStructureChangedEventHandler=object)
        changes = []
        register_handlers(automation, uia, "desktop", lambda: changes.append("changed"), HandlerBase,
                          accepts=lambda sender: sender == "owned popup", structure_only=True)
        self.assertEqual(1, len(automation.added))
        handler = automation.added[0][-1]
        handler.HandleStructureChangedEvent("unrelated", 0, [])
        handler.HandleStructureChangedEvent("owned popup", 0, [])
        self.assertEqual(["changed"], changes)

    def test_expand_waits_once_for_structure_with_injected_event_and_no_real_time(self):
        from unittest.mock import Mock
        from partyline_helper.uia_expand_events import EXPAND_EVENT_SECONDS, structure_call
        event = Mock()
        subscription = SimpleNamespace(start=Mock(return_value=True), close=Mock())
        subscribe = Mock(return_value=subscription)
        pattern = Mock(return_value="done")
        self.assertEqual("done", structure_call(42, pattern, subscribe, lambda: event)())
        subscribe.assert_called_once_with(42, event.set, structure_only=True)
        event.clear.assert_called_once_with()
        event.wait.assert_called_once_with(EXPAND_EVENT_SECONDS)
        subscription.close.assert_called_once_with()
        subscription.start.return_value = False
        event.reset_mock()
        structure_call(42, pattern, subscribe, lambda: event)()
        event.wait.assert_not_called()
        pattern.side_effect = RuntimeError("pattern failed")
        with self.assertRaisesRegex(RuntimeError, "pattern failed"):
            structure_call(42, pattern, subscribe, lambda: event)()
        self.assertEqual(3, subscription.close.call_count)
