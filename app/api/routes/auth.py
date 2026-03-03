"""Auth API routes – login, register, profile, user management."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
import logging

from app.database import get_db
from app.services.auth_service import (
    authenticate_user,
    create_user,
    create_access_token,
    get_user_permissions,
    get_user_by_username,
    VALID_PERMISSIONS,
)
from app.api.deps import get_current_user
from app.models import User, UserPermission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Request / Response models ─────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    permissions: List[str]


class RegisterRequest(BaseModel):
    username: str
    password: str
    permissions: List[str]  # e.g. ["db_onboard", "prompt_query"]


class RegisterResponse(BaseModel):
    id: int
    username: str
    permissions: List[str]
    message: str


class SignupRequest(BaseModel):
    username: str
    password: str


class SignupResponse(BaseModel):
    id: int
    username: str
    permissions: List[str]
    message: str


class UpdatePermissionsRequest(BaseModel):
    permissions: List[str]  # full replacement list


class ProfileResponse(BaseModel):
    id: int
    username: str
    permissions: List[str]
    is_active: bool


class UserListItem(BaseModel):
    id: int
    username: str
    permissions: List[str]
    is_active: bool


# ── Endpoints ─────────────────────────────────────────
@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return a JWT token (5-hour expiry)."""
    user = authenticate_user(db, request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    perms = get_user_permissions(db, user.id)
    token = create_access_token(user.id, user.username, perms)

    logger.info(f"User '{user.username}' logged in successfully")
    return LoginResponse(
        access_token=token,
        username=user.username,
        permissions=perms,
    )


@router.post("/register", response_model=RegisterResponse)
async def register_user(
    request: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a new user. Only existing authenticated users can register others."""
    try:
        user = create_user(db, request.username, request.password, request.permissions)
        perms = get_user_permissions(db, user.id)
        logger.info(f"User '{user.username}' created by '{current_user['username']}' with permissions {perms}")
        return RegisterResponse(
            id=user.id,
            username=user.username,
            permissions=perms,
            message="User created successfully",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/signup", response_model=SignupResponse)
async def signup(request: SignupRequest, db: Session = Depends(get_db)):
    """Public self-registration. New users always get prompt_query only."""
    try:
        user = create_user(db, request.username, request.password, ["prompt_query"])
        perms = get_user_permissions(db, user.id)
        logger.info(f"New user '{user.username}' signed up (self-registration)")
        return SignupResponse(
            id=user.id,
            username=user.username,
            permissions=perms,
            message="Account created! You can now sign in.",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/users/{user_id}/permissions")
async def update_user_permissions(
    user_id: int,
    request: UpdatePermissionsRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Update a user's permissions. Only users with db_onboard can do this."""
    caller_perms = current_user.get("permissions", [])
    if "db_onboard" not in caller_perms:
        raise HTTPException(status_code=403, detail="Only admins (db_onboard) can manage permissions")

    bad = set(request.permissions) - VALID_PERMISSIONS
    if bad:
        raise HTTPException(status_code=400, detail=f"Invalid permissions: {bad}")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete existing permissions and re-create
    db.query(UserPermission).filter(UserPermission.user_id == user_id).delete()
    for perm in set(request.permissions):
        db.add(UserPermission(user_id=user_id, permission=perm))
    db.commit()

    new_perms = get_user_permissions(db, user_id)
    logger.info(f"Permissions updated for '{user.username}' by '{current_user['username']}': {new_perms}")
    return {"id": user_id, "username": user.username, "permissions": new_perms, "message": "Permissions updated"}


@router.get("/me", response_model=ProfileResponse)
async def my_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's profile and permissions."""
    user = db.query(User).filter(User.id == int(current_user["sub"])).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    perms = get_user_permissions(db, user.id)
    return ProfileResponse(
        id=user.id,
        username=user.username,
        permissions=perms,
        is_active=user.is_active,
    )


@router.get("/users", response_model=List[UserListItem])
async def list_users(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all users (any authenticated user can view)."""
    users = db.query(User).all()
    result = []
    for u in users:
        perms = [p.permission for p in u.permissions]
        result.append(UserListItem(id=u.id, username=u.username, permissions=perms, is_active=u.is_active))
    return result


@router.get("/permissions")
async def available_permissions():
    """Return the list of valid permission names (public, no auth needed)."""
    return {
        "permissions": sorted(VALID_PERMISSIONS),
        "description": {
            "db_onboard": "Register / onboard new databases",
            "db_reindex": "Trigger reindex on existing databases",
            "prompt_query": "Use the chat prompt and view charts / data",
        },
    }
