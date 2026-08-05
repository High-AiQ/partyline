import unittest

from partyline.contracts import (
    AdapterMetadataResponse,
    ConversationResponse,
    HelloEvent,
    MessageEvent,
    MessageResponse,
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
            HelloEvent(conversation_id="line", handle="greg").model_dump(exclude_none=True),
            {"type": "hello", "conversation_id": "line", "handle": "greg"},
        )
