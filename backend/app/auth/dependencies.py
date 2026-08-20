"""FastAPI dependencies for Supabase bearer authentication."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import AsyncClient
from supabase_auth import User
from supabase_auth.errors import AuthError

from app.config import Settings
from app.database.supabase import create_user_supabase_client

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedContext:
    """Verified user and their request-scoped, RLS-aware Supabase client."""

    user: User
    supabase: AsyncClient


def authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_authenticated_context(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> AuthenticatedContext:
    """Verify one bearer token and return its user-scoped database context."""
    if credentials is None:
        raise authentication_error()

    access_token = credentials.credentials
    app_settings: Settings = request.app.state.settings
    client = await create_user_supabase_client(app_settings, access_token)

    try:
        response = await client.auth.get_user(access_token)
    except AuthError:
        raise authentication_error() from None

    if response is None:
        raise authentication_error()

    return AuthenticatedContext(user=response.user, supabase=client)


async def get_current_user(
    context: Annotated[AuthenticatedContext, Depends(get_authenticated_context)],
) -> User:
    """Return the Supabase user represented by a valid bearer token."""
    return context.user
