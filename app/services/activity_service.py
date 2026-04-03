"""Activity Logging Service — records every significant action to the DB.

Usage
─────
    from app.services.activity_service import log_activity

    # Inside a route handler:
    await log_activity(
        request,                 # FastAPI Request object (for IP / UA)
        user=current_user,       # JWT payload dict  (or None for anon)
        action="chat.query",
        connection_id=3,
        resource_type="connection",
        resource_id=3,
        status="success",
        detail={"prompt": "Show me all artists", "row_count": 347},
        duration_ms=1230,
    )

The function is fire-and-forget — it never raises and never blocks the
response.  Errors are logged to the Python logger.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ActivityLog

logger = logging.getLogger(__name__)


# ── Action constants ──────────────────────────────────
class Actions:
    """Canonical action names – keeps all routes consistent."""

    # Auth
    LOGIN           = "auth.login"
    LOGIN_FAILED    = "auth.login_failed"
    SIGNUP          = "auth.signup"
    TOKEN_REFRESH   = "auth.token_refresh"
    LOGOUT          = "auth.logout"

    # Chat
    CHAT_QUERY          = "chat.query"
    CHAT_QUERY_FAILED   = "chat.query_failed"
    CHAT_EXECUTE        = "chat.execute"
    CHAT_EXECUTE_FAILED = "chat.execute_failed"

    # Admin
    REGISTER_DB         = "admin.register_db"
    LIST_DATABASES      = "admin.list_databases"
    REINDEX             = "admin.reindex"
    VIEW_AUDIT          = "admin.view_audit"
    VIEW_SUMMARIES      = "admin.view_summaries"
    UPDATE_SUMMARY      = "admin.update_summary"
    REFRESH_EMBEDDINGS  = "admin.refresh_embeddings"

    # Permissions
    VIEW_USERS      = "perm.view_users"
    VIEW_DB_USERS   = "perm.view_db_users"
    UPDATE_PERM     = "perm.update"
    PERM_DENIED     = "perm.denied"


# ── Helpers ───────────────────────────────────────────

def _client_ip(request: Optional[Request]) -> Optional[str]:
    """Best-effort client IP from the request."""
    if request is None:
        return None
    # Respect X-Forwarded-For if behind a proxy
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _user_agent(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    ua = request.headers.get("user-agent", "")
    return ua[:512] if ua else None


def _serialize_detail(detail: Any) -> Optional[str]:
    """Safely serialize the detail payload to a JSON string."""
    if detail is None:
        return None
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, default=str, ensure_ascii=False)
    except Exception:
        return str(detail)


# ── Main logging function ─────────────────────────────

async def log_activity(
    request: Optional[Request] = None,
    *,
    user: Optional[dict] = None,
    action: str,
    connection_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    status: str = "success",
    detail: Any = None,
    duration_ms: Optional[int] = None,
    db: Optional[Session] = None,
):
    """Write one activity log row.  Never raises."""
    own_session = False
    try:
        if db is None:
            db = SessionLocal()
            own_session = True

        entry = ActivityLog(
            user_id=int(user["sub"]) if user and "sub" in user else None,
            username=user.get("username") if user else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            connection_id=connection_id,
            status=status,
            detail=_serialize_detail(detail),
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            duration_ms=duration_ms,
            created_at=datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
    except Exception as exc:
        logger.warning(f"Activity log write failed ({action}): {exc}")
        try:
            if db:
                db.rollback()
        except Exception:
            pass
    finally:
        if own_session and db:
            try:
                db.close()
            except Exception:
                pass
