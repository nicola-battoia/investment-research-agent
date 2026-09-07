"""Collect diagnostics in the operator's report, without logging model prompts."""

from typing import Any

from app.assistant.tracing import AssistantTrace


def compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: compact(item)
            for key, item in value.items()
            if key
            not in {
                "input",
                "output",
                "text",
                "preview",
                "question",
                "embedding",
                "metadata",
                "passage",
                "answer",
                "draft",
                "history",
                "assistant_message_data",
                "user_message_data",
            }
        }
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


class ReportTrace(AssistantTrace):
    def __init__(self) -> None:
        super().__init__(
            trace_id="qa",
            thread_id="qa",
            user_id="qa",
            client_message_id="qa",
            mode="full",
            max_content_characters=3000,
        )
        self.events: list[dict] = []

    def emit(self, event: str, stage: str, **fields: object) -> None:
        self._sequence += 1
        self._last_stage = stage
        # The production serializer redacts secrets and omits private reasoning.
        self.events.append(
            {
                "stage": stage,
                "elapsed_ms": round(self.elapsed_ms, 1),
                **compact(self.serialize(fields)),
            }
        )


def evidence_from_trace(events: list[dict], rows: list[dict]) -> dict:
    identities = {
        (row["accession_number"], row["chunk_index"]): str(row["chunk_id"])
        for row in rows
    }
    retrieved: set[str] = set()
    read: set[str] = set()

    def collect(value: Any, target: set[str]) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item, target)
        elif isinstance(value, dict):
            key = (value.get("accession_number"), value.get("chunk_index"))
            if key in identities:
                target.add(identities[key])
            for item in value.values():
                collect(item, target)

    for event in events:
        if event["stage"] == "retrieval.search.completed":
            collect(event.get("ranked_passages"), retrieved)
            collect(event.get("context_passages"), retrieved)
        if event["stage"] == "assistant.tool.completed":
            if event.get("tool_name") in {"read_chunk", "read_surrounding_chunks"}:
                collect(event.get("result"), read)
            collect(event.get("result"), retrieved)
    return {"retrieved_chunk_ids": sorted(retrieved), "read_chunk_ids": sorted(read)}
