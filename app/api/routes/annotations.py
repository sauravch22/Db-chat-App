"""Result Annotations API – add notes, tags, and share findings."""

import json
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query as QParam
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import QueryAnnotation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/annotations", tags=["Annotations"])


class CreateAnnotationReq(BaseModel):
    connection_id: int
    note: str
    tags: Optional[List[str]] = None
    chat_history_id: Optional[int] = None
    saved_query_id: Optional[int] = None
    is_shared: bool = False


class UpdateAnnotationReq(BaseModel):
    note: Optional[str] = None
    tags: Optional[List[str]] = None
    is_shared: Optional[bool] = None


class AnnotationOut(BaseModel):
    id: int
    user_id: int
    username: Optional[str] = None
    connection_id: int
    chat_history_id: Optional[int] = None
    saved_query_id: Optional[int] = None
    note: str
    tags: List[str] = []
    is_shared: bool = False
    created_at: str
    updated_at: str


@router.post("", response_model=AnnotationOut, status_code=201)
async def create_annotation(body: CreateAnnotationReq, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        ann = QueryAnnotation(
            user_id=int(user["sub"]),
            connection_id=body.connection_id,
            chat_history_id=body.chat_history_id,
            saved_query_id=body.saved_query_id,
            note=body.note.strip(),
            tags=json.dumps(body.tags) if body.tags else None,
            is_shared=body.is_shared,
        )
        db.add(ann)
        db.commit()
        db.refresh(ann)
        return _ann_out(ann, user.get("username", ""))
    finally:
        db.close()


@router.get("", response_model=List[AnnotationOut])
async def list_annotations(
    connection_id: Optional[int] = QParam(None),
    chat_history_id: Optional[int] = QParam(None),
    saved_query_id: Optional[int] = QParam(None),
    include_shared: bool = QParam(False),
    user: dict = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        q = db.query(QueryAnnotation)
        if include_shared:
            from sqlalchemy import or_
            q = q.filter(or_(
                QueryAnnotation.user_id == int(user["sub"]),
                QueryAnnotation.is_shared == True
            ))
        else:
            q = q.filter(QueryAnnotation.user_id == int(user["sub"]))
        
        if connection_id is not None:
            q = q.filter(QueryAnnotation.connection_id == connection_id)
        if chat_history_id is not None:
            q = q.filter(QueryAnnotation.chat_history_id == chat_history_id)
        if saved_query_id is not None:
            q = q.filter(QueryAnnotation.saved_query_id == saved_query_id)
        
        anns = q.order_by(QueryAnnotation.created_at.desc()).limit(100).all()
        return [_ann_out(a, user.get("username", "")) for a in anns]
    finally:
        db.close()


@router.put("/{annotation_id}", response_model=AnnotationOut)
async def update_annotation(annotation_id: int, body: UpdateAnnotationReq, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        ann = db.query(QueryAnnotation).filter(
            QueryAnnotation.id == annotation_id,
            QueryAnnotation.user_id == int(user["sub"])
        ).first()
        if not ann:
            raise HTTPException(404, "Annotation not found")
        if body.note is not None:
            ann.note = body.note.strip()
        if body.tags is not None:
            ann.tags = json.dumps(body.tags) if body.tags else None
        if body.is_shared is not None:
            ann.is_shared = body.is_shared
        db.commit()
        db.refresh(ann)
        return _ann_out(ann, user.get("username", ""))
    finally:
        db.close()


@router.delete("/{annotation_id}")
async def delete_annotation(annotation_id: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        ann = db.query(QueryAnnotation).filter(
            QueryAnnotation.id == annotation_id,
            QueryAnnotation.user_id == int(user["sub"])
        ).first()
        if not ann:
            raise HTTPException(404, "Annotation not found")
        db.delete(ann)
        db.commit()
        return {"deleted": True}
    finally:
        db.close()


def _ann_out(a: QueryAnnotation, username: str = "") -> AnnotationOut:
    return AnnotationOut(
        id=a.id,
        user_id=a.user_id,
        username=username,
        connection_id=a.connection_id,
        chat_history_id=a.chat_history_id,
        saved_query_id=a.saved_query_id,
        note=a.note,
        tags=json.loads(a.tags) if a.tags else [],
        is_shared=a.is_shared if a.is_shared else False,
        created_at=a.created_at.isoformat() if a.created_at else "",
        updated_at=a.updated_at.isoformat() if a.updated_at else "",
    )
