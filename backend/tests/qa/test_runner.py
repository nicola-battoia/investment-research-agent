import json
from types import SimpleNamespace

import httpx
import pytest

from evaluation.qa.dataset import load_dataset
from evaluation.qa.run import run_case
from evaluation.qa.trace import ReportTrace, evidence_from_trace


def response(*, payload=None, text=None, code=200):
    return httpx.Response(
        code,
        json=payload,
        text=text,
        request=httpx.Request("POST", "http://testserver/chat"),
    )


def test_http_200_with_sse_error_is_a_failed_turn_and_keeps_denominator():
    sse = 'data: {"type":"data-turn-error","data":{"code":"assistant_tool_calls_limit"}}\n\ndata: [DONE]\n\n'
    client = SimpleNamespace(
        post=lambda path, **_: (
            response(payload={"id": "thread"})
            if path == "/chat/threads"
            else response(text=sse)
        ),
        get=lambda *_a, **_k: response(payload={"messages": []}),
        delete=lambda *_a, **_k: response(code=204),
    )
    result = run_case(client, {}, load_dataset().cases[0], [])
    assert result["status"] == "failed"
    assert result["error_code"] == "assistant_tool_calls_limit"
    assert result["evaluation"]["retrieval"]["recall"] == 0
    assert not result["evaluation"]["failed_turn_persisted"]


@pytest.mark.parametrize(
    "stored_text, expected", [("answer", "completed"), ("different", "failed")]
)
def test_stream_completion_requires_persisted_answer_match(stored_text, expected):
    events = [{"type": "text-delta", "delta": "answer"}, {"type": "finish"}]
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    client = SimpleNamespace(
        post=lambda path, **_: (
            response(payload={"id": "thread"})
            if path == "/chat/threads"
            else response(text=sse)
        ),
        get=lambda *_a, **_k: response(
            payload={
                "messages": [
                    {
                        "role": "assistant",
                        "parts": [{"type": "text", "text": stored_text}],
                    }
                ]
            }
        ),
        delete=lambda *_a, **_k: response(code=204),
    )
    assert run_case(client, {}, load_dataset().cases[0], [])["status"] == expected


def test_partial_trace_keeps_retrieved_and_read_separate_and_redacts_secrets():
    trace = ReportTrace()
    passage = {
        "accession_number": "filing",
        "chunk_index": 3,
        "chunk_id": "chunk",
        "text": "Do not retain full source text here",
    }
    trace.emit(
        "search",
        "retrieval.search.completed",
        ranked_passages=[passage],
        authorization="Bearer secret",
    )
    trace.emit("failed", "stream.failed", error_code="assistant_tool_calls_limit")
    evidence = evidence_from_trace(trace.events, [passage])
    assert evidence["retrieved_chunk_ids"] == ["chunk"]
    assert evidence["read_chunk_ids"] == []
    assert trace.events[0]["authorization"] == "[REDACTED]"
    assert "text" not in trace.events[0]["ranked_passages"][0]
