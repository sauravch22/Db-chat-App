"""Training / RAG API — store successful query pairs for improved future generation."""

import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query as QParam
from pydantic import BaseModel
from typing import Optional, List

from app.api.deps import get_current_user
from app.database import SessionLocal
from app.models import TrainingPair

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/training", tags=["Training / RAG"])


class AddTrainingPairRequest(BaseModel):
    connection_id: int
    question: str
    query: str
    query_type: str = "sql"
    is_verified: bool = True


@router.post("")
async def add_training_pair(req: AddTrainingPairRequest, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        pair = TrainingPair(
            user_id=int(user["sub"]),
            connection_id=req.connection_id,
            question=req.question,
            query=req.query,
            query_type=req.query_type,
            is_verified=req.is_verified,
        )
        db.add(pair)
        db.commit()
        db.refresh(pair)
        return {"id": pair.id, "status": "saved"}
    finally:
        db.close()


@router.get("")
async def list_training_pairs(
    connection_id: Optional[int] = QParam(None),
    limit: int = QParam(50),
    user: dict = Depends(get_current_user),
):
    db = SessionLocal()
    try:
        q = db.query(TrainingPair)
        if connection_id:
            q = q.filter(TrainingPair.connection_id == connection_id)
        pairs = q.order_by(TrainingPair.created_at.desc()).limit(limit).all()
        return [
            {"id": p.id, "question": p.question, "query": p.query,
             "query_type": p.query_type, "is_verified": p.is_verified,
             "upvotes": p.upvotes, "created_at": p.created_at.isoformat() if p.created_at else None}
            for p in pairs
        ]
    finally:
        db.close()


@router.post("/{pair_id}/upvote")
async def upvote_pair(pair_id: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        pair = db.query(TrainingPair).filter(TrainingPair.id == pair_id).first()
        if not pair:
            raise HTTPException(404, "Training pair not found")
        pair.upvotes = (pair.upvotes or 0) + 1
        db.commit()
        return {"upvotes": pair.upvotes}
    finally:
        db.close()


@router.delete("/{pair_id}")
async def delete_training_pair(pair_id: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        pair = db.query(TrainingPair).filter(TrainingPair.id == pair_id).first()
        if not pair:
            raise HTTPException(404, "Training pair not found")
        db.delete(pair)
        db.commit()
        return {"deleted": True}
    finally:
        db.close()


@router.get("/context/{connection_id}")
async def get_training_context(connection_id: int, question: str = QParam(""),
                                user: dict = Depends(get_current_user)):
    """Get relevant training pairs for RAG context injection."""
    db = SessionLocal()
    try:
        pairs = db.query(TrainingPair).filter(
            TrainingPair.connection_id == connection_id,
            TrainingPair.is_verified == True,
        ).order_by(TrainingPair.upvotes.desc()).limit(20).all()
        
        context_lines = []
        for p in pairs:
            context_lines.append(f"Q: {p.question}\n{p.query_type.upper()}: {p.query}")
        return {"context": "\n\n".join(context_lines), "pair_count": len(pairs)}
    finally:
        db.close()


@router.post("/auto-save")
async def auto_save_from_chat(
    connection_id: int,
    question: str,
    query: str,
    query_type: str = "sql",
    user: dict = Depends(get_current_user),
):
    """Automatically save a successful chat interaction as a training pair."""
    db = SessionLocal()
    try:
        existing = db.query(TrainingPair).filter(
            TrainingPair.connection_id == connection_id,
            TrainingPair.question == question,
        ).first()
        if existing:
            return {"id": existing.id, "status": "already_exists"}
        pair = TrainingPair(
            user_id=int(user["sub"]),
            connection_id=connection_id,
            question=question,
            query=query,
            query_type=query_type,
            is_verified=False,
        )
        db.add(pair)
        db.commit()
        db.refresh(pair)
        return {"id": pair.id, "status": "auto_saved"}
    finally:
        db.close()
