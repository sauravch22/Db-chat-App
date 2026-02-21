"""Chat API endpoints"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


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


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat endpoint - Process natural language query
    
    Complete flow:
    1. Embed user prompt with Ollama
    2. Vector search in Qdrant for relevant tables
    3. Fetch schema context from PostgreSQL
    4. Generate SQL query with Ollama
    5. Validate SQL (SELECT only)
    6. Execute on user database
    7. Format results with natural language answer
    
    Args:
        connection_id: ID of the database connection to query
        prompt: Natural language question
        top_k_tables: Number of most relevant tables to include (default: 5)
    
    Returns:
        Status, answer, SQL, results, and execution time
    """
    
    try:
        logger.info(f"Chat request: connection={request.connection_id}, prompt='{request.prompt[:50]}'")
        
        # Create chat service
        chat_service = ChatService()
        
        try:
            # Process query
            result = await chat_service.process_query(
                connection_id=request.connection_id,
                user_prompt=request.prompt,
                top_k_tables=request.top_k_tables
            )
            
            return ChatResponse(
                status=result.get("status", "error"),
                answer=result.get("answer"),
                sql=result.get("sql"),
                rows=result.get("rows"),
                columns=result.get("columns"),
                row_count=result.get("row_count"),
                execution_time_ms=result.get("execution_time_ms", 0),
                query_time_ms=result.get("query_time_ms"),
                error=result.get("error")
            )
        
        finally:
            chat_service.close()
    
    except Exception as e:
        logger.error(f"Chat endpoint error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
