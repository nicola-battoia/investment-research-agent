"""Supabase clients for user-scoped and privileged database access."""

from supabase import AsyncClient, AsyncClientOptions, acreate_client

from app.config import Settings


async def create_user_supabase_client(
    app_settings: Settings,
    access_token: str,
) -> AsyncClient:
    """Create a client whose database requests run with one user's JWT."""
    if not access_token:
        raise ValueError("A Supabase access token is required")

    return await acreate_client(
        supabase_url=str(app_settings.supabase_url),
        supabase_key=app_settings.supabase_anon_key.get_secret_value(),
        options=AsyncClientOptions(
            auto_refresh_token=False,
            persist_session=False,
            headers={"Authorization": f"Bearer {access_token}"},
        ),
    )


async def create_admin_supabase_client(app_settings: Settings) -> AsyncClient:
    """Create a server-only client that bypasses RLS with the service-role key."""
    return await acreate_client(
        supabase_url=str(app_settings.supabase_url),
        supabase_key=app_settings.supabase_service_role_key.get_secret_value(),
        options=AsyncClientOptions(
            auto_refresh_token=False,
            persist_session=False,
        ),
    )
