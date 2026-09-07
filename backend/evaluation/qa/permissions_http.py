"""Real JWT/PostgREST probes; only disposable QA accounts and chats are changed."""

import argparse
from pathlib import Path
from uuid import uuid4

import httpx

from app.config import settings
from evaluation.qa.identity import temporary_identity
from evaluation.qa.storage import connection, write_report


def outcome(
    name: str, response: httpx.Response, *, allowed: bool, removed_rpc: bool = False
) -> dict:
    actual = response.is_success and bool(response.json())
    valid = response.is_success or response.status_code in (401, 403)
    if removed_rpc:
        valid = valid or (
            response.status_code == 404 and response.json().get("code") == "PGRST202"
        )
    return {
        "name": name,
        "expected_allowed": allowed,
        "actual_allowed": actual,
        "http_status": response.status_code,
        "passed": valid and actual == allowed,
    }


def audit_http_permissions() -> list[dict]:
    with (
        temporary_identity() as first,
        temporary_identity() as second,
        httpx.Client(base_url=str(settings.supabase_url), timeout=30) as client,
    ):
        headers = {
            "apikey": settings.supabase_anon_key.get_secret_value(),
            "Authorization": f"Bearer {first}",
            "Prefer": "return=representation",
        }
        other_headers = {**headers, "Authorization": f"Bearer {second}"}
        anon_headers = {"apikey": headers["apikey"], "Prefer": "return=representation"}
        service_key = settings.supabase_service_role_key.get_secret_value()
        server_headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Prefer": "return=representation",
        }
        owner = client.get("/auth/v1/user", headers=headers)
        owner.raise_for_status()
        other = client.get("/auth/v1/user", headers=other_headers)
        other.raise_for_status()
        thread_id, message_id, user_message_id, citation_id = [
            str(uuid4()) for _ in range(4)
        ]
        thread_path = f"/rest/v1/chat_threads?id=eq.{thread_id}"
        message_path = f"/rest/v1/chat_messages?id=eq.{message_id}"
        citation_path = f"/rest/v1/message_citations?id=eq.{citation_id}"
        with connection(readonly=True) as conn:
            chunk = conn.execute(
                "SELECT id,left(text,120) AS excerpt FROM public.document_chunks ORDER BY id LIMIT 1"
            ).fetchone()
        created = client.post(
            "/rest/v1/chat_threads",
            headers=headers,
            json={
                "id": thread_id,
                "owner_id": owner.json()["id"],
                "title": "QA HTTP permissions",
            },
        )
        created.raise_for_status()
        checks = [outcome("owner_can_create_thread", created, allowed=True)]

        def check(name, response, *, allowed=False, removed_rpc=False):
            checks.append(
                outcome(name, response, allowed=allowed, removed_rpc=removed_rpc)
            )

        payload = {
            "p_thread_id": thread_id,
            "p_owner_id": owner.json()["id"],
            "p_expected_position": 0,
            "p_user_message_id": user_message_id,
            "p_user_content": "QA question",
            "p_user_message_data": {"clientMessageId": str(uuid4())},
            "p_assistant_message_id": message_id,
            "p_assistant_content": "QA server answer",
            "p_assistant_message_data": {
                "answerStatus": "supported",
                "parts": [{"type": "text", "text": "QA server answer"}],
            },
            "p_model_usage": {},
            "p_citations": [
                {
                    "id": citation_id,
                    "chunk_id": str(chunk["id"]),
                    "citation_index": 0,
                    "excerpt": chunk["excerpt"],
                }
            ],
            "p_first_turn_title": "QA HTTP",
        }
        rpc = "/rest/v1/rpc/complete_chat_turn"
        try:
            check(
                "anonymous_cannot_read_thread",
                client.get(thread_path, headers=anon_headers),
            )
            check(
                "other_user_cannot_read_thread",
                client.get(thread_path, headers=other_headers),
            )
            check(
                "other_user_cannot_rename_thread",
                client.patch(
                    thread_path, headers=other_headers, json={"title": "QA forged"}
                ),
            )
            check(
                "owner_cannot_transfer_thread",
                client.patch(
                    thread_path, headers=headers, json={"owner_id": other.json()["id"]}
                ),
            )
            legacy = {k: v for k, v in payload.items() if k != "p_owner_id"}
            check(
                "legacy_completion_rpc_is_unavailable",
                client.post(rpc, headers=headers, json=legacy),
                removed_rpc=True,
            )
            check(
                "user_cannot_complete_fabricated_turn",
                client.post(rpc, headers=headers, json=payload),
            )
            check(
                "anonymous_cannot_complete_turn",
                client.post(rpc, headers=anon_headers, json=payload),
            )
            check(
                "other_user_cannot_complete_turn_as_owner",
                client.post(rpc, headers=other_headers, json=payload),
            )
            loaded = client.get(message_path, headers=headers)
            loaded.raise_for_status()
            checks.append(
                {"name": "forged_answer_not_persisted", "passed": loaded.json() == []}
            )
            check(
                "server_cannot_save_for_wrong_owner",
                client.post(
                    rpc,
                    headers=server_headers,
                    json={**payload, "p_owner_id": other.json()["id"]},
                ),
            )
            check(
                "server_can_save_for_verified_owner",
                client.post(rpc, headers=server_headers, json=payload),
                allowed=True,
            )
            original = client.get(message_path, headers=headers)
            original.raise_for_status()
            assert len(original.json()) == 1, "Server fixture was not saved"
            check("owner_can_read_assistant", original, allowed=True)
            check(
                "other_user_cannot_read_assistant",
                client.get(message_path, headers=other_headers),
            )
            check(
                "other_user_cannot_read_citation",
                client.get(citation_path, headers=other_headers),
            )
            check(
                "owner_can_read_citation",
                client.get(citation_path, headers=headers),
                allowed=True,
            )
            for suffix, changes in (
                ("content", {"content": "QA forged"}),
                (
                    "display",
                    {
                        "message_data": {
                            "answerStatus": "supported",
                            "parts": [{"type": "text", "text": "QA forged"}],
                        }
                    },
                ),
                ("role", {"role": "user"}),
                ("usage", {"model_usage": {"totalTokens": 0}}),
            ):
                check(
                    f"user_cannot_edit_assistant_{suffix}",
                    client.patch(message_path, headers=headers, json=changes),
                )
            check(
                "user_cannot_edit_saved_question",
                client.patch(
                    f"/rest/v1/chat_messages?id=eq.{user_message_id}",
                    headers=headers,
                    json={"content": "QA forged"},
                ),
            )
            check(
                "user_cannot_delete_assistant",
                client.delete(message_path, headers=headers),
            )
            for role in ("user", "assistant"):
                check(
                    f"user_cannot_insert_{role}",
                    client.post(
                        "/rest/v1/chat_messages",
                        headers=headers,
                        json={
                            "id": str(uuid4()),
                            "thread_id": thread_id,
                            "position": 2,
                            "role": role,
                            "content": "QA forged",
                        },
                    ),
                )
            check(
                "user_cannot_upsert_assistant",
                client.post(
                    "/rest/v1/chat_messages?on_conflict=id",
                    headers={
                        **headers,
                        "Prefer": "resolution=merge-duplicates,return=representation",
                    },
                    json={
                        "id": message_id,
                        "thread_id": thread_id,
                        "position": 1,
                        "role": "assistant",
                        "content": "QA forged",
                    },
                ),
            )
            check(
                "user_cannot_edit_citation",
                client.patch(
                    citation_path,
                    headers=headers,
                    json={"excerpt": "QA fabricated evidence"},
                ),
            )
            check(
                "user_cannot_delete_citation",
                client.delete(citation_path, headers=headers),
            )
            check(
                "user_cannot_insert_citation",
                client.post(
                    "/rest/v1/message_citations",
                    headers=headers,
                    json={
                        "id": str(uuid4()),
                        "message_id": message_id,
                        "chunk_id": str(chunk["id"]),
                        "citation_index": 1,
                        "excerpt": "QA fabricated evidence",
                    },
                ),
            )
            readback = client.get(message_path, headers=headers)
            readback.raise_for_status()
            checks.append(
                {
                    "name": "assistant_unchanged_after_all_probes",
                    "passed": readback.json() == original.json(),
                }
            )
            readback = client.get(citation_path, headers=headers)
            readback.raise_for_status()
            checks.append(
                {
                    "name": "citation_unchanged_after_all_probes",
                    "passed": len(readback.json()) == 1
                    and readback.json()[0]["excerpt"] == chunk["excerpt"],
                }
            )
            check(
                "owner_can_rename_thread",
                client.patch(
                    thread_path, headers=headers, json={"title": "QA renamed"}
                ),
                allowed=True,
            )
            check(
                "owner_can_delete_thread",
                client.delete(thread_path, headers=headers),
                allowed=True,
            )
            for table, field, ident in (
                ("chat_messages", "thread_id", thread_id),
                ("message_citations", "message_id", message_id),
            ):
                remaining = client.get(
                    f"/rest/v1/{table}?{field}=eq.{ident}", headers=server_headers
                )
                remaining.raise_for_status()
                checks.append(
                    {
                        "name": f"thread_delete_removes_{table}",
                        "passed": remaining.json() == [],
                    }
                )
            return checks
        finally:
            deleted = client.delete(thread_path, headers=server_headers)
            deleted.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = audit_http_permissions()
    failures = [c for c in checks if not c["passed"]]
    write_report(
        args.output,
        {
            "scope": "real JWT and public PostgREST API",
            "temporary_accounts_deleted": True,
            "passed": len(checks) - len(failures),
            "failed": len(failures),
            "checks": checks,
        },
    )
    print(
        f"HTTP permissions: {len(checks) - len(failures)} passed, {len(failures)} failed"
    )
    for check in failures:
        print("FAIL:", check["name"], check.get("http_status"))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
