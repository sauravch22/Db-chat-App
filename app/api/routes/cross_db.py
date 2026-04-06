"""Cross-Database Query API — execute the same query against multiple connections
and merge/compare results."""

import asyncio
import json
import logging
import time
from decimal import Decimal
from datetime import datetime, date
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.api.deps import get_current_user, has_db_permission
from app.services.chat_service import ChatService
from app.database import SessionLocal
from app.models import Connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crossdb", tags=["Cross-Database"])


def _safe(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


class CrossDbRequest(BaseModel):
    connection_ids: List[int]
    sql: str
    merge_mode: str = "union"  # union | side_by_side


class CrossDbNLRequest(BaseModel):
    connection_ids: List[int]
    prompt: str


@router.get("/connections")
async def list_connections(user: dict = Depends(get_current_user)):
    """Return all active connections the user has access to."""
    db = SessionLocal()
    try:
        conns = db.query(Connection).filter(Connection.is_active == True).all()
        result = []
        for c in conns:
            if has_db_permission(user, c.id, "prompt_query"):
                result.append({
                    "id": c.id, "name": c.name,
                    "database_type": c.database_type,
                    "database": c.database,
                    "host": c.host,
                })
        return result
    finally:
        db.close()


@router.post("/query")
async def cross_db_query(
    request: CrossDbRequest,
    user: dict = Depends(get_current_user),
):
    """Execute the same SQL against multiple connections and merge results."""
    if len(request.connection_ids) < 1:
        raise HTTPException(400, "Provide at least one connection_id")
    if len(request.connection_ids) > 5:
        raise HTTPException(400, "Maximum 5 connections per cross-db query")

    for cid in request.connection_ids:
        if not has_db_permission(user, cid, "prompt_query"):
            raise HTTPException(403, f"No prompt_query permission on connection {cid}")

    async def run_one(cid: int):
        svc = ChatService()
        try:
            result = await svc.execute_query(connection_id=cid, sql=request.sql)
            return {"connection_id": cid, **result}
        except Exception as e:
            return {"connection_id": cid, "success": False, "error": str(e),
                    "rows": [], "columns": []}
        finally:
            svc.close()

    t0 = time.time()
    results = await asyncio.gather(*[run_one(cid) for cid in request.connection_ids])
    total_ms = int((time.time() - t0) * 1000)

    db = SessionLocal()
    try:
        conn_names = {}
        for c in db.query(Connection).filter(Connection.id.in_(request.connection_ids)).all():
            conn_names[c.id] = c.name
    finally:
        db.close()

    for r in results:
        r["connection_name"] = conn_names.get(r["connection_id"], f"DB#{r['connection_id']}")

    if request.merge_mode == "union":
        all_cols = set()
        for r in results:
            all_cols.update(r.get("columns") or [c["name"] for c in r.get("columns", [])])
        all_cols_list = sorted(all_cols) if all_cols else []
        merged_rows = []
        for r in results:
            row_cols = r.get("columns", [])
            if isinstance(row_cols, list) and row_cols and isinstance(row_cols[0], dict):
                row_cols = [c["name"] for c in row_cols]
            for row in r.get("rows", []):
                new_row = {"__source__": r["connection_name"]}
                for c in all_cols_list:
                    new_row[c] = row.get(c)
                merged_rows.append(new_row)
        return {
            "merge_mode": "union",
            "columns": ["__source__"] + all_cols_list,
            "rows": merged_rows,
            "total_rows": len(merged_rows),
            "total_time_ms": total_ms,
            "per_connection": [
                {"connection_id": r["connection_id"], "name": r["connection_name"],
                 "row_count": r.get("row_count", len(r.get("rows", []))),
                 "success": r.get("success", True),
                 "error": r.get("error")}
                for r in results
            ],
        }
    else:
        return {
            "merge_mode": "side_by_side",
            "results": [
                {
                    "connection_id": r["connection_id"],
                    "connection_name": r["connection_name"],
                    "columns": r.get("columns", []),
                    "rows": r.get("rows", []),
                    "row_count": r.get("row_count", len(r.get("rows", []))),
                    "success": r.get("success", True),
                    "error": r.get("error"),
                }
                for r in results
            ],
            "total_time_ms": total_ms,
        }


@router.get("/db-types")
async def supported_db_types(user: dict = Depends(get_current_user)):
    """Return list of supported database types for the admin UI."""
    from app.services.schema_service import SchemaExtractor
    return SchemaExtractor.SUPPORTED_DB_TYPES
