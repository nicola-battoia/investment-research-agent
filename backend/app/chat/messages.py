"""AI SDK UI message validation and persistence conversion."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class TextPart(ApiModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    type: Literal["text"]
    text: str = Field(max_length=10_000)

    @field_validator("text")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message text cannot be empty")
        return value


class UserUIMessage(ApiModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    id: str = Field(min_length=1, max_length=200)
    role: Literal["user"]
    parts: list[TextPart] = Field(min_length=1, max_length=1)
    metadata: dict[str, object] | None = None


class ChatStreamRequest(ApiModel):
    id: UUID
    message: UserUIMessage


class CitationResponse(ApiModel):
    id: UUID
    chunk_id: UUID
    citation_index: int
    excerpt: str


class MessageMetadata(ApiModel):
    created_at: datetime
    citations: list[CitationResponse]


class UIMessageResponse(ApiModel):
    id: str
    role: Literal["user", "assistant"]
    parts: list[TextPart]
    metadata: MessageMetadata


@dataclass(frozen=True)
class InternalUserMessage:
    client_id: str
    content: str
    message_data: dict[str, object]


def to_internal_user_message(message: UserUIMessage) -> InternalUserMessage:
    part = message.parts[0]
    return InternalUserMessage(
        client_id=message.id,
        content=part.text,
        message_data={
            "clientMessageId": message.id,
            "parts": [part.model_dump(by_alias=True)],
        },
    )


def assistant_message_data(content: str) -> dict[str, object]:
    return {
        "parts": [{"type": "text", "text": content}],
        "stub": True,
    }


def stored_messages_to_ui(
    message_rows: list[dict[str, object]],
    citation_rows: list[dict[str, object]],
) -> list[UIMessageResponse]:
    citations_by_message: dict[str, list[dict[str, object]]] = defaultdict(list)
    for citation in citation_rows:
        citations_by_message[str(citation["message_id"])].append(citation)

    messages: list[UIMessageResponse] = []
    for message in message_rows:
        citations = sorted(
            citations_by_message[str(message["id"])],
            key=lambda citation: int(citation["citation_index"]),
        )
        messages.append(
            UIMessageResponse(
                id=str(message["id"]),
                role=str(message["role"]),
                parts=[TextPart(type="text", text=str(message["content"]))],
                metadata=MessageMetadata(
                    created_at=_parse_datetime(message["created_at"]),
                    citations=[
                        CitationResponse(
                            id=UUID(str(citation["id"])),
                            chunk_id=UUID(str(citation["chunk_id"])),
                            citation_index=int(citation["citation_index"]),
                            excerpt=str(citation["excerpt"]),
                        )
                        for citation in citations
                    ],
                ),
            )
        )
    return messages


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
