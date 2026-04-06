"""AI Data Summarization API — generates plain-English insights from query results."""

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.api.deps import get_current_user
from app.services.ollama_service import OllamaService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/summarize", tags=["Data Summarization"])


class SummarizeRequest(BaseModel):
    prompt: str
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int


@router.post("")
async def summarize_results(
    request: SummarizeRequest,
    user: dict = Depends(get_current_user),
):
    """Generate AI insights from query results."""
    svc = OllamaService()
    summary = await svc.summarize_data(
        user_prompt=request.prompt,
        columns=request.columns,
        rows=request.rows,
        row_count=request.row_count,
    )
    return {"summary": summary}
