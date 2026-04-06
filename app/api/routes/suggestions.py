"""Smart Suggestions API – follow-up query suggestions based on context."""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query as QParam
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import ChatHistory, Table, Database, Column

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/suggestions", tags=["Suggestions"])


class SuggestionsResponse(BaseModel):
    follow_ups: List[str] = []
    related_tables: List[str] = []
    popular_queries: List[str] = []


@router.get("", response_model=SuggestionsResponse)
async def get_suggestions(
    connection_id: int = QParam(...),
    prompt: Optional[str] = QParam(None),
    sql: Optional[str] = QParam(None),
    user: dict = Depends(get_current_user),
):
    """Generate smart follow-up suggestions based on the last query and context."""
    if not has_db_permission(user, connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required")
    
    db = SessionLocal()
    try:
        follow_ups = []
        related_tables = []
        popular_queries = []
        
        # Generate contextual follow-ups from the last query
        if prompt and sql:
            follow_ups = _generate_follow_ups(prompt, sql)
        
        # Find tables related to the current context
        databases = db.query(Database).filter(Database.connection_id == connection_id).all()
        if databases:
            tables = db.query(Table).filter(
                Table.database_id.in_([d.id for d in databases])
            ).all()
            
            if sql:
                sql_lower = sql.lower()
                mentioned = [t.name for t in tables if t.name.lower() in sql_lower]
                from app.models import ForeignKeyModel
                for tname in mentioned:
                    fks = db.query(ForeignKeyModel).filter(
                        ForeignKeyModel.database_id.in_([d.id for d in databases]),
                        (ForeignKeyModel.table_name == tname) | (ForeignKeyModel.referenced_table == tname)
                    ).all()
                    for fk in fks:
                        related = fk.referenced_table if fk.table_name == tname else fk.table_name
                        if related not in mentioned and related not in related_tables:
                            related_tables.append(related)
            
            related_tables = related_tables[:5]
        
        # Popular queries from this user's history
        recent = (
            db.query(ChatHistory.prompt)
            .filter(
                ChatHistory.user_id == int(user["sub"]),
                ChatHistory.connection_id == connection_id,
                ChatHistory.status == "success",
            )
            .order_by(ChatHistory.created_at.desc())
            .limit(20)
            .all()
        )
        seen = set()
        for r in recent:
            p = r[0].strip()[:100]
            if p not in seen and len(p) > 10:
                seen.add(p)
                popular_queries.append(p)
            if len(popular_queries) >= 5:
                break
        
        return SuggestionsResponse(
            follow_ups=follow_ups,
            related_tables=related_tables,
            popular_queries=popular_queries,
        )
    finally:
        db.close()


def _generate_follow_ups(prompt: str, sql: str) -> List[str]:
    """Generate contextual follow-up suggestions from a query."""
    suggestions = []
    sql_lower = sql.lower()
    prompt_lower = prompt.lower()
    
    if "group by" in sql_lower:
        suggestions.append("Show me the trend over time")
        suggestions.append("Which category has the highest value?")
    
    if "count" in sql_lower or "sum" in sql_lower:
        suggestions.append("Break this down by month")
        suggestions.append("Compare this to last period")
        suggestions.append("What percentage does each represent?")
    
    if "where" in sql_lower:
        suggestions.append("Show me all records without this filter")
        suggestions.append("What are the top 10 results?")
    
    if "order by" in sql_lower:
        suggestions.append("Show me the bottom results instead")
    
    if "join" in sql_lower:
        suggestions.append("Which records don't have matches?")
    
    if any(w in prompt_lower for w in ["total", "sum", "count", "how many"]):
        suggestions.append("Show me a breakdown by category")
        suggestions.append("What's the average instead?")
    
    if any(w in prompt_lower for w in ["top", "best", "highest", "most"]):
        suggestions.append("Show me the worst/lowest instead")
        suggestions.append("How has this changed over time?")
    
    return suggestions[:6]
