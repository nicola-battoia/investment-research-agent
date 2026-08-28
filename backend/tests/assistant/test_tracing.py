from httpx import Request, Response
from openai import RateLimitError
from structlog.testing import capture_logs

from app.assistant.tracing import (
    AssistantTrace,
    embedding_summary,
    upstream_error_log_context,
)


def trace(*, mode: str = "full", limit: int = 12_000) -> AssistantTrace:
    return AssistantTrace(
        trace_id="trace-1",
        thread_id="thread-1",
        user_id="user-1",
        client_message_id="client-1",
        mode=mode,
        max_content_characters=limit,
    )


def test_full_trace_redacts_secrets_omits_provider_details_and_bounds_text() -> None:
    serialized = trace(limit=8).serialize(
        {
            "authorization": "Bearer token-value",
            "prompt": "abcdefghijkl",
            "provider_details": {"reasoning_content": "private"},
            "answer": "Use sk-secretvalue123 nowhere",
        }
    )

    assert serialized["authorization"] == "[REDACTED]"
    assert serialized["provider_details"] == "[OMITTED]"
    assert serialized["prompt"]["preview"] == "abcdefgh"
    assert serialized["prompt"]["omitted_characters"] == 4
    assert serialized["prompt"]["truncated"] is True
    assert "secretvalue123" not in str(serialized)


def test_summary_trace_keeps_metadata_without_content_or_identifiers() -> None:
    summary = trace(mode="summary", limit=12_000)
    embedding = embedding_summary([0.1, 0.2, 0.3])

    assert summary.serialize("PRIVATE_DIRECT_SERIALIZATION") == "[OMITTED]"

    with capture_logs() as logs:
        summary.emit(
            "retrieval_completed",
            "retrieval.search.completed",
            duration_ms=12.5,
            candidate_count=20,
            model="safe-model-name",
            question="PRIVATE_QUESTION_SENTINEL",
            history=[{"content": "PRIVATE_HISTORY_SENTINEL"}],
            passages=["PRIVATE_PASSAGE_SENTINEL"] * 1_000,
            error_message="PRIVATE_ERROR_SENTINEL",
            provider_response_id="provider-private",
        )

    assert logs[0]["duration_ms"] == 12.5
    assert logs[0]["candidate_count"] == 20
    assert logs[0]["model"] == "safe-model-name"
    rendered = str(logs[0])
    for forbidden in (
        "PRIVATE_QUESTION_SENTINEL",
        "PRIVATE_HISTORY_SENTINEL",
        "PRIVATE_PASSAGE_SENTINEL",
        "PRIVATE_ERROR_SENTINEL",
        "provider-private",
        "thread-1",
        "user-1",
        "client-1",
    ):
        assert forbidden not in rendered
    assert embedding["dimensions"] == 3
    assert "sha256" in embedding
    assert "vector" not in embedding
    assert [0.1, 0.2, 0.3] not in embedding.values()


def test_trace_events_are_ordered_and_off_mode_emits_nothing() -> None:
    active = trace()
    disabled = trace(mode="off")

    with capture_logs() as logs:
        active.emit("first", "turn.first")
        active.emit("second", "turn.second")
        disabled.emit("hidden", "turn.hidden")

    assert [log["event"] for log in logs] == ["first", "second"]
    assert [log["sequence"] for log in logs] == [1, 2]
    assert all(log["trace_id"] == "trace-1" for log in logs)
    assert disabled.last_stage == "turn.hidden"


def test_off_mode_emits_only_operational_events() -> None:
    disabled = trace(mode="off")

    with capture_logs() as logs:
        disabled.emit("diagnostic", "assistant.model.request", model="safe-model")
        disabled.emit(
            "chat_turn_failed",
            "stream.failed",
            operational=True,
            error_class="RuntimeError",
            error_code="turn_failed",
            error_message="PRIVATE_ERROR_SENTINEL",
        )

    assert [log["event"] for log in logs] == ["chat_turn_failed"]
    assert logs[0]["sequence"] == 2
    assert logs[0]["error_class"] == "RuntimeError"
    assert logs[0]["error_code"] == "turn_failed"
    assert "PRIVATE_ERROR_SENTINEL" not in str(logs[0])
    assert disabled.last_stage == "stream.failed"


def test_rate_headers_are_extracted_from_a_bounded_exception_chain() -> None:
    response = Response(
        429,
        request=Request("POST", "https://foundry.example/openai/v1/responses"),
        headers={
            "retry-after": "2.5",
            "x-ratelimit-limit-requests": "100",
            "x-ratelimit-reset-tokens": "1m250ms",
            "x-ratelimit-remaining-tokens": "not-a-number",
            "authorization": "PRIVATE_AUTHORIZATION",
        },
    )
    provider_error = RateLimitError(
        "PRIVATE_PROVIDER_MESSAGE",
        response=response,
        body={"message": "PRIVATE_BODY"},
    )
    wrapped = RuntimeError("PRIVATE_WRAPPER")
    wrapped.__cause__ = provider_error

    context = upstream_error_log_context(wrapped)

    assert context == {
        "upstream_status_code": 429,
        "rate_limit_requests": 100,
        "rate_reset_tokens_ms": 60_250,
        "retry_after_ms": 2_500,
    }
    assert "PRIVATE" not in str(context)
