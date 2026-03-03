"""FastAPI dependencies for authentication & authorization.

Usage in route files:
    from app.api.deps import require_permission

    @router.post("/something")
    async def do_something(user=Depends(require_permission("db_onboard"))):
        ...
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.auth_service import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
):
    """Extract and validate JWT from Authorization header.
    Returns the decoded payload dict with keys: sub, username, permissions, exp.
    """
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated – please log in",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(creds.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def require_permission(permission: str):
    """Return a dependency that checks the caller holds *permission*."""

    async def _check(user: dict = Depends(get_current_user)):
        perms = user.get("permissions", [])
        if permission not in perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required",
            )
        return user

    return _check
