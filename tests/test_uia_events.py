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

