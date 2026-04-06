"""Scheduled Queries API – create, manage, and run scheduled queries with alerts."""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query as QParam
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import ScheduledQuery, SavedQuery
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scheduled", tags=["Scheduled Queries"])

CRON_PRESETS = {
    "every_hour": "0 * * * *",
    "daily_9am": "0 9 * * *",
    "daily_6pm": "0 18 * * *",
    "weekly_monday": "0 9 * * 1",
    "weekly_friday": "0 17 * * 5",
    "monthly_first": "0 9 1 * *",
}


class CreateScheduleReq(BaseModel):
    saved_query_id: int
    name: str
    cron_expression: Optional[str] = None
    cron_preset: Optional[str] = None
    alert_condition: Optional[Dict[str, Any]] = None
    alert_email: Optional[str] = None


class UpdateScheduleReq(BaseModel):
    name: Optional[str] = None
    cron_expression: Optional[str] = None
    is_active: Optional[bool] = None
    alert_condition: Optional[Dict[str, Any]] = None
    alert_email: Optional[str] = None


class ScheduleOut(BaseModel):
    id: int
    saved_query_id: int
    connection_id: int
    name: str
    cron_expression: str
    is_active: bool
    alert_condition: Optional[Dict[str, Any]] = None
    alert_email: Optional[str] = None
    last_run_at: Optional[str] = None
    last_run_status: Optional[str] = None
    last_run_row_count: Optional[int] = None
    next_run_at: Optional[str] = None
    run_count: int = 0
    created_at: str


class RunScheduleResult(BaseModel):
    success: bool
    row_count: int = 0
    alert_triggered: bool = False
    alert_message: Optional[str] = None
    execution_time_ms: int = 0
    error: Optional[str] = None


@router.post("", response_model=ScheduleOut, status_code=201)
async def create_schedule(body: CreateScheduleReq, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        sq = db.query(SavedQuery).filter(
            SavedQuery.id == body.saved_query_id,
            SavedQuery.user_id == int(user["sub"])
        ).first()
        if not sq:
            raise HTTPException(404, "Saved query not found")
        
        cron = body.cron_expression or CRON_PRESETS.get(body.cron_preset or "", "0 9 * * *")
        
        sched = ScheduledQuery(
            user_id=int(user["sub"]),
            saved_query_id=body.saved_query_id,
            connection_id=sq.connection_id,
            name=body.name.strip(),
            cron_expression=cron,
            alert_condition=json.dumps(body.alert_condition) if body.alert_condition else None,
            alert_email=body.alert_email,
        )
        db.add(sched)
        db.commit()
        db.refresh(sched)
        return _sched_out(sched)
    finally:
        db.close()


@router.get("", response_model=List[ScheduleOut])
async def list_schedules(
    connection_id: Optional[int] = QParam(None),
    active_only: bool = QParam(False),
    user: dict = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        q = db.query(ScheduledQuery).filter(ScheduledQuery.user_id == int(user["sub"]))
        if connection_id is not None:
            q = q.filter(ScheduledQuery.connection_id == connection_id)
        if active_only:
            q = q.filter(ScheduledQuery.is_active == True)
        scheds = q.order_by(ScheduledQuery.created_at.desc()).all()
        return [_sched_out(s) for s in scheds]
    finally:
        db.close()


@router.put("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(schedule_id: int, body: UpdateScheduleReq, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        sched = db.query(ScheduledQuery).filter(
            ScheduledQuery.id == schedule_id,
            ScheduledQuery.user_id == int(user["sub"])
        ).first()
        if not sched:
            raise HTTPException(404, "Schedule not found")
        if body.name is not None:
            sched.name = body.name.strip()
        if body.cron_expression is not None:
            sched.cron_expression = body.cron_expression
        if body.is_active is not None:
            sched.is_active = body.is_active
        if body.alert_condition is not None:
            sched.alert_condition = json.dumps(body.alert_condition)
        if body.alert_email is not None:
            sched.alert_email = body.alert_email
        db.commit()
        db.refresh(sched)
        return _sched_out(sched)
    finally:
        db.close()


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        sched = db.query(ScheduledQuery).filter(
            ScheduledQuery.id == schedule_id,
            ScheduledQuery.user_id == int(user["sub"])
        ).first()
        if not sched:
            raise HTTPException(404, "Schedule not found")
        db.delete(sched)
        db.commit()
        return {"deleted": True}
    finally:
        db.close()


@router.post("/{schedule_id}/run", response_model=RunScheduleResult)
async def run_schedule_now(schedule_id: int, user: dict = Depends(get_current_user)):
    """Manually trigger a scheduled query execution."""
    db = SessionLocal()
    try:
        sched = db.query(ScheduledQuery).filter(
            ScheduledQuery.id == schedule_id,
            ScheduledQuery.user_id == int(user["sub"])
        ).first()
        if not sched:
            raise HTTPException(404, "Schedule not found")
        
        if not has_db_permission(user, sched.connection_id, "prompt_query"):
            raise HTTPException(403, "Permission required")
        
        sq = db.query(SavedQuery).filter(SavedQuery.id == sched.saved_query_id).first()
        if not sq:
            raise HTTPException(404, "Linked saved query not found")
        
        chat_service = ChatService()
        try:
            raw = await chat_service.execute_query(connection_id=sched.connection_id, sql=sq.sql, timeout=30)
        finally:
            chat_service.close()
        
        success = raw.get("success", False)
        row_count = len(raw.get("rows", []))
        
        sched.last_run_at = datetime.utcnow()
        sched.last_run_status = "success" if success else "failed"
        sched.last_run_row_count = row_count
        sched.run_count = (sched.run_count or 0) + 1
        
        alert_triggered = False
        alert_message = None
        if success and sched.alert_condition:
            alert_triggered, alert_message = _check_alert(
                json.loads(sched.alert_condition), raw.get("rows", [])
            )
        
        sched.last_run_result = json.dumps({"alert_triggered": alert_triggered, "alert_message": alert_message, "row_count": row_count})
        db.commit()
        
        return RunScheduleResult(
            success=success,
            row_count=row_count,
            alert_triggered=alert_triggered,
            alert_message=alert_message,
            execution_time_ms=raw.get("execution_time_ms", 0),
            error=raw.get("error"),
        )
    finally:
        db.close()


@router.get("/presets")
async def get_cron_presets(user: dict = Depends(get_current_user)):
    return {"presets": CRON_PRESETS}


def _check_alert(condition: dict, rows: list) -> tuple:
    """Check if alert condition is triggered. Returns (triggered, message)."""
    try:
        ctype = condition.get("type", "row_count")
        if ctype == "row_count":
            op = condition.get("op", ">")
            val = condition.get("value", 0)
            actual = len(rows)
            triggered = _compare(actual, op, val)
            return triggered, f"Row count {actual} {op} {val}" if triggered else None
        
        if ctype == "threshold" and rows:
            col = condition.get("column", "")
            op = condition.get("op", ">")
            val = condition.get("value", 0)
            for row in rows:
                cell = row.get(col)
                if cell is not None:
                    try:
                        if _compare(float(cell), op, float(val)):
                            return True, f"Column '{col}' value {cell} {op} {val}"
                    except (ValueError, TypeError):
                        pass
        
        if ctype == "no_results":
            return len(rows) == 0, "Query returned no results" if len(rows) == 0 else None
    except Exception as e:
        logger.warning(f"Alert check failed: {e}")
    return False, None


def _compare(a, op, b):
    ops = {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b, "==": a == b, "!=": a != b}
    return ops.get(op, False)


def _sched_out(s: ScheduledQuery) -> ScheduleOut:
    return ScheduleOut(
        id=s.id,
        saved_query_id=s.saved_query_id,
        connection_id=s.connection_id,
        name=s.name,
        cron_expression=s.cron_expression,
        is_active=s.is_active if s.is_active is not None else True,
        alert_condition=json.loads(s.alert_condition) if s.alert_condition else None,
        alert_email=s.alert_email,
        last_run_at=s.last_run_at.isoformat() if s.last_run_at else None,
        last_run_status=s.last_run_status,
        last_run_row_count=s.last_run_row_count,
        next_run_at=s.next_run_at.isoformat() if s.next_run_at else None,
        run_count=s.run_count or 0,
        created_at=s.created_at.isoformat() if s.created_at else "",
    )
