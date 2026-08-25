"""AI SDK UI message validation, history conversion, and persisted parts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from app.assistant.outputs import AnswerStatus, Citation, GroundedAnswer, HistoryMessage


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class StrictApiModel(ApiModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class TextPart(StrictApiModel):
    type: Literal["text"]
    text: str = Field(max_length=10_000)

    @field_validator("text")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message text cannot be empty")
        return value


class SourceUrlPart(StrictApiModel):
    type: Literal["source-url"]
    source_id: str
    url: str
    title: str | None = None


class CitationTextHighlightData(StrictApiModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class TextCitationPassageData(StrictApiModel):
    version: Literal[1]
    kind: Literal["text"]
    text: str
    highlights: tuple[CitationTextHighlightData, ...]


class CitationTableCellData(StrictApiModel):
    text: str
    column_index: int = Field(ge=0)
    row_span: int = Field(gt=0)
    column_span: int = Field(gt=0)
    column_header: bool
    row_header: bool
    highlighted: bool


class CitationTableRowData(StrictApiModel):
    cells: tuple[CitationTableCellData, ...]


class TableCitationPassageData(StrictApiModel):
    version: Literal[1]
    kind: Literal["table"]
    column_count: int = Field(gt=0)
    rows: tuple[CitationTableRowData, ...]


CitationPassageData = Annotated[
    TextCitationPassageData | TableCitationPassageData,
    Field(discriminator="kind"),
]


class CitationData(StrictApiModel):
    citation_id: UUID
    source_id: str
    citation_index: int = Field(ge=0)
    chunk_id: UUID
    document_id: UUID
    chunk_index: int = Field(ge=0)
    excerpt: str
    company: str
    ticker: str
    filing_type: str
    filing_date: date
    report_date: date
    accession_number: str
    sec_url: str
    page_number: int | None = Field(default=None, gt=0)
    section_title: str | None = None
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, gt=0)
    passage: CitationPassageData | None = None


class CitationPart(StrictApiModel):
    type: Literal["data-citation"]
    id: str
    data: CitationData


type UIMessagePart = TextPart | SourceUrlPart | CitationPart
PART_ADAPTER = TypeAdapter(UIMessagePart)


class UserUIMessage(StrictApiModel):
    id: str = Field(min_length=1, max_length=200)
    role: Literal["user"]
    parts: list[TextPart] = Field(min_length=1, max_length=1)
    metadata: dict[str, object] | None = None


class ChatStreamRequest(ApiModel):
    id: UUID
    message: UserUIMessage


class MessageMetadata(ApiModel):
    created_at: datetime
    answer_status: AnswerStatus | None = None


class UIMessageResponse(ApiModel):
    id: str
    role: Literal["user", "assistant"]
    parts: list[UIMessagePart]
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


def assistant_ui_parts(
    answer: GroundedAnswer,
    citation_ids: tuple[UUID, ...],
) -> list[UIMessagePart]:
    if len(answer.citations) != len(citation_ids):
        raise ValueError("Every validated citation requires a persistence ID")

    parts: list[UIMessagePart] = [TextPart(type="text", text=answer.answer)]
    for citation, citation_id in zip(answer.citations, citation_ids, strict=True):
        parts.append(
            SourceUrlPart(
                type="source-url",
                source_id=citation.source_id,
                url=citation.sec_url,
                title=_source_title(citation),
            )
        )
        data = CitationData(
            citation_id=citation_id,
            **citation.model_dump(),
        )
        parts.append(
            CitationPart(
                type="data-citation",
                id=str(citation_id),
                data=data,
            )
        )
    return parts


def assistant_message_data(
    answer_status: AnswerStatus,
    parts: list[UIMessagePart],
) -> dict[str, object]:
    return {
        "answerStatus": answer_status,
        "parts": [part.model_dump(mode="json", by_alias=True) for part in parts],
    }


def stored_messages_to_ui(
    message_rows: list[dict[str, object]],
    _citation_rows: list[dict[str, object]],
) -> list[UIMessageResponse]:
    messages = []
    for message in message_rows:
        message_data = _message_data(message)
        role = str(message["role"])
        ui_id = str(message["id"])
        if role == "user":
            client_id = message_data.get("clientMessageId")
            if isinstance(client_id, str) and client_id:
                ui_id = client_id

        messages.append(
            UIMessageResponse(
                id=ui_id,
                role=role,
                parts=_stored_parts(message, message_data),
                metadata=MessageMetadata(
                    created_at=_parse_datetime(message["created_at"]),
                    answer_status=_answer_status(message_data),
                ),
            )
        )
    return messages


def stored_messages_to_history(
    message_rows: list[dict[str, object]],
) -> tuple[HistoryMessage, ...]:
    if len(message_rows) % 2:
        raise ValueError("Stored chat history must contain complete turns")
    history = tuple(
        HistoryMessage(role=str(message["role"]), content=str(message["content"]))
        for message in message_rows
    )
    for index, message in enumerate(history):
        expected_role = "user" if index % 2 == 0 else "assistant"
        if message.role != expected_role:
            raise ValueError("Stored chat history must alternate user and assistant")
    return history


def _stored_parts(
    message: dict[str, object],
    message_data: dict[str, object],
) -> list[UIMessagePart]:
    raw_parts = message_data.get("parts")
    if not isinstance(raw_parts, list):
        return [TextPart(type="text", text=str(message["content"]))]
    return [PART_ADAPTER.validate_python(part) for part in raw_parts]


def _message_data(message: dict[str, object]) -> dict[str, object]:
    value = message.get("message_data")
    if isinstance(value, dict):
        return value
    return {}


def _answer_status(message_data: dict[str, object]) -> AnswerStatus | None:
    value = message_data.get("answerStatus")
    if value in {
        "conversational",
        "out_of_scope",
        "supported",
        "insufficient_evidence",
        "investment_advice_refused",
    }:
        return value
    return None


def _source_title(citation: Citation) -> str:
    return (
        f"{citation.company} ({citation.ticker}) · {citation.filing_type} · "
        f"{citation.filing_date.isoformat()}"
    )


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
