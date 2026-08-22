"""Opt-in HTTP coverage for the complete authenticated chat path."""

import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def live_client() -> tuple[TestClient, dict[str, str]]:
    access_token = os.environ.get("SUPABASE_TEST_ACCESS_TOKEN")
    if not access_token:
        pytest.skip("SUPABASE_TEST_ACCESS_TOKEN is required for live chat tests")

    from app.config import settings
    from app.main import create_app

    return TestClient(create_app(settings)), {
        "Authorization": f"Bearer {access_token}",
    }


def test_live_cited_turn_streams_and_survives_reload() -> None:
    client, headers = live_client()
    with client:
        thread = client.post("/chat/threads", headers=headers, json={}).json()
        try:
            response = client.post(
                "/chat/stream",
                headers=headers,
                json={
                    "id": thread["id"],
                    "message": {
                        "id": "live-cited-turn",
                        "role": "user",
                        "parts": [
                            {
                                "type": "text",
                                "text": (
                                    "According to Apple's 2024 10-K, what drove the "
                                    "increase in Services net sales?"
                                ),
                            }
                        ],
                    },
                },
            )

            assert response.status_code == 200
            assert '"type":"data-citation"' in response.text
            loaded = client.get(
                f"/chat/threads/{thread['id']}",
                headers=headers,
            ).json()
            assert loaded["messages"][-1]["metadata"]["answerStatus"] == "supported"
            assert any(
                part["type"] == "data-citation"
                for part in loaded["messages"][-1]["parts"]
            )
        finally:
            client.delete(f"/chat/threads/{thread['id']}", headers=headers)


def test_live_insufficient_evidence_turn_streams_and_survives_reload() -> None:
    client, headers = live_client()
    with client:
        thread = client.post("/chat/threads", headers=headers, json={}).json()
        try:
            response = client.post(
                "/chat/stream",
                headers=headers,
                json={
                    "id": thread["id"],
                    "message": {
                        "id": "live-insufficient-turn",
                        "role": "user",
                        "parts": [
                            {
                                "type": "text",
                                "text": (
                                    "What color were the walls in Apple's executive "
                                    "offices in fiscal 2024?"
                                ),
                            }
                        ],
                    },
                },
            )

            assert response.status_code == 200
            assert '"answerStatus":"insufficient_evidence"' in response.text
            assert '"type":"data-citation"' not in response.text
            loaded = client.get(
                f"/chat/threads/{thread['id']}",
                headers=headers,
            ).json()
            assert (
                loaded["messages"][-1]["metadata"]["answerStatus"]
                == "insufficient_evidence"
            )
        finally:
            client.delete(f"/chat/threads/{thread['id']}", headers=headers)
