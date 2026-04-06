"""Auth API routes – login, signup, profile, DB-level permission management."""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
import logging

from app.database import get_db
from app.services.auth_service import (
    authenticate_user,
    create_user,
    create_access_token,
    get_user_perms_dict,
    get_user_by_username,
    set_db_permissions,
    VALID_PERMISSIONS,
)
from app.services.activity_service import log_activity, Actions
from app.api.deps import get_current_user, is_db_admin, has_any_onboard
from app.models import User, UserPermission, Connection, TableAccess

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
    perms: Dict[str, List[str]]  # {"*": ["db_onboard"], "3": [...]}


class SignupRequest(BaseModel):
    username: str
    password: str


class SignupResponse(BaseModel):
    id: int
    username: str
    message: str


class ProfileResponse(BaseModel):
    id: int
    username: str
    perms: Dict[str, List[str]]
    accessible_dbs: List[dict]
    is_active: bool


class DbPermissionsRequest(BaseModel):
    connection_id: int
    permissions: List[str]


class UserDbPermsItem(BaseModel):
    id: int
    username: str
    is_active: bool
    permissions: List[str]


# ── Login ─────────────────────────────────────────────
@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, req: Request = None, db: Session = Depends(get_db)):
    """Authenticate and return a JWT token (5-hour expiry)."""
    user = authenticate_user(db, request.username, request.password)
    if not user:
        await log_activity(req, action=Actions.LOGIN_FAILED, status="failed",
                           detail={"username": request.username}, db=db)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    perms = get_user_perms_dict(db, user.id)
    token = create_access_token(user.id, user.username, perms)

    await log_activity(req, user={"sub": str(user.id), "username": user.username},
                       action=Actions.LOGIN, detail={"perms": perms}, db=db)
    logger.info(f"User '{user.username}' logged in")
    return LoginResponse(access_token=token, username=user.username, perms=perms)


# ── Public Signup ─────────────────────────────────────
@router.post("/signup", response_model=SignupResponse)
async def signup(request: SignupRequest, req: Request = None, db: Session = Depends(get_db)):
    """Public self-registration.

    New users get **zero** permissions — they cannot access any database
    until an admin grants them per-DB access.
    """
    try:
        user = create_user(db, request.username, request.password)
        await log_activity(req, user={"sub": str(user.id), "username": user.username},
                           action=Actions.SIGNUP, resource_type="user", resource_id=user.id, db=db)
        logger.info(f"New user '{user.username}' signed up (no permissions)")
        return SignupResponse(
            id=user.id,
            username=user.username,
            message="Account created! Ask an admin to grant you database access.",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── My Profile ────────────────────────────────────────
@router.get("/me", response_model=ProfileResponse)
async def my_profile(
    req: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's profile, permissions, and accessible databases."""
    user = db.query(User).filter(User.id == int(current_user["sub"])).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    perms = get_user_perms_dict(db, user.id)

    # Build accessible DB list
    is_global_admin = "db_onboard" in perms.get("*", [])
    if is_global_admin:
        connections = db.query(Connection).filter(Connection.is_active == True).all()
    else:
        conn_ids = [int(k) for k in perms.keys() if k != "*" and perms[k]]
        if conn_ids:
            connections = db.query(Connection).filter(
                Connection.id.in_(conn_ids), Connection.is_active == True
            ).all()
        else:
            connections = []

    accessible = [{"id": c.id, "name": c.name} for c in connections]

    await log_activity(req, user=current_user, action=Actions.TOKEN_REFRESH, db=db)

    return ProfileResponse(
        id=user.id,
        username=user.username,
        perms=perms,
        accessible_dbs=accessible,
        is_active=user.is_active,
    )


# ── List all users ────────────────────────────────────
@router.get("/users")
async def list_users(
    req: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all users with their full permission maps."""
    await log_activity(req, user=current_user, action=Actions.VIEW_USERS, db=db)
    users = db.query(User).all()
    result = []
    for u in users:
        perms = get_user_perms_dict(db, u.id)
        result.append({
            "id": u.id,
            "username": u.username,
            "is_active": u.is_active,
            "perms": perms,
        })
    return result


# ── Users for a specific DB ──────────────────────────
@router.get("/users/db/{connection_id}", response_model=List[UserDbPermsItem])
async def list_users_for_db(
    connection_id: int,
    req: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all users with their permissions for a specific database.

    Only admins of this DB can view this.
    """
    if not is_db_admin(current_user, connection_id):
        await log_activity(req, user=current_user, action=Actions.PERM_DENIED,
                           connection_id=connection_id, status="denied",
                           detail={"attempted": "view_db_users"}, db=db)
        raise HTTPException(
            status_code=403,
            detail="Only admins of this database can view its users",
        )

    conn = db.query(Connection).filter(Connection.id == connection_id).first()
    if not conn:
        raise HTTPException(status_code=404, detail="Database not found")

    await log_activity(req, user=current_user, action=Actions.VIEW_DB_USERS,
                       connection_id=connection_id, resource_type="connection",
                       resource_id=connection_id, db=db)

    users = db.query(User).all()
    result = []
    for u in users:
        user_perms = (
            db.query(UserPermission)
            .filter(
                UserPermission.user_id == u.id,
                UserPermission.connection_id == connection_id,
            )
            .all()
        )
        result.append(
            UserDbPermsItem(
                id=u.id,
                username=u.username,
                is_active=u.is_active,
                permissions=[p.permission for p in user_perms],
            )
        )
    return result


# ── Update user permissions on a DB ──────────────────
@router.put("/users/{user_id}/db-permissions")
async def update_user_db_permissions(
    user_id: int,
    request: DbPermissionsRequest,
    req: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set permissions for a user on a specific database.

    Caller must be admin (``db_onboard``) on that database.
    """
    if not is_db_admin(current_user, request.connection_id):
        await log_activity(req, user=current_user, action=Actions.PERM_DENIED,
                           connection_id=request.connection_id, status="denied",
                           detail={"attempted": "update_perm", "target_user": user_id}, db=db)
        raise HTTPException(
            status_code=403,
            detail="Only admins of this database can manage its permissions",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        set_db_permissions(db, user_id, request.connection_id, request.permissions)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    new_perms = (
        db.query(UserPermission)
        .filter(
            UserPermission.user_id == user_id,
            UserPermission.connection_id == request.connection_id,
        )
        .all()
    )
    perm_list = [p.permission for p in new_perms]

    await log_activity(req, user=current_user, action=Actions.UPDATE_PERM,
                       connection_id=request.connection_id, resource_type="user",
                       resource_id=user_id,
                       detail={"target_user": user.username, "permissions": perm_list}, db=db)
    logger.info(
        f"Perms updated for '{user.username}' on conn {request.connection_id}: {perm_list} "
        f"by '{current_user['username']}'"
    )
    return {
        "user_id": user_id,
        "username": user.username,
        "connection_id": request.connection_id,
        "permissions": perm_list,
    }


# ── Available permissions (public) ────────────────────
@router.get("/permissions")
async def available_permissions():
    """Return the list of valid permission names (public, no auth needed)."""
    return {
        "permissions": sorted(VALID_PERMISSIONS),
        "description": {
            "db_onboard": "Admin of a database — manage users, reindex, query",
            "db_reindex": "Can reindex and query a database",
            "prompt_query": "Can query a database (chat and view charts)",
        },
    }


# ── Table-level access control ───────────────────────


class TableAccessRequest(BaseModel):
    user_id: int
    connection_id: int
    tables: List[str]


@router.get("/table-access/{connection_id}/{user_id}")
async def get_table_access(
    connection_id: int,
    user_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the table allowlist for a user on a connection.

    Empty list means the user can see ALL tables (no restrictions).
    """
    if not is_db_admin(current_user, connection_id):
        raise HTTPException(403, "Only admins of this database can view table access")

    rows = (
        db.query(TableAccess)
        .filter(
            TableAccess.user_id == user_id,
            TableAccess.connection_id == connection_id,
        )
        .order_by(TableAccess.table_name)
        .all()
    )
    return {
        "user_id": user_id,
        "connection_id": connection_id,
        "allowed_tables": [r.table_name for r in rows],
        "mode": "restricted" if rows else "all",
    }


@router.put("/table-access")
async def set_table_access(
    request: TableAccessRequest,
    req: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set the table allowlist for a user on a connection.

    Pass an empty `tables` list to remove restrictions (allow all).
    Pass a non-empty list to restrict the user to only those tables.
    """
    if not is_db_admin(current_user, request.connection_id):
        raise HTTPException(403, "Only admins of this database can manage table access")

    user = db.query(User).filter(User.id == request.user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    db.query(TableAccess).filter(
        TableAccess.user_id == request.user_id,
        TableAccess.connection_id == request.connection_id,
    ).delete()

    admin_id = int(current_user["sub"])
    for tbl in request.tables:
        db.add(TableAccess(
            user_id=request.user_id,
            connection_id=request.connection_id,
            table_name=tbl.strip(),
            created_by=admin_id,
        ))
    db.commit()

    await log_activity(
        req, user=current_user, action=Actions.UPDATE_PERM,
        connection_id=request.connection_id,
        resource_type="table_access", resource_id=request.user_id,
        detail={
            "target_user": user.username,
            "tables": request.tables,
            "mode": "restricted" if request.tables else "all",
        },
        db=db,
    )

    return {
        "user_id": request.user_id,
        "connection_id": request.connection_id,
        "allowed_tables": request.tables,
        "mode": "restricted" if request.tables else "all",
    }


@router.get("/table-access/available/{connection_id}")
async def list_available_tables(
    connection_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all indexed tables for a connection (for the admin UI picker)."""
    if not is_db_admin(current_user, connection_id):
        raise HTTPException(403, "Only admins can view this")

    from app.models import Table
    tables = (
        db.query(Table.name)
        .filter(Table.connection_id == connection_id)
        .order_by(Table.name)
        .all()
    )
    return {"connection_id": connection_id, "tables": [t[0] for t in tables]}
