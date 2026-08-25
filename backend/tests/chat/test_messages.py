from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.assistant.outputs import (
    Citation,
    CitationTableCell,
    CitationTableRow,
    GroundedAnswer,
    TableCitationPassage,
)
from app.chat.messages import (
    CitationPart,
    SourceUrlPart,
    UserUIMessage,
    assistant_message_data,
    assistant_ui_parts,
    stored_messages_to_history,
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


def test_serializes_persisted_source_and_citation_parts() -> None:
    message_id = uuid4()
    citation_id = uuid4()
    chunk_id = uuid4()
    document_id = uuid4()

    messages = stored_messages_to_ui(
        [
            {
                "id": str(message_id),
                "role": "assistant",
                "content": "Supported answer [S1].",
                "message_data": {
                    "answerStatus": "supported",
                    "parts": [
                        {"type": "text", "text": "Supported answer [S1]."},
                        {
                            "type": "source-url",
                            "sourceId": "S1",
                            "url": "https://www.sec.gov/example",
                            "title": "Apple 10-K",
                        },
                        {
                            "type": "data-citation",
                            "id": str(citation_id),
                            "data": {
                                "citationId": str(citation_id),
                                "sourceId": "S1",
                                "citationIndex": 0,
                                "chunkId": str(chunk_id),
                                "documentId": str(document_id),
                                "chunkIndex": 4,
                                "excerpt": "An exact filing excerpt used by the answer.",
                                "company": "Apple Inc.",
                                "ticker": "AAPL",
                                "filingType": "10-K",
                                "filingDate": "2024-11-01",
                                "reportDate": "2024-09-28",
                                "accessionNumber": "0000320193-24-000123",
                                "secUrl": "https://www.sec.gov/example",
                                "pageNumber": 12,
                                "sectionTitle": "Results of Operations",
                                "sourceStart": 100,
                                "sourceEnd": 180,
                            },
                        },
                    ],
                },
                "created_at": "2026-08-19T09:30:00+00:00",
            }
        ],
        [],
    )

    assert messages[0].parts[0].text == "Supported answer [S1]."
    assert isinstance(messages[0].parts[1], SourceUrlPart)
    assert isinstance(messages[0].parts[2], CitationPart)
    assert messages[0].parts[2].data.company == "Apple Inc."
    assert messages[0].metadata.answer_status == "supported"


@pytest.mark.parametrize("status", ["conversational", "out_of_scope"])
def test_reloads_non_retrieval_answer_status(status: str) -> None:
    messages = stored_messages_to_ui(
        [
            {
                "id": str(uuid4()),
                "role": "assistant",
                "content": "A short response.",
                "message_data": {
                    "answerStatus": status,
                    "parts": [{"type": "text", "text": "A short response."}],
                },
                "created_at": "2026-08-19T09:30:00+00:00",
            }
        ],
        [],
    )

    assert messages[0].metadata.answer_status == status
    assert [part.type for part in messages[0].parts] == ["text"]


def test_persists_and_reloads_citation_passage_with_camel_case_cells() -> None:
    citation_id = uuid4()
    citation = Citation(
        source_id="S1",
        citation_index=0,
        chunk_id=uuid4(),
        document_id=uuid4(),
        chunk_index=4,
        excerpt="Revenue | <script>alert(1)</script>",
        company="Apple Inc.",
        ticker="AAPL",
        filing_type="10-K",
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        accession_number="0000320193-24-000123",
        sec_url="https://www.sec.gov/example",
        passage=TableCitationPassage(
            column_count=4,
            rows=(
                CitationTableRow(
                    cells=(
                        CitationTableCell(
                            text="<script>alert(1)</script>",
                            column_index=2,
                            row_span=1,
                            column_span=2,
                            highlighted=True,
                        ),
                    )
                ),
            ),
        ),
    )
    answer = GroundedAnswer(
        status="supported",
        answer="Revenue was disclosed [S1].",
        citations=(citation,),
    )
    message_data = assistant_message_data(
        answer.status,
        assistant_ui_parts(answer, (citation_id,)),
    )

    passage_data = message_data["parts"][2]["data"]["passage"]
    cell_data = passage_data["rows"][0]["cells"][0]
    assert cell_data["columnIndex"] == 2
    assert "column_index" not in cell_data

    messages = stored_messages_to_ui(
        [
            {
                "id": str(uuid4()),
                "role": "assistant",
                "content": answer.answer,
                "message_data": message_data,
                "created_at": "2026-08-19T09:30:00+00:00",
            }
        ],
        [],
    )

    part = messages[0].parts[2]
    assert isinstance(part, CitationPart)
    assert part.data.passage is not None
    assert part.data.passage.kind == "table"
    assert part.data.passage.rows[0].cells[0].text == "<script>alert(1)</script>"


def test_uses_client_message_id_when_reloading_a_user_message() -> None:
    messages = stored_messages_to_ui(
        [
            {
                "id": str(uuid4()),
                "role": "user",
                "content": "What changed?",
                "message_data": {
                    "clientMessageId": "client-1",
                    "parts": [{"type": "text", "text": "What changed?"}],
                },
                "created_at": "2026-08-19T09:30:00+00:00",
            }
        ],
        [],
    )

    assert messages[0].id == "client-1"


def test_converts_only_complete_alternating_stored_history() -> None:
    rows = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer [S1]."},
    ]

    history = stored_messages_to_history(rows)

    assert [message.role for message in history] == ["user", "assistant"]
    assert history[1].content == "First answer [S1]."


def test_rejects_incomplete_stored_history() -> None:
    with pytest.raises(ValueError, match="complete turns"):
        stored_messages_to_history([{"role": "user", "content": "Question"}])
