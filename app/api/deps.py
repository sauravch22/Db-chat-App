"""FastAPI dependencies for authentication & DB-level authorization.

Usage in route files::

    from app.api.deps import get_current_user, has_db_permission

    @router.post("/something")
    async def do_something(user=Depends(get_current_user)):
        if not has_db_permission(user, connection_id, "prompt_query"):
            raise HTTPException(403, detail="...")
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import decode_access_token

_bearer = HTTPBearer(auto_error=False)


# ── Extract & validate JWT ────────────────────────────
async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
):
    """Extract and validate JWT from Authorization header.

    Returns the decoded payload dict with keys: sub, username, perms, exp.
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


# ── Permission helpers (work on the JWT payload dict) ─

def _user_perms(user: dict) -> dict:
    """Extract the ``perms`` dict from JWT payload."""
    return user.get("perms", {})


def has_db_permission(user: dict, connection_id: int, permission: str) -> bool:
    """Check if *user* has *permission* on *connection_id*.

    Hierarchy applied:
    * Global ``db_onboard`` (key ``"*"``) → everything on every DB.
    * ``db_onboard`` on a DB → ``db_reindex`` + ``prompt_query`` on that DB.
    * ``db_reindex`` on a DB → ``prompt_query`` on that DB.
    """
    perms = _user_perms(user)

    # Global db_onboard = superadmin
    if "db_onboard" in perms.get("*", []):
        return True

    db_perms = perms.get(str(connection_id), [])

    # Direct match
    if permission in db_perms:
        return True

    # db_onboard on this DB implies everything lower
    if "db_onboard" in db_perms:
        return True

    # db_reindex implies prompt_query
    if permission == "prompt_query" and "db_reindex" in db_perms:
        return True

    return False


def has_any_onboard(user: dict) -> bool:
    """Can this user register new databases?

    True if global ``db_onboard`` **or** ``db_onboard`` on any specific DB.
    """
    perms = _user_perms(user)
    if "db_onboard" in perms.get("*", []):
        return True
    for key, perm_list in perms.items():
        if key != "*" and "db_onboard" in perm_list:
            return True
    return False


def is_db_admin(user: dict, connection_id: int) -> bool:
    """Is *user* admin (``db_onboard``) of a specific DB?"""
    perms = _user_perms(user)
    if "db_onboard" in perms.get("*", []):
        return True
    return "db_onboard" in perms.get(str(connection_id), [])
