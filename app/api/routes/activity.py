"""Activity Log API routes — view the full audit trail of every action."""

from fastapi import APIRouter, HTTPException, Depends, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List, Optional
from datetime import datetime, timedelta
import logging

from app.database import get_db
from app.models import ActivityLog, Connection, User
from app.api.deps import get_current_user, has_db_permission, is_db_admin
from app.services.activity_service import log_activity, Actions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/activity", tags=["activity"])


# ── Shared serializer ────────────────────────────────
def _serialize_log(log, include_connection_id=False):
    """Return a dict for a single ActivityLog row."""
    d = {
        "id": log.id,
        "user_id": log.user_id,
        "username": log.username,
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "status": log.status,
        "detail": log.detail,
        "ip_address": log.ip_address,
        "duration_ms": log.duration_ms,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
    if include_connection_id:
        d["connection_id"] = log.connection_id
    return d


def _apply_common_filters(q, *, action=None, status=None, username=None,
                           connection_id=None, hours=None):
    """Apply common filter parameters to a query."""
    if action:
        q = q.filter(ActivityLog.action == action)
    if status:
        q = q.filter(ActivityLog.status == status)
    if username:
        q = q.filter(ActivityLog.username.ilike(f"%{username}%"))
    if connection_id is not None:
        q = q.filter(ActivityLog.connection_id == connection_id)
    if hours:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        q = q.filter(ActivityLog.created_at >= cutoff)
    return q


# ══════════════════════════════════════════════════════
#  MY ACTIVITY (any logged-in user can see their own)
# ══════════════════════════════════════════════════════
@router.get("/me")
async def get_my_activity(
    req: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = None,
    status: Optional[str] = None,
    connection_id: Optional[int] = None,
    hours: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return activity logs for the currently logged-in user.

    Every user can view their **own** activity — no admin required.
    """
    user_id = int(current_user["sub"])
    q = db.query(ActivityLog).filter(ActivityLog.user_id == user_id)
    q = _apply_common_filters(q, action=action, status=status,
                              connection_id=connection_id, hours=hours)

    total = q.count()
    logs = q.order_by(desc(ActivityLog.created_at)).offset(offset).limit(limit).all()

    return {
        "user_id": user_id,
        "username": current_user.get("username"),
        "total": total,
        "offset": offset,
        "limit": limit,
        "logs": [_serialize_log(log, include_connection_id=True) for log in logs],
    }


@router.get("/me/stats")
async def get_my_stats(
    req: Request,
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return aggregated activity stats for the currently logged-in user."""
    user_id = int(current_user["sub"])
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    q = db.query(ActivityLog).filter(
        ActivityLog.user_id == user_id,
        ActivityLog.created_at >= cutoff,
    )

    total = q.count()
    action_counts = (
        q.with_entities(ActivityLog.action, func.count(ActivityLog.id))
        .group_by(ActivityLog.action).all()
    )
    status_counts = (
        q.with_entities(ActivityLog.status, func.count(ActivityLog.id))
        .group_by(ActivityLog.status).all()
    )

    return {
        "user_id": user_id,
        "hours": hours,
        "total_events": total,
        "by_action": {a: c for a, c in action_counts},
        "by_status": {s: c for s, c in status_counts},
    }


# ══════════════════════════════════════════════════════
#  USER-SPECIFIC ACTIVITY (admin can view any user)
# ══════════════════════════════════════════════════════
@router.get("/user/{user_id}")
async def get_user_activity(
    user_id: int,
    req: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = None,
    status: Optional[str] = None,
    connection_id: Optional[int] = None,
    hours: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return activity logs for a specific user.

    Requires **global admin** (``db_onboard`` on ``*``).
    """
    perms = current_user.get("perms", {})
    if "db_onboard" not in perms.get("*", []):
        raise HTTPException(status_code=403, detail="Only global admins can view other users' activity")

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    q = db.query(ActivityLog).filter(ActivityLog.user_id == user_id)
    q = _apply_common_filters(q, action=action, status=status,
                              connection_id=connection_id, hours=hours)

    total = q.count()
    logs = q.order_by(desc(ActivityLog.created_at)).offset(offset).limit(limit).all()

    return {
        "user_id": user_id,
        "username": target_user.username,
        "total": total,
        "offset": offset,
        "limit": limit,
        "logs": [_serialize_log(log, include_connection_id=True) for log in logs],
    }


@router.get("/user/{user_id}/stats")
async def get_user_stats(
    user_id: int,
    req: Request,
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return aggregated stats for a specific user (admin only)."""
    perms = current_user.get("perms", {})
    if "db_onboard" not in perms.get("*", []):
        raise HTTPException(status_code=403, detail="Only global admins can view other users' stats")

    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    q = db.query(ActivityLog).filter(
        ActivityLog.user_id == user_id,
        ActivityLog.created_at >= cutoff,
    )

    total = q.count()
    action_counts = (
        q.with_entities(ActivityLog.action, func.count(ActivityLog.id))
        .group_by(ActivityLog.action).all()
    )
    status_counts = (
        q.with_entities(ActivityLog.status, func.count(ActivityLog.id))
        .group_by(ActivityLog.status).all()
    )

    return {
        "user_id": user_id,
        "username": target_user.username,
        "hours": hours,
        "total_events": total,
        "by_action": {a: c for a, c in action_counts},
        "by_status": {s: c for s, c in status_counts},
    }


# ══════════════════════════════════════════════════════
#  DATABASE-SCOPED ACTIVITY (db admin)
# ══════════════════════════════════════════════════════
@router.get("/db/{connection_id}")
async def get_db_activity(
    connection_id: int,
    req: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = None,
    status: Optional[str] = None,
    username: Optional[str] = None,
    hours: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return activity logs for a specific database.

    Requires ``db_onboard`` (admin) on the database.
    Supports filtering by action, status, username, and time window.
    """
    if not is_db_admin(current_user, connection_id):
        await log_activity(req, user=current_user, action=Actions.PERM_DENIED,
                           connection_id=connection_id, status="denied",
                           detail={"attempted": "view_activity_log"}, db=db)
        raise HTTPException(status_code=403, detail="Only database admins can view activity logs")

    conn = db.query(Connection).filter(Connection.id == connection_id).first()
    if not conn:
        raise HTTPException(status_code=404, detail="Database not found")

    q = db.query(ActivityLog).filter(ActivityLog.connection_id == connection_id)
    q = _apply_common_filters(q, action=action, status=status,
                              username=username, hours=hours)

    total = q.count()
    logs = q.order_by(desc(ActivityLog.created_at)).offset(offset).limit(limit).all()

    return {
        "connection_id": connection_id,
        "connection_name": conn.name,
        "total": total,
        "offset": offset,
        "limit": limit,
        "logs": [_serialize_log(log) for log in logs],
    }


# ── Global activity log (all databases) ───────────────
@router.get("/global")
async def get_global_activity(
    req: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = None,
    status: Optional[str] = None,
    username: Optional[str] = None,
    connection_id: Optional[int] = None,
    hours: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return the global activity log (all databases + auth events).

    Requires **global** ``db_onboard`` (superadmin).
    """
    perms = current_user.get("perms", {})
    if "db_onboard" not in perms.get("*", []):
        await log_activity(req, user=current_user, action=Actions.PERM_DENIED,
                           status="denied",
                           detail={"attempted": "view_global_activity_log"}, db=db)
        raise HTTPException(status_code=403, detail="Only global admins can view the full activity log")

    q = db.query(ActivityLog)
    q = _apply_common_filters(q, action=action, status=status,
                              username=username, connection_id=connection_id,
                              hours=hours)

    total = q.count()
    logs = q.order_by(desc(ActivityLog.created_at)).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "logs": [_serialize_log(log, include_connection_id=True) for log in logs],
    }


# ── Stats summary ─────────────────────────────────────
@router.get("/stats")
async def get_activity_stats(
    req: Request,
    connection_id: Optional[int] = None,
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return aggregated activity statistics.

    If ``connection_id`` is given, scoped to that DB (requires db_admin).
    Otherwise returns global stats (requires global admin).
    """
    perms = current_user.get("perms", {})
    is_global = "db_onboard" in perms.get("*", [])

    if connection_id is not None:
        if not is_db_admin(current_user, connection_id):
            raise HTTPException(status_code=403, detail="Admin access required")
    else:
        if not is_global:
            raise HTTPException(status_code=403, detail="Global admin access required")

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    q = db.query(ActivityLog).filter(ActivityLog.created_at >= cutoff)
    if connection_id is not None:
        q = q.filter(ActivityLog.connection_id == connection_id)

    total = q.count()

    # Breakdown by action
    action_counts = (
        q.with_entities(ActivityLog.action, func.count(ActivityLog.id))
        .group_by(ActivityLog.action)
        .all()
    )

    # Breakdown by status
    status_counts = (
        q.with_entities(ActivityLog.status, func.count(ActivityLog.id))
        .group_by(ActivityLog.status)
        .all()
    )

    # Top users
    top_users = (
        q.with_entities(ActivityLog.username, func.count(ActivityLog.id))
        .group_by(ActivityLog.username)
        .order_by(func.count(ActivityLog.id).desc())
        .limit(10)
        .all()
    )

    return {
        "hours": hours,
        "connection_id": connection_id,
        "total_events": total,
        "by_action": {a: c for a, c in action_counts},
        "by_status": {s: c for s, c in status_counts},
        "top_users": [{"username": u or "(anonymous)", "count": c} for u, c in top_users],
    }


# ── Available action types (for UI filters) ──────────
@router.get("/actions")
async def list_action_types():
    """Return all known action types for filtering in the UI."""
    return {
        "actions": [
            {"key": "auth.login", "label": "Login", "category": "auth"},
            {"key": "auth.login_failed", "label": "Login Failed", "category": "auth"},
            {"key": "auth.signup", "label": "Signup", "category": "auth"},
            {"key": "auth.token_refresh", "label": "Token Refresh", "category": "auth"},
            {"key": "chat.query", "label": "Chat Query", "category": "chat"},
            {"key": "chat.query_failed", "label": "Chat Query Failed", "category": "chat"},
            {"key": "chat.execute", "label": "SQL Execute", "category": "chat"},
            {"key": "chat.execute_failed", "label": "SQL Execute Failed", "category": "chat"},
            {"key": "admin.register_db", "label": "Register DB", "category": "admin"},
            {"key": "admin.list_databases", "label": "List Databases", "category": "admin"},
            {"key": "admin.reindex", "label": "Reindex", "category": "admin"},
            {"key": "admin.view_audit", "label": "View Audit", "category": "admin"},
            {"key": "admin.view_summaries", "label": "View Summaries", "category": "admin"},
            {"key": "admin.update_summary", "label": "Update Summary", "category": "admin"},
            {"key": "admin.refresh_embeddings", "label": "Refresh Embeddings", "category": "admin"},
            {"key": "perm.view_users", "label": "View Users", "category": "perm"},
            {"key": "perm.view_db_users", "label": "View DB Users", "category": "perm"},
            {"key": "perm.update", "label": "Update Permission", "category": "perm"},
            {"key": "perm.denied", "label": "Permission Denied", "category": "perm"},
        ]
    }
