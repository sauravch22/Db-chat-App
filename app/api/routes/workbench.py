"""Multi-Query Workbench API – execute multiple queries and compare results."""

import time
import json
from decimal import Decimal
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workbench", tags=["Workbench"])


def _safe_json(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


class WorkbenchQuery(BaseModel):
    id: str
    connection_id: int
    sql: str
    label: Optional[str] = None


class WorkbenchRequest(BaseModel):
    queries: List[WorkbenchQuery]


class QueryResult(BaseModel):
    id: str
    label: Optional[str] = None
    success: bool
    columns: List[str] = []
    rows: List[Dict[str, Any]] = []
    row_count: int = 0
    execution_time_ms: int = 0
    error: Optional[str] = None


class WorkbenchResponse(BaseModel):
    results: List[QueryResult]
    total_time_ms: int


class DiffRequest(BaseModel):
    connection_id: int
    sql_a: str
    sql_b: str
    key_column: Optional[str] = None


class DiffResponse(BaseModel):
    only_in_a: int = 0
    only_in_b: int = 0
    in_both: int = 0
    differences: List[Dict[str, Any]] = []
    execution_time_ms: int = 0


@router.post("/execute", response_model=WorkbenchResponse)
async def execute_workbench(
    request: WorkbenchRequest,
    user: dict = Depends(get_current_user),
):
    """Execute multiple queries and return all results."""
    if not request.queries:
        raise HTTPException(400, "At least one query required")
    if len(request.queries) > 10:
        raise HTTPException(400, "Maximum 10 queries per batch")
    
    for q in request.queries:
        if not has_db_permission(user, q.connection_id, "prompt_query"):
            raise HTTPException(403, f"Permission required for connection {q.connection_id}")
    
    t0 = time.time()
    results = []
    
    for q in request.queries:
        qt0 = time.time()
        try:
            chat_service = ChatService()
            try:
                raw = await chat_service.execute_query(
                    connection_id=q.connection_id,
                    sql=q.sql,
                    timeout=30,
                )
            finally:
                chat_service.close()
            
            qdur = int((time.time() - qt0) * 1000)
            col_objs = raw.get("columns") or []
            col_names = [c["name"] if isinstance(c, dict) else c for c in col_objs]
            
            rows = raw.get("rows") or []
            clean_rows = json.loads(json.dumps(rows[:500], default=_safe_json))
            
            results.append(QueryResult(
                id=q.id,
                label=q.label,
                success=raw.get("success", False),
                columns=col_names,
                rows=clean_rows,
                row_count=len(rows),
                execution_time_ms=qdur,
                error=raw.get("error"),
            ))
        except Exception as e:
            qdur = int((time.time() - qt0) * 1000)
            results.append(QueryResult(
                id=q.id,
                label=q.label,
                success=False,
                execution_time_ms=qdur,
                error=str(e),
            ))
    
    total = int((time.time() - t0) * 1000)
    return WorkbenchResponse(results=results, total_time_ms=total)


@router.post("/diff", response_model=DiffResponse)
async def diff_queries(request: DiffRequest, user: dict = Depends(get_current_user)):
    """Compare results of two queries and show differences."""
    if not has_db_permission(user, request.connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required")
    
    t0 = time.time()
    chat_service = ChatService()
    try:
        res_a = await chat_service.execute_query(connection_id=request.connection_id, sql=request.sql_a, timeout=30)
        res_b = await chat_service.execute_query(connection_id=request.connection_id, sql=request.sql_b, timeout=30)
    finally:
        chat_service.close()
    
    rows_a = res_a.get("rows") or []
    rows_b = res_b.get("rows") or []
    
    key_col = request.key_column
    if not key_col and rows_a:
        key_col = list(rows_a[0].keys())[0] if rows_a[0] else None
    
    if not key_col:
        dur = int((time.time() - t0) * 1000)
        return DiffResponse(only_in_a=len(rows_a), only_in_b=len(rows_b), execution_time_ms=dur)
    
    set_a = {str(r.get(key_col, "")): r for r in rows_a}
    set_b = {str(r.get(key_col, "")): r for r in rows_b}
    
    keys_a = set(set_a.keys())
    keys_b = set(set_b.keys())
    
    only_a = keys_a - keys_b
    only_b = keys_b - keys_a
    both = keys_a & keys_b
    
    diffs = []
    for k in list(both)[:50]:
        ra, rb = set_a[k], set_b[k]
        row_diffs = {}
        for col in ra:
            va, vb = str(ra.get(col, "")), str(rb.get(col, ""))
            if va != vb:
                row_diffs[col] = {"a": va, "b": vb}
        if row_diffs:
            diffs.append({"key": k, "changes": row_diffs})
    
    dur = int((time.time() - t0) * 1000)
    return DiffResponse(
        only_in_a=len(only_a),
        only_in_b=len(only_b),
        in_both=len(both),
        differences=diffs[:50],
        execution_time_ms=dur,
    )
