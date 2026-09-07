"""A temporary, confirmed QA account; no emails or real user sessions involved."""

from collections.abc import Iterator
from contextlib import contextmanager
from secrets import token_urlsafe
from uuid import uuid4

import httpx

from app.config import settings


@contextmanager
def temporary_identity() -> Iterator[str]:
    service_key = settings.supabase_service_role_key.get_secret_value()
    admin_headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    credentials = {
        "email": f"qa-{uuid4()}@example.invalid",
        "password": token_urlsafe(32),
    }
    with httpx.Client(base_url=str(settings.supabase_url), timeout=30) as auth:
        created = auth.post(
            "/auth/v1/admin/users",
            headers=admin_headers,
            json={**credentials, "email_confirm": True},
        )
        created.raise_for_status()
        user_id = created.json()["id"]
        try:
            signed_in = auth.post(
                "/auth/v1/token?grant_type=password",
                headers={"apikey": settings.supabase_anon_key.get_secret_value()},
                json=credentials,
            )
            signed_in.raise_for_status()
            yield signed_in.json()["access_token"]
        finally:
            deleted = auth.delete(
                f"/auth/v1/admin/users/{user_id}", headers=admin_headers
            )
            deleted.raise_for_status()
