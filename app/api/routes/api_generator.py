"""API Endpoint Generator — turn saved queries into REST API endpoints."""

import json
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from app.api.deps import get_current_user
from app.database import SessionLocal
from app.models import GeneratedEndpoint, SavedQuery
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/endpoints", tags=["API Generator"])

_generated_endpoints = {}


class CreateEndpointRequest(BaseModel):
    saved_query_id: int
    path_slug: str
    method: str = "GET"
    description: Optional[str] = None
    rate_limit: int = 100


@router.post("/generate")
async def generate_endpoint(req: CreateEndpointRequest, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        sq = db.query(SavedQuery).filter(SavedQuery.id == req.saved_query_id).first()
        if not sq:
            raise HTTPException(404, "Saved query not found")

        slug = req.path_slug.strip("/").replace(" ", "-").lower()
        slug = "".join(c if c.isalnum() or c in ("-", "_") else "" for c in slug)

        api_key = uuid.uuid4().hex[:24]
        ep = GeneratedEndpoint(
            user_id=int(user["sub"]),
            saved_query_id=sq.id,
            connection_id=sq.connection_id,
            path_slug=slug,
            method=req.method.upper(),
            api_key=api_key,
            description=req.description or sq.description,
            rate_limit=req.rate_limit,
            is_active=True,
        )
        db.add(ep)
        db.commit()
        db.refresh(ep)

        return {
            "id": ep.id,
            "url": f"/api/v1/{slug}",
            "method": ep.method,
            "api_key": api_key,
            "description": ep.description,
            "status": "created",
        }
    finally:
        db.close()


@router.get("")
async def list_endpoints(user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        endpoints = db.query(GeneratedEndpoint).filter(
            GeneratedEndpoint.user_id == int(user["sub"]),
        ).order_by(GeneratedEndpoint.created_at.desc()).all()
        return [
            {
                "id": ep.id,
                "url": f"/api/v1/{ep.path_slug}",
                "method": ep.method,
                "api_key": ep.api_key[:8] + "…",
                "description": ep.description,
                "is_active": ep.is_active,
                "call_count": ep.call_count,
                "created_at": ep.created_at.isoformat() if ep.created_at else None,
            }
            for ep in endpoints
        ]
    finally:
        db.close()


@router.delete("/{endpoint_id}")
async def delete_endpoint(endpoint_id: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        ep = db.query(GeneratedEndpoint).filter(GeneratedEndpoint.id == endpoint_id).first()
        if not ep:
            raise HTTPException(404, "Endpoint not found")
        db.delete(ep)
        db.commit()
        return {"deleted": True}
    finally:
        db.close()


@router.get("/v1/{slug:path}")
async def call_generated_endpoint(slug: str, request: Request):
    """Public endpoint — execute a generated API query."""
    api_key = request.headers.get("X-API-Key", request.query_params.get("api_key", ""))
    if not api_key:
        raise HTTPException(401, "API key required (X-API-Key header or api_key param)")

    db = SessionLocal()
    try:
        ep = db.query(GeneratedEndpoint).filter(
            GeneratedEndpoint.path_slug == slug,
            GeneratedEndpoint.api_key == api_key,
            GeneratedEndpoint.is_active == True,
        ).first()
        if not ep:
            raise HTTPException(404, "Endpoint not found or invalid API key")

        sq = db.query(SavedQuery).filter(SavedQuery.id == ep.saved_query_id).first()
        if not sq:
            raise HTTPException(500, "Linked saved query not found")

        svc = ChatService()
        try:
            result = await svc.execute_query(connection_id=ep.connection_id, sql=sq.sql)
        finally:
            svc.close()

        ep.call_count = (ep.call_count or 0) + 1
        db.commit()

        if result.get("success"):
            return {"data": result.get("rows", []), "row_count": result.get("row_count", 0),
                    "columns": [c["name"] if isinstance(c, dict) else c for c in result.get("columns", [])]}
        else:
            raise HTTPException(500, result.get("error", "Query failed"))
    finally:
        db.close()
