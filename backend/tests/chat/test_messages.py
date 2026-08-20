from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.chat.messages import (
    UserUIMessage,
    stored_messages_to_ui,
    to_internal_user_message,
)


def test_converts_one_text_ui_message_to_internal_storage() -> None:
    message = UserUIMessage.model_validate(
        {
            "id": "client-message-1",
            "role": "user",
            "parts": [{"type": "text", "text": "  What changed?  "}],
        }
    )

    internal = to_internal_user_message(message)

    assert internal.client_id == "client-message-1"
    assert internal.content == "What changed?"
    assert internal.message_data == {
        "clientMessageId": "client-message-1",
        "parts": [{"type": "text", "text": "What changed?"}],
    }


@pytest.mark.parametrize(
    "parts",
    [
        [],
        [{"type": "text", "text": ""}],
        [{"type": "text", "text": "   "}],
        [{"type": "image", "url": "https://example.com/image.png"}],
        [
            {"type": "text", "text": "one"},
            {"type": "text", "text": "two"},
        ],
    ],
)
def test_rejects_unsupported_or_empty_parts(parts: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError):
        UserUIMessage.model_validate(
            {"id": "client-message-1", "role": "user", "parts": parts}
        )


def test_serializes_messages_with_ordered_citations() -> None:
    message_id = uuid4()
    first_citation_id = uuid4()
    second_citation_id = uuid4()
    first_chunk_id = uuid4()
    second_chunk_id = uuid4()

    messages = stored_messages_to_ui(
        [
            {
                "id": str(message_id),
                "role": "assistant",
                "content": "Supported answer",
                "created_at": "2026-08-19T09:30:00+00:00",
            }
        ],
        [
            {
                "id": str(second_citation_id),
                "message_id": str(message_id),
                "chunk_id": str(second_chunk_id),
                "citation_index": 1,
                "excerpt": "Second",
            },
            {
                "id": str(first_citation_id),
                "message_id": str(message_id),
                "chunk_id": str(first_chunk_id),
                "citation_index": 0,
                "excerpt": "First",
            },
        ],
    )

    assert messages[0].parts[0].text == "Supported answer"
    assert [citation.excerpt for citation in messages[0].metadata.citations] == [
        "First",
        "Second",
    ]
