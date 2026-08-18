"""FastAPI dependencies for Supabase bearer authentication."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase_auth import User
from supabase_auth.errors import AuthError

from app.config import Settings
from app.database.supabase import create_user_supabase_client

bearer_scheme = HTTPBearer(auto_error=False)


def authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> User:
    """Return the Supabase user represented by a valid bearer token."""
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

    return response.user
