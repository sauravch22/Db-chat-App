"""Saved Queries API – bookmark, list, run, and manage saved SQL queries."""

import time
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query as QParam
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import SavedQuery
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/saved-queries", tags=["Saved Queries"])


class SaveQueryReq(BaseModel):
    connection_id: int
    name: str
    sql: str
    prompt: Optional[str] = None
    description: Optional[str] = None
    folder: Optional[str] = None
    is_favorite: bool = False


class UpdateSavedQueryReq(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    folder: Optional[str] = None
    is_favorite: Optional[bool] = None


class SavedQueryOut(BaseModel):
    id: int
    connection_id: int
    name: str
    sql: str
    prompt: Optional[str] = None
    description: Optional[str] = None
    folder: Optional[str] = None
    is_favorite: bool = False
    run_count: int = 0
    last_run_at: Optional[str] = None
    created_at: str
    updated_at: str


class RunResult(BaseModel):
    success: bool
    columns: List[str] = []
    rows: List[Dict[str, Any]] = []
    row_count: int = 0
    total_count: Optional[int] = None
    execution_time_ms: int = 0
    error: Optional[str] = None


@router.post("", response_model=SavedQueryOut, status_code=201)
async def save_query(body: SaveQueryReq, user: dict = Depends(get_current_user)):
    """Save a query for later re-use."""
    if not has_db_permission(user, body.connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required on this database")
    db = SessionLocal()
    try:
        sq = SavedQuery(
            user_id=int(user["sub"]),
            connection_id=body.connection_id,
            name=body.name.strip(),
            sql=body.sql.strip(),
            prompt=body.prompt,
            description=body.description,
            folder=body.folder,
            is_favorite=body.is_favorite,
        )
        db.add(sq)
        db.commit()
        db.refresh(sq)
        return _sq_out(sq)
    finally:
        db.close()


@router.get("", response_model=List[SavedQueryOut])
async def list_saved_queries(
    connection_id: Optional[int] = QParam(None),
    folder: Optional[str] = QParam(None),
    favorites_only: bool = QParam(False),
    user: dict = Depends(get_current_user),
):
    """List saved queries for the current user, optionally filtered."""
    db = SessionLocal()
    try:
        q = db.query(SavedQuery).filter(SavedQuery.user_id == int(user["sub"]))
        if connection_id is not None:
            q = q.filter(SavedQuery.connection_id == connection_id)
        if folder:
            q = q.filter(SavedQuery.folder == folder)
        if favorites_only:
            q = q.filter(SavedQuery.is_favorite == True)
        queries = q.order_by(SavedQuery.updated_at.desc()).all()
        return [_sq_out(sq) for sq in queries]
    finally:
        db.close()


@router.get("/folders", response_model=List[str])
async def list_folders(user: dict = Depends(get_current_user)):
    """List distinct folder names for the current user."""
    db = SessionLocal()
    try:
        rows = (
            db.query(SavedQuery.folder)
            .filter(SavedQuery.user_id == int(user["sub"]), SavedQuery.folder.isnot(None))
            .distinct()
            .all()
        )
        return sorted(set(r[0] for r in rows if r[0]))
    finally:
        db.close()


@router.put("/{query_id}", response_model=SavedQueryOut)
async def update_saved_query(
    query_id: int,
    body: UpdateSavedQueryReq,
    user: dict = Depends(get_current_user),
):
    """Update a saved query's metadata."""
    db = SessionLocal()
    try:
        sq = _own_query(db, query_id, int(user["sub"]))
        if body.name is not None:
            sq.name = body.name.strip()
        if body.description is not None:
            sq.description = body.description
        if body.folder is not None:
            sq.folder = body.folder if body.folder else None
        if body.is_favorite is not None:
            sq.is_favorite = body.is_favorite
        db.commit()
        db.refresh(sq)
        return _sq_out(sq)
    finally:
        db.close()


@router.delete("/{query_id}")
async def delete_saved_query(query_id: int, user: dict = Depends(get_current_user)):
    """Delete a saved query."""
    db = SessionLocal()
    try:
        sq = _own_query(db, query_id, int(user["sub"]))
        db.delete(sq)
        db.commit()
        return {"deleted": True}
    finally:
        db.close()


@router.post("/{query_id}/run", response_model=RunResult)
async def run_saved_query(
    query_id: int,
    page: int = QParam(1, ge=1),
    page_size: int = QParam(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    """Re-execute a saved query with pagination support."""
    db = SessionLocal()
    try:
        sq = _own_query(db, query_id, int(user["sub"]))

        if not has_db_permission(user, sq.connection_id, "prompt_query"):
            raise HTTPException(403, "Permission 'prompt_query' required on this database")

        chat_service = ChatService()
        try:
            raw = await chat_service.execute_query(
                connection_id=sq.connection_id,
                sql=sq.sql,
                timeout=30,
            )
        finally:
            chat_service.close()

        sq.run_count = (sq.run_count or 0) + 1
        sq.last_run_at = datetime.utcnow()
        db.commit()

        if not raw.get("success"):
            return RunResult(success=False, error=raw.get("error"), execution_time_ms=raw.get("execution_time_ms", 0))

        col_objs = raw.get("columns") or []
        col_names = [c["name"] if isinstance(c, dict) else c for c in col_objs]
        all_rows = raw.get("rows") or []
        total_count = len(all_rows)

        offset = (page - 1) * page_size
        paginated_rows = all_rows[offset:offset + page_size]

        return RunResult(
            success=True,
            columns=col_names,
            rows=paginated_rows,
            row_count=len(paginated_rows),
            total_count=total_count,
            execution_time_ms=raw.get("execution_time_ms", 0),
        )
    finally:
        db.close()


@router.post("/{query_id}/toggle-favorite", response_model=SavedQueryOut)
async def toggle_favorite(query_id: int, user: dict = Depends(get_current_user)):
    """Toggle the favorite status of a saved query."""
    db = SessionLocal()
    try:
        sq = _own_query(db, query_id, int(user["sub"]))
        sq.is_favorite = not sq.is_favorite
        db.commit()
        db.refresh(sq)
        return _sq_out(sq)
    finally:
        db.close()


def _own_query(db, query_id: int, user_id: int) -> SavedQuery:
    sq = db.query(SavedQuery).filter(SavedQuery.id == query_id, SavedQuery.user_id == user_id).first()
    if not sq:
        raise HTTPException(404, "Saved query not found")
    return sq


def _sq_out(sq: SavedQuery) -> SavedQueryOut:
    return SavedQueryOut(
        id=sq.id,
        connection_id=sq.connection_id,
        name=sq.name,
        sql=sq.sql,
        prompt=sq.prompt,
        description=sq.description,
        folder=sq.folder,
        is_favorite=sq.is_favorite,
        run_count=sq.run_count or 0,
        last_run_at=sq.last_run_at.isoformat() if sq.last_run_at else None,
        created_at=sq.created_at.isoformat() if sq.created_at else "",
        updated_at=sq.updated_at.isoformat() if sq.updated_at else "",
    )
