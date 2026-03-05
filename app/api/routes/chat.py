"""Chat API endpoints"""

import json
import time
from decimal import Decimal
from datetime import datetime, date
from fastapi import APIRouter, HTTPException, Depends, Request, Query as QParam
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

from app.services.chat_service import ChatService
from app.services.activity_service import log_activity, Actions
from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import ChatHistory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

MAX_HISTORY_ROWS = 50  # max result rows persisted per message


def _safe_json(obj):
    """JSON encoder that handles Decimal, datetime, date, bytes, etc."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


# ── Helper: persist a chat exchange to chat_history ───
def _save_chat_history(user: dict, connection_id: int, prompt: str, result: dict):
    """Fire-and-forget save of a chat exchange (never raises)."""
    try:
        db = SessionLocal()
        try:
            cols = result.get("columns") or []
            rows = result.get("rows") or []
            sel_tables = result.get("selected_tables") or []

            entry = ChatHistory(
                user_id=int(user["sub"]),
                connection_id=connection_id,
                prompt=prompt,
                answer=result.get("answer"),
                sql=result.get("sql"),
                columns=json.dumps(cols, default=_safe_json) if cols else None,
                rows=json.dumps(rows[:MAX_HISTORY_ROWS], default=_safe_json) if rows else None,
                row_count=result.get("row_count"),
                execution_time_ms=result.get("execution_time_ms"),
                selected_tables=json.dumps(sel_tables, default=_safe_json) if sel_tables else None,
                status=result.get("status", "error"),
                error_message=result.get("error"),
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        import traceback
        logger.error(f"Failed to save chat history: {exc}\n{traceback.format_exc()}")
        print(f"[HISTORY-SAVE-ERROR] {exc}", flush=True)


# ══════════════════════════════════════════════════════
#  GET /api/chat/history  –  user's own chat history
# ══════════════════════════════════════════════════════

class ChatHistoryItem(BaseModel):
    id: int
    connection_id: int
    prompt: str
    answer: Optional[str] = None
    sql: Optional[str] = None
    columns: Optional[List[str]] = None
    rows: Optional[List[Dict[str, Any]]] = None
    row_count: Optional[int] = None
    execution_time_ms: Optional[int] = None
    selected_tables: Optional[List[str]] = None
    status: str
    error_message: Optional[str] = None
    created_at: str


@router.get("/history", response_model=List[ChatHistoryItem])
async def get_chat_history(
    connection_id: int = QParam(..., description="Database connection ID"),
    limit: int = QParam(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    """Return the current user's chat history for a specific database."""
    db = SessionLocal()
    try:
        entries = (
            db.query(ChatHistory)
            .filter(ChatHistory.user_id == int(user["sub"]),
                    ChatHistory.connection_id == connection_id)
            .order_by(ChatHistory.created_at.asc())
            .limit(limit)
            .all()
        )
        items = []
        for e in entries:
            items.append(ChatHistoryItem(
                id=e.id,
                connection_id=e.connection_id,
                prompt=e.prompt,
                answer=e.answer,
                sql=e.sql,
                columns=json.loads(e.columns) if e.columns else None,
                rows=json.loads(e.rows) if e.rows else None,
                row_count=e.row_count,
                execution_time_ms=e.execution_time_ms,
                selected_tables=json.loads(e.selected_tables) if e.selected_tables else None,
                status=e.status,
                error_message=e.error_message,
                created_at=e.created_at.isoformat() if e.created_at else "",
            ))
        return items
    finally:
        db.close()


@router.delete("/history")
async def clear_chat_history(
    connection_id: Optional[int] = QParam(None),
    user: dict = Depends(get_current_user),
):
    """Clear the current user's chat history (optionally scoped to a DB)."""
    db = SessionLocal()
    try:
        q = db.query(ChatHistory).filter(ChatHistory.user_id == int(user["sub"]))
        if connection_id is not None:
            q = q.filter(ChatHistory.connection_id == connection_id)
        deleted = q.delete(synchronize_session=False)
        db.commit()
        return {"deleted": deleted}
    finally:
        db.close()


class ChatRequest(BaseModel):
    """Chat request model"""
    connection_id: int
    prompt: str
    top_k_tables: int = 5  # Number of relevant tables to use


class ChatResponse(BaseModel):
    """Chat response model"""
    status: str
    answer: Optional[str] = None
    sql: Optional[str] = None
    rows: Optional[List[Dict[str, Any]]] = None
    columns: Optional[List[str]] = None
    row_count: Optional[int] = None
    execution_time_ms: int
    query_time_ms: Optional[int] = None
    error: Optional[str] = None
    # Debug fields
    selected_tables: Optional[List[str]] = None
    schema_context: Optional[str] = None


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    req: Request,
    user: dict = Depends(get_current_user),
):
    if not has_db_permission(user, request.connection_id, "prompt_query"):
        await log_activity(req, user=user, action=Actions.PERM_DENIED,
                           connection_id=request.connection_id, status="denied",
                           detail={"attempted": "prompt_query", "prompt": request.prompt[:120]})
        raise HTTPException(status_code=403, detail="Permission 'prompt_query' required on this database")
    """
    Chat endpoint - Process natural language query
    """
    t0 = time.time()
    try:
        logger.info(f"Chat request: connection={request.connection_id}, prompt='{request.prompt[:50]}'")
        chat_service = ChatService()
        
        try:
            result = await chat_service.process_query(
                connection_id=request.connection_id,
                user_prompt=request.prompt,
                top_k_tables=request.top_k_tables
            )
            dur = int((time.time() - t0) * 1000)
            await log_activity(req, user=user, action=Actions.CHAT_QUERY,
                               connection_id=request.connection_id,
                               resource_type="connection", resource_id=request.connection_id,
                               detail={"prompt": request.prompt[:200],
                                       "row_count": result.get("row_count"),
                                       "sql": (result.get("sql") or "")[:300],
                                       "status": result.get("status")},
                               duration_ms=dur)
            # Persist chat exchange for per-user history
            _save_chat_history(user, request.connection_id, request.prompt, result)
            return ChatResponse(
                status=result.get("status", "error"),
                answer=result.get("answer"),
                sql=result.get("sql"),
                rows=result.get("rows"),
                columns=result.get("columns"),
                row_count=result.get("row_count"),
                execution_time_ms=result.get("execution_time_ms", 0),
                query_time_ms=result.get("query_time_ms"),
                error=result.get("error"),
                selected_tables=result.get("selected_tables"),
                schema_context=result.get("schema_context")
            )
        finally:
            chat_service.close()
    
    except HTTPException:
        raise
    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        await log_activity(req, user=user, action=Actions.CHAT_QUERY_FAILED,
                           connection_id=request.connection_id, status="failed",
                           detail={"prompt": request.prompt[:200], "error": str(e)[:300]},
                           duration_ms=dur)
        logger.error(f"Chat endpoint error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class ExecuteRequest(BaseModel):
    """Execute query request model"""
    connection_id: int
    sql: str


class ExecuteResponse(BaseModel):
    """Execute query response model"""
    success: bool
    columns: List[Dict[str, str]] = []
    data: List[Dict[str, Any]] = []
    row_count: int = 0
    execution_time_ms: int = 0
    error: Optional[str] = None


@router.post("/execute", response_model=ExecuteResponse)
async def execute_query(
    request: ExecuteRequest,
    req: Request,
    user: dict = Depends(get_current_user),
):
    if not has_db_permission(user, request.connection_id, "prompt_query"):
        await log_activity(req, user=user, action=Actions.PERM_DENIED,
                           connection_id=request.connection_id, status="denied",
                           detail={"attempted": "execute", "sql": request.sql[:200]})
        raise HTTPException(status_code=403, detail="Permission 'prompt_query' required on this database")
    """
    Execute a SQL query on the connected database
    """
    t0 = time.time()
    try:
        logger.info(f"Execute request: connection={request.connection_id}, sql='{request.sql[:50]}'")
        chat_service = ChatService()
        
        try:
            result = await chat_service.execute_query(
                connection_id=request.connection_id,
                sql=request.sql
            )
            dur = int((time.time() - t0) * 1000)
            await log_activity(req, user=user, action=Actions.CHAT_EXECUTE,
                               connection_id=request.connection_id,
                               resource_type="connection", resource_id=request.connection_id,
                               detail={"sql": request.sql[:300], "row_count": result.get("row_count")},
                               duration_ms=dur)
            return ExecuteResponse(
                success=result.get("success", False),
                columns=result.get("columns", []),
                data=result.get("rows", []),
                row_count=result.get("row_count", 0),
                execution_time_ms=result.get("execution_time_ms", 0),
                error=result.get("error")
            )
        finally:
            chat_service.close()
    
    except HTTPException:
        raise
    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        await log_activity(req, user=user, action=Actions.CHAT_EXECUTE_FAILED,
                           connection_id=request.connection_id, status="failed",
                           detail={"sql": request.sql[:200], "error": str(e)[:300]},
                           duration_ms=dur)
        logger.error(f"Execute endpoint error: {str(e)}", exc_info=True)
        return ExecuteResponse(
            success=False,
            error=str(e)
        )


# ══════════════════════════════════════════════════════
#  POST /api/chat/explain  –  Explain a SQL query
# ══════════════════════════════════════════════════════

class ExplainRequest(BaseModel):
    connection_id: int
    sql: str
    prompt: str
    schema_context: Optional[str] = None
    columns: Optional[List[str]] = None
    row_count: Optional[int] = None


class ExplainResponse(BaseModel):
    explanation: str
    execution_time_ms: int


@router.post("/explain", response_model=ExplainResponse)
async def explain_query(
    request: ExplainRequest,
    req: Request,
    user: dict = Depends(get_current_user),
):
    """Explain a SQL query in plain English for non-technical users."""
    if not has_db_permission(user, request.connection_id, "prompt_query"):
        raise HTTPException(status_code=403, detail="Permission 'prompt_query' required on this database")

    t0 = time.time()
    try:
        chat_service = ChatService()
        try:
            schema_context = request.schema_context
            if not schema_context:
                tables = chat_service._extract_tables_from_sql(request.sql)
                schema_context = chat_service.metadata.get_column_schema(
                    request.connection_id, tables
                ) or "Schema not available"

            explanation = await chat_service.ollama.explain_sql(
                sql=request.sql,
                user_prompt=request.prompt,
                schema_context=schema_context,
                columns=request.columns,
                row_count=request.row_count,
            )
            dur = int((time.time() - t0) * 1000)
            await log_activity(
                req, user=user, action="chat.explain",
                connection_id=request.connection_id,
                detail={"sql": request.sql[:300], "prompt": request.prompt[:200]},
                duration_ms=dur,
            )
            return ExplainResponse(explanation=explanation, execution_time_ms=dur)
        finally:
            chat_service.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Explain endpoint error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
