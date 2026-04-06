"""Write-Back API – controlled data modifications with approval workflow."""

import json
import re
import time
from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query as QParam
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission, has_any_onboard
from app.database import SessionLocal
from app.models import WriteBackRequest, Connection
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/writeback", tags=["Write-Back"])


class WriteBackReq(BaseModel):
    connection_id: int
    sql: str
    reason: Optional[str] = None


class WriteBackOut(BaseModel):
    id: int
    connection_id: int
    sql: str
    operation_type: str
    target_table: str
    affected_rows_estimate: Optional[int] = None
    status: str
    approved_by: Optional[int] = None
    approved_at: Optional[str] = None
    executed_at: Optional[str] = None
    rows_affected: Optional[int] = None
    reason: Optional[str] = None
    username: Optional[str] = None
    created_at: str


@router.post("", response_model=WriteBackOut, status_code=201)
async def create_writeback(body: WriteBackReq, user: dict = Depends(get_current_user)):
    """Submit a write-back request for approval."""
    if not has_db_permission(user, body.connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required")
    
    sql_upper = body.sql.strip().upper()
    op_type = "UNKNOWN"
    target_table = "unknown"
    
    if sql_upper.startswith("INSERT"):
        op_type = "INSERT"
        m = re.search(r'INSERT\s+INTO\s+(\S+)', body.sql, re.IGNORECASE)
        if m:
            target_table = m.group(1).strip('"').strip("'")
    elif sql_upper.startswith("UPDATE"):
        op_type = "UPDATE"
        m = re.search(r'UPDATE\s+(\S+)', body.sql, re.IGNORECASE)
        if m:
            target_table = m.group(1).strip('"').strip("'")
    elif sql_upper.startswith("DELETE"):
        op_type = "DELETE"
        m = re.search(r'DELETE\s+FROM\s+(\S+)', body.sql, re.IGNORECASE)
        if m:
            target_table = m.group(1).strip('"').strip("'")
    else:
        raise HTTPException(400, "Only INSERT, UPDATE, DELETE statements are supported for write-back")
    
    db = SessionLocal()
    try:
        wb = WriteBackRequest(
            user_id=int(user["sub"]),
            connection_id=body.connection_id,
            sql=body.sql.strip(),
            operation_type=op_type,
            target_table=target_table,
            reason=body.reason,
            status="pending",
        )
        db.add(wb)
        db.commit()
        db.refresh(wb)
        return _wb_out(wb, user.get("username", ""))
    finally:
        db.close()


@router.get("", response_model=List[WriteBackOut])
async def list_writebacks(
    connection_id: Optional[int] = QParam(None),
    status: Optional[str] = QParam(None),
    user: dict = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        is_admin = has_any_onboard(user)
        q = db.query(WriteBackRequest)
        if not is_admin:
            q = q.filter(WriteBackRequest.user_id == int(user["sub"]))
        if connection_id is not None:
            q = q.filter(WriteBackRequest.connection_id == connection_id)
        if status:
            q = q.filter(WriteBackRequest.status == status)
        wbs = q.order_by(WriteBackRequest.created_at.desc()).limit(100).all()
        return [_wb_out(wb) for wb in wbs]
    finally:
        db.close()


@router.post("/{wb_id}/approve", response_model=WriteBackOut)
async def approve_writeback(wb_id: int, user: dict = Depends(get_current_user)):
    """Approve a pending write-back request (admin only)."""
    db = SessionLocal()
    try:
        wb = db.query(WriteBackRequest).filter(WriteBackRequest.id == wb_id).first()
        if not wb:
            raise HTTPException(404, "Write-back request not found")
        if not has_db_permission(user, wb.connection_id, "db_reindex"):
            raise HTTPException(403, "Admin permission required to approve")
        if wb.status != "pending":
            raise HTTPException(400, f"Cannot approve request in '{wb.status}' status")
        
        wb.status = "approved"
        wb.approved_by = int(user["sub"])
        wb.approved_at = datetime.utcnow()
        db.commit()
        db.refresh(wb)
        return _wb_out(wb)
    finally:
        db.close()


@router.post("/{wb_id}/reject", response_model=WriteBackOut)
async def reject_writeback(wb_id: int, user: dict = Depends(get_current_user)):
    """Reject a pending write-back request."""
    db = SessionLocal()
    try:
        wb = db.query(WriteBackRequest).filter(WriteBackRequest.id == wb_id).first()
        if not wb:
            raise HTTPException(404, "Write-back request not found")
        if not has_db_permission(user, wb.connection_id, "db_reindex"):
            raise HTTPException(403, "Admin permission required to reject")
        if wb.status != "pending":
            raise HTTPException(400, f"Cannot reject request in '{wb.status}' status")
        
        wb.status = "rejected"
        db.commit()
        db.refresh(wb)
        return _wb_out(wb)
    finally:
        db.close()


@router.post("/{wb_id}/execute", response_model=WriteBackOut)
async def execute_writeback(wb_id: int, user: dict = Depends(get_current_user)):
    """Execute an approved write-back request."""
    db = SessionLocal()
    try:
        wb = db.query(WriteBackRequest).filter(WriteBackRequest.id == wb_id).first()
        if not wb:
            raise HTTPException(404, "Write-back request not found")
        if not has_db_permission(user, wb.connection_id, "db_reindex"):
            raise HTTPException(403, "Admin permission required to execute")
        if wb.status != "approved":
            raise HTTPException(400, "Only approved requests can be executed")
        
        chat_service = ChatService()
        try:
            result = await chat_service.execute_query(
                connection_id=wb.connection_id,
                sql=wb.sql,
                timeout=30,
            )
        finally:
            chat_service.close()
        
        if result.get("success"):
            wb.status = "executed"
            wb.executed_at = datetime.utcnow()
            wb.rows_affected = result.get("row_count", 0)
            wb.execution_result = json.dumps({"success": True, "rows_affected": wb.rows_affected})
        else:
            wb.status = "failed"
            wb.execution_result = json.dumps({"success": False, "error": result.get("error", "")})
        
        db.commit()
        db.refresh(wb)
        return _wb_out(wb)
    finally:
        db.close()


def _wb_out(wb: WriteBackRequest, username: str = None) -> WriteBackOut:
    return WriteBackOut(
        id=wb.id,
        connection_id=wb.connection_id,
        sql=wb.sql,
        operation_type=wb.operation_type,
        target_table=wb.target_table,
        affected_rows_estimate=wb.affected_rows_estimate,
        status=wb.status,
        approved_by=wb.approved_by,
        approved_at=wb.approved_at.isoformat() if wb.approved_at else None,
        executed_at=wb.executed_at.isoformat() if wb.executed_at else None,
        rows_affected=wb.rows_affected,
        reason=wb.reason,
        username=username,
        created_at=wb.created_at.isoformat() if wb.created_at else "",
    )
