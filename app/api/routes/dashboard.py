"""Dashboard API – CRUD for dashboards & pins, plus live refresh."""

import json
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import Dashboard, DashboardPin, Connection
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboards", tags=["Dashboard"])

MAX_PIN_ROWS = 100  # max result rows returned per pin on refresh


# ═══════════════════════════════════════════════════════
#  Pydantic schemas
# ═══════════════════════════════════════════════════════

class CreateDashboardReq(BaseModel):
    name: str
    description: Optional[str] = None


class UpdateDashboardReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class CreatePinReq(BaseModel):
    connection_id: int
    pin_name: str
    prompt: str
    sql: str
    chart_type: str  # bar | line | pie | scatter | area | table
    chart_config: Optional[str] = None  # JSON string
    position: Optional[int] = None


class UpdatePinReq(BaseModel):
    pin_name: Optional[str] = None
    position: Optional[int] = None


class PinOut(BaseModel):
    id: int
    dashboard_id: int
    connection_id: int
    pin_name: str
    prompt: str
    sql: str
    chart_type: str
    chart_config: Optional[str] = None
    position: int
    last_run_at: Optional[str] = None
    created_at: str


class DashboardOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    pin_count: int = 0
    created_at: str
    updated_at: str


class DashboardDetailOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    pins: List[PinOut] = []
    created_at: str
    updated_at: str


class PinRefreshResult(BaseModel):
    pin_id: int
    pin_name: str
    chart_type: str
    chart_config: Optional[str] = None
    prompt: str
    sql: str
    connection_id: int
    columns: Optional[List[str]] = None
    rows: Optional[List[Dict[str, Any]]] = None
    row_count: int = 0
    execution_time_ms: int = 0
    last_run_at: str
    status: str  # success | error | denied
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════
#  Dashboard CRUD
# ═══════════════════════════════════════════════════════

@router.post("", response_model=DashboardOut, status_code=201)
async def create_dashboard(
    body: CreateDashboardReq,
    user: dict = Depends(get_current_user),
):
    """Create a new dashboard for the current user."""
    db = SessionLocal()
    try:
        dash = Dashboard(
            user_id=int(user["sub"]),
            name=body.name.strip(),
            description=body.description,
        )
        db.add(dash)
        db.commit()
        db.refresh(dash)
        return _dash_out(dash, 0)
    finally:
        db.close()


@router.get("", response_model=List[DashboardOut])
async def list_dashboards(user: dict = Depends(get_current_user)):
    """List all dashboards owned by the current user."""
    db = SessionLocal()
    try:
        dashboards = (
            db.query(Dashboard)
            .filter(Dashboard.user_id == int(user["sub"]))
            .order_by(Dashboard.updated_at.desc())
            .all()
        )
        return [_dash_out(d, len(d.pins)) for d in dashboards]
    finally:
        db.close()


@router.get("/{dashboard_id}", response_model=DashboardDetailOut)
async def get_dashboard(
    dashboard_id: int,
    user: dict = Depends(get_current_user),
):
    """Get a single dashboard with all its pins (metadata only, no data)."""
    db = SessionLocal()
    try:
        dash = _own_dashboard(db, dashboard_id, int(user["sub"]))
        return DashboardDetailOut(
            id=dash.id,
            name=dash.name,
            description=dash.description,
            pins=[_pin_out(p) for p in dash.pins],
            created_at=dash.created_at.isoformat() if dash.created_at else "",
            updated_at=dash.updated_at.isoformat() if dash.updated_at else "",
        )
    finally:
        db.close()


@router.put("/{dashboard_id}", response_model=DashboardOut)
async def update_dashboard(
    dashboard_id: int,
    body: UpdateDashboardReq,
    user: dict = Depends(get_current_user),
):
    """Rename or update a dashboard."""
    db = SessionLocal()
    try:
        dash = _own_dashboard(db, dashboard_id, int(user["sub"]))
        if body.name is not None:
            dash.name = body.name.strip()
        if body.description is not None:
            dash.description = body.description
        db.commit()
        db.refresh(dash)
        return _dash_out(dash, len(dash.pins))
    finally:
        db.close()


@router.delete("/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: int,
    user: dict = Depends(get_current_user),
):
    """Delete a dashboard and all its pins."""
    db = SessionLocal()
    try:
        dash = _own_dashboard(db, dashboard_id, int(user["sub"]))
        db.delete(dash)
        db.commit()
        return {"deleted": True}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════
#  Pin CRUD
# ═══════════════════════════════════════════════════════

@router.post("/{dashboard_id}/pins", response_model=PinOut, status_code=201)
async def add_pin(
    dashboard_id: int,
    body: CreatePinReq,
    user: dict = Depends(get_current_user),
):
    """Pin a query + chart to an existing dashboard."""
    db = SessionLocal()
    try:
        dash = _own_dashboard(db, dashboard_id, int(user["sub"]))

        # Determine position (append to end)
        max_pos = max((p.position for p in dash.pins), default=-1)
        pos = body.position if body.position is not None else max_pos + 1

        pin = DashboardPin(
            dashboard_id=dash.id,
            connection_id=body.connection_id,
            pin_name=body.pin_name.strip(),
            prompt=body.prompt,
            sql=body.sql,
            chart_type=body.chart_type,
            chart_config=body.chart_config,
            position=pos,
        )
        db.add(pin)
        db.commit()
        db.refresh(pin)
        return _pin_out(pin)
    finally:
        db.close()


@router.put("/pins/{pin_id}", response_model=PinOut)
async def update_pin(
    pin_id: int,
    body: UpdatePinReq,
    user: dict = Depends(get_current_user),
):
    """Edit a pin's name or reorder it."""
    db = SessionLocal()
    try:
        pin = _own_pin(db, pin_id, int(user["sub"]))
        if body.pin_name is not None:
            pin.pin_name = body.pin_name.strip()
        if body.position is not None:
            pin.position = body.position
        db.commit()
        db.refresh(pin)
        return _pin_out(pin)
    finally:
        db.close()


@router.delete("/pins/{pin_id}")
async def delete_pin(
    pin_id: int,
    user: dict = Depends(get_current_user),
):
    """Remove a pin from its dashboard."""
    db = SessionLocal()
    try:
        pin = _own_pin(db, pin_id, int(user["sub"]))
        db.delete(pin)
        db.commit()
        return {"deleted": True}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════
#  Refresh – re-run ALL pinned SQLs for live data
# ═══════════════════════════════════════════════════════

@router.post("/{dashboard_id}/refresh", response_model=List[PinRefreshResult])
async def refresh_dashboard(
    dashboard_id: int,
    user: dict = Depends(get_current_user),
):
    """Re-execute every pinned SQL and return fresh results + chart configs."""
    db = SessionLocal()
    try:
        dash = _own_dashboard(db, dashboard_id, int(user["sub"]))
        results: List[PinRefreshResult] = []

        chat_service = ChatService()
        try:
            for pin in dash.pins:
                result = await _run_pin(chat_service, pin, user, db)
                results.append(result)
        finally:
            chat_service.close()

        return results
    finally:
        db.close()


async def _run_pin(
    chat_service: ChatService,
    pin: DashboardPin,
    user: dict,
    db,
) -> PinRefreshResult:
    """Execute a single pin's SQL and return its result."""
    now_iso = datetime.utcnow().isoformat()

    # Permission check
    if not has_db_permission(user, pin.connection_id, "prompt_query"):
        return PinRefreshResult(
            pin_id=pin.id, pin_name=pin.pin_name,
            chart_type=pin.chart_type, chart_config=pin.chart_config,
            prompt=pin.prompt, sql=pin.sql,
            connection_id=pin.connection_id,
            last_run_at=now_iso, status="denied",
            error="Permission 'prompt_query' revoked on this database",
        )

    try:
        raw = await chat_service.execute_query(
            connection_id=pin.connection_id,
            sql=pin.sql,
            timeout=30,
        )

        # Update last_run_at
        pin.last_run_at = datetime.utcnow()
        db.commit()

        if not raw.get("success"):
            return PinRefreshResult(
                pin_id=pin.id, pin_name=pin.pin_name,
                chart_type=pin.chart_type, chart_config=pin.chart_config,
                prompt=pin.prompt, sql=pin.sql,
                connection_id=pin.connection_id,
                execution_time_ms=raw.get("execution_time_ms", 0),
                last_run_at=now_iso, status="error",
                error=raw.get("error", "Unknown query error"),
            )

        # Flatten column names (execute_query returns [{name, type}])
        col_objs = raw.get("columns") or []
        col_names = [c["name"] if isinstance(c, dict) else c for c in col_objs]
        rows = (raw.get("rows") or [])[:MAX_PIN_ROWS]

        return PinRefreshResult(
            pin_id=pin.id, pin_name=pin.pin_name,
            chart_type=pin.chart_type, chart_config=pin.chart_config,
            prompt=pin.prompt, sql=pin.sql,
            connection_id=pin.connection_id,
            columns=col_names, rows=rows,
            row_count=raw.get("row_count", len(rows)),
            execution_time_ms=raw.get("execution_time_ms", 0),
            last_run_at=now_iso, status="success",
        )
    except Exception as exc:
        logger.error(f"Pin {pin.id} refresh error: {exc}", exc_info=True)
        return PinRefreshResult(
            pin_id=pin.id, pin_name=pin.pin_name,
            chart_type=pin.chart_type, chart_config=pin.chart_config,
            prompt=pin.prompt, sql=pin.sql,
            connection_id=pin.connection_id,
            last_run_at=now_iso, status="error",
            error=str(exc),
        )


# ═══════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════

def _own_dashboard(db, dashboard_id: int, user_id: int) -> Dashboard:
    """Fetch a dashboard ensuring the caller owns it."""
    dash = db.query(Dashboard).filter(Dashboard.id == dashboard_id).first()
    if not dash or dash.user_id != user_id:
        raise HTTPException(404, "Dashboard not found")
    return dash


def _own_pin(db, pin_id: int, user_id: int) -> DashboardPin:
    """Fetch a pin ensuring the caller owns the parent dashboard."""
    pin = (
        db.query(DashboardPin)
        .join(Dashboard, DashboardPin.dashboard_id == Dashboard.id)
        .filter(DashboardPin.id == pin_id, Dashboard.user_id == user_id)
        .first()
    )
    if not pin:
        raise HTTPException(404, "Pin not found")
    return pin


def _dash_out(d: Dashboard, pin_count: int) -> DashboardOut:
    return DashboardOut(
        id=d.id,
        name=d.name,
        description=d.description,
        pin_count=pin_count,
        created_at=d.created_at.isoformat() if d.created_at else "",
        updated_at=d.updated_at.isoformat() if d.updated_at else "",
    )


def _pin_out(p: DashboardPin) -> PinOut:
    return PinOut(
        id=p.id,
        dashboard_id=p.dashboard_id,
        connection_id=p.connection_id,
        pin_name=p.pin_name,
        prompt=p.prompt,
        sql=p.sql,
        chart_type=p.chart_type,
        chart_config=p.chart_config,
        position=p.position,
        last_run_at=p.last_run_at.isoformat() if p.last_run_at else None,
        created_at=p.created_at.isoformat() if p.created_at else "",
    )
