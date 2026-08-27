from structlog.testing import capture_logs

from app.assistant.tracing import AssistantTrace, embedding_summary


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


def test_summary_trace_uses_short_preview_and_embedding_never_contains_vector() -> None:
    serialized = trace(mode="summary", limit=12_000).serialize("x" * 500)
    embedding = embedding_summary([0.1, 0.2, 0.3])

    assert len(serialized["preview"]) == 320
    assert serialized["characters"] == 500
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
