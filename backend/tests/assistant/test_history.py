import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse

from app.assistant.history import build_message_history
from app.assistant.outputs import HistoryMessage


def turn(index: int, *, size: int = 0) -> list[HistoryMessage]:
    suffix = "x" * size
    return [
        HistoryMessage(role="user", content=f"question {index}{suffix}"),
        HistoryMessage(
            role="assistant",
            content=f"answer {index} [S{index}]{suffix}",
        ),
    ]


def test_keeps_only_three_latest_complete_turns_and_removes_old_markers() -> None:
    history = [message for index in range(1, 6) for message in turn(index)]

    messages = build_message_history(history)

    assert len(messages) == 6
    assert isinstance(messages[0], ModelRequest)
    assert messages[0].parts[0].content == "question 3"
    assert isinstance(messages[1], ModelResponse)
    assert messages[1].parts[0].content == "answer 3"
    assert messages[-1].parts[0].content == "answer 5"


def test_drops_older_pairs_to_respect_character_budget() -> None:
    history = [*turn(1, size=6_000), *turn(2, size=6_000)]

    messages = build_message_history(history)

    assert len(messages) == 2
    assert messages[0].parts[0].content.startswith("question 2")


@pytest.mark.parametrize(
    "history",
    [
        [HistoryMessage(role="user", content="unfinished")],
        [
            HistoryMessage(role="assistant", content="wrong order"),
            HistoryMessage(role="user", content="wrong order"),
        ],
    ],
)
def test_rejects_incomplete_or_misordered_history(
    history: list[HistoryMessage],
) -> None:
    with pytest.raises(ValueError, match="history|History"):
        build_message_history(history)
