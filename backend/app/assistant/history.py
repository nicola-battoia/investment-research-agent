"""Bounded conversion from stored chat text to PydanticAI model history."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from app.assistant.outputs import HistoryMessage

MAX_HISTORY_TURNS = 3
MAX_HISTORY_CHARACTERS = 20_000
OLD_SOURCE_MARKER_RE = re.compile(r"\[S[1-9][0-9]*\]")


def build_message_history(history: Sequence[HistoryMessage]) -> list[ModelMessage]:
    """Keep only recent complete pairs and never carry old evidence/tool state."""
    if len(history) % 2:
        raise ValueError("Assistant history must contain complete user/assistant pairs")

    pairs: list[tuple[str, str]] = []
    for index in range(0, len(history), 2):
        user, assistant = history[index : index + 2]
        if user.role != "user" or assistant.role != "assistant":
            raise ValueError("Assistant history must alternate user then assistant")
        pairs.append(
            (
                _remove_old_source_ids(user.content),
                _remove_old_source_ids(assistant.content),
            )
        )

    selected: list[tuple[str, str]] = []
    character_count = 0
    for pair in reversed(pairs[-MAX_HISTORY_TURNS:]):
        pair_characters = len(pair[0]) + len(pair[1])
        if selected and character_count + pair_characters > MAX_HISTORY_CHARACTERS:
            break
        if pair_characters > MAX_HISTORY_CHARACTERS:
            continue
        selected.append(pair)
        character_count += pair_characters
    selected.reverse()

    messages: list[ModelMessage] = []
    for user_text, assistant_text in selected:
        messages.extend(
            (
                ModelRequest(parts=[UserPromptPart(content=user_text)]),
                ModelResponse(parts=[TextPart(content=assistant_text)]),
            )
        )
    return messages


def _remove_old_source_ids(content: str) -> str:
    cleaned = OLD_SOURCE_MARKER_RE.sub("", content).strip()
    if not cleaned:
        raise ValueError("History cannot consist only of old citation markers")
    return cleaned
