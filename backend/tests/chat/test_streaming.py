import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from openai import APIConnectionError
from pydantic_ai.exceptions import UsageLimitExceeded
from structlog.testing import capture_logs

from app.chat.messages import MessageMetadata, TextPart, UIMessageResponse
from app.chat.orchestrator import PreparedChatTurn
from app.chat.streaming import chat_turn_events
from app.grounding import GroundingFailureError


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


class DisconnectedRequest:
    async def is_disconnected(self) -> bool:
        return True


def prepared_turn() -> PreparedChatTurn:
    return PreparedChatTurn(
        thread_id=UUID(int=1),
        user_id=UUID(int=2),
        user_message=SimpleNamespace(client_id="client-1", content="Question"),
        expected_position=0,
        history_rows=(),
    )


def completed_message() -> UIMessageResponse:
    return UIMessageResponse(
        id=str(UUID(int=3)),
        role="assistant",
        parts=[TextPart(type="text", text="Validated answer.")],
        metadata=MessageMetadata(
            created_at=datetime(2026, 8, 21, tzinfo=UTC),
            answer_status="supported",
        ),
    )


async def collect(orchestrator: object, *, timeout_seconds: float = 1) -> str:
    events = []
    async for event in chat_turn_events(
        request=ConnectedRequest(),
        orchestrator=orchestrator,
        turn=prepared_turn(),
        timeout_seconds=timeout_seconds,
    ):
        events.append(event)
    return "".join(events)


def test_success_streams_status_then_completed_message() -> None:
    orchestrator = SimpleNamespace(complete=AsyncMock(return_value=completed_message()))

    payload = asyncio.run(collect(orchestrator))

    assert payload.index('"type":"data-turn-status"') < payload.index('"type":"start"')
    assert '"delta":"Validated answer."' in payload
    assert '"finishReason":"stop"' in payload
    assert payload.endswith("data: [DONE]\n\n")


def test_grounding_failure_never_looks_like_a_completed_answer() -> None:
    orchestrator = SimpleNamespace(
        complete=AsyncMock(side_effect=GroundingFailureError("invalid citation"))
    )

    payload = asyncio.run(collect(orchestrator))

    assert '"code":"grounding_failed"' in payload
    assert '"type":"error"' in payload
    assert '"type":"start"' not in payload
    assert '"type":"finish"' not in payload


def test_openai_failure_uses_retryable_upstream_protocol() -> None:
    orchestrator = SimpleNamespace(
        complete=AsyncMock(side_effect=APIConnectionError(request=SimpleNamespace()))
    )

    payload = asyncio.run(collect(orchestrator))

    assert '"code":"assistant_unavailable"' in payload
    assert '"retryable":true' in payload
    assert '"type":"start"' not in payload


@pytest.mark.parametrize(
    ("reason", "expected_limit", "expected_code"),
    [
        (
            "The next request would exceed the request_limit of 8",
            "request_limit",
            "assistant_request_limit",
        ),
        (
            (
                "The next tool call(s) would exceed the tool_calls_limit of 12 "
                "(tool_calls=13)"
            ),
            "tool_calls_limit",
            "assistant_tool_calls_limit",
        ),
        (
            "Exceeded the output_tokens_limit of 6000 (output_tokens=7000)",
            "output_tokens_limit",
            "assistant_output_tokens_limit",
        ),
        (
            (
                "Exceeded the per_request_input_tokens_limit of 64000 "
                "(request_input_tokens=65000)"
            ),
            "per_request_input_tokens_limit",
            "assistant_context_limit",
        ),
    ],
)
def test_usage_limit_failure_identifies_limit_in_stream_and_log(
    reason: str,
    expected_limit: str,
    expected_code: str,
) -> None:
    orchestrator = SimpleNamespace(
        complete=AsyncMock(side_effect=UsageLimitExceeded(reason))
    )

    with capture_logs() as logs:
        payload = asyncio.run(collect(orchestrator))

    assert f'"code":"{expected_code}"' in payload
    assert '"retryable":true' in payload
    assert '"type":"start"' not in payload
    failure_log = next(log for log in logs if log["event"] == "chat_turn_failed")
    assert failure_log["error_code"] == expected_code
    assert failure_log["usage_limit"] == expected_limit
    assert failure_log["error_message"] == reason


def test_unknown_usage_limit_has_stable_fallback_and_diagnostic() -> None:
    reason = "A future usage constraint was exceeded"
    orchestrator = SimpleNamespace(
        complete=AsyncMock(side_effect=UsageLimitExceeded(reason))
    )

    with capture_logs() as logs:
        payload = asyncio.run(collect(orchestrator))

    assert '"code":"assistant_usage_limit"' in payload
    failure_log = next(log for log in logs if log["event"] == "chat_turn_failed")
    assert failure_log["usage_limit"] == "unknown"
    assert failure_log["error_message"] == reason


def test_timeout_cancels_the_turn_without_streaming_completion() -> None:
    cancelled = asyncio.Event()

    async def complete(_turn):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.set()

    orchestrator = SimpleNamespace(complete=complete)

    fast_stream_settings = SimpleNamespace(chat_stream_heartbeat_seconds=0.001)
    with patch("app.chat.streaming.settings", fast_stream_settings):
        payload = asyncio.run(collect(orchestrator, timeout_seconds=0.005))

    assert '"code":"turn_timeout"' in payload
    assert '"type":"start"' not in payload
    assert cancelled.is_set()


def test_client_disconnect_cancels_without_an_error_or_completed_message() -> None:
    cancelled = asyncio.Event()

    async def complete(_turn):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.set()

    async def run() -> str:
        events = []
        async for event in chat_turn_events(
            request=DisconnectedRequest(),
            orchestrator=SimpleNamespace(complete=complete),
            turn=prepared_turn(),
            timeout_seconds=1,
        ):
            events.append(event)
        return "".join(events)

    fast_stream_settings = SimpleNamespace(chat_stream_heartbeat_seconds=0.001)
    with patch("app.chat.streaming.settings", fast_stream_settings):
        payload = asyncio.run(run())

    assert '"type":"data-turn-status"' in payload
    assert '"type":"start"' not in payload
    assert '"type":"error"' not in payload
    assert cancelled.is_set()
