"""Query Validation API – EXPLAIN plan + safety analysis before execution."""

import time
import re
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import Connection
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/validate", tags=["Query Validation"])


class ValidateRequest(BaseModel):
    connection_id: int
    sql: str


class ValidationWarning(BaseModel):
    level: str  # info | warning | danger
    message: str
    suggestion: Optional[str] = None


class ValidateResponse(BaseModel):
    is_safe: bool
    estimated_cost: Optional[str] = None
    estimated_rows: Optional[int] = None
    plan: Optional[List[Dict[str, Any]]] = None
    plan_text: Optional[str] = None
    warnings: List[ValidationWarning] = []
    execution_time_ms: int = 0


@router.post("/query", response_model=ValidateResponse)
async def validate_query(
    request: ValidateRequest,
    user: dict = Depends(get_current_user),
):
    """Validate a SQL query by running EXPLAIN and analyzing for potential issues."""
    if not has_db_permission(user, request.connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required")
    
    t0 = time.time()
    warnings = []
    sql_upper = request.sql.strip().upper()
    
    # Static analysis
    if any(kw in sql_upper for kw in ["DROP ", "TRUNCATE ", "ALTER ", "CREATE "]):
        warnings.append(ValidationWarning(level="danger", message="DDL statement detected", suggestion="This query modifies database structure"))
    
    if "DELETE " in sql_upper and "WHERE" not in sql_upper:
        warnings.append(ValidationWarning(level="danger", message="DELETE without WHERE clause", suggestion="This will delete all rows in the table"))
    
    if "UPDATE " in sql_upper and "WHERE" not in sql_upper:
        warnings.append(ValidationWarning(level="danger", message="UPDATE without WHERE clause", suggestion="This will update all rows in the table"))
    
    if "SELECT " in sql_upper and " LIMIT" not in sql_upper and "COUNT(" not in sql_upper:
        warnings.append(ValidationWarning(level="warning", message="No LIMIT clause", suggestion="Consider adding LIMIT to avoid fetching too many rows"))
    
    if sql_upper.count(" JOIN ") > 3:
        warnings.append(ValidationWarning(level="warning", message=f"Multiple JOINs detected ({sql_upper.count(' JOIN ')})", suggestion="Complex joins may be slow; check indexes"))
    
    if "SELECT *" in sql_upper:
        warnings.append(ValidationWarning(level="info", message="SELECT * used", suggestion="Consider selecting only needed columns for better performance"))
    
    cross_join = "CROSS JOIN" in sql_upper or (", " in request.sql and "JOIN" not in sql_upper and "WHERE" not in sql_upper)
    if cross_join:
        warnings.append(ValidationWarning(level="danger", message="Possible cartesian join", suggestion="This may produce a massive result set"))
    
    # Try EXPLAIN
    plan_text = None
    estimated_rows = None
    estimated_cost = None
    plan = None
    
    if sql_upper.startswith("SELECT") or sql_upper.startswith("WITH"):
        try:
            chat_service = ChatService()
            try:
                explain_sql = f"EXPLAIN (FORMAT JSON) {request.sql}"
                result = await chat_service.execute_query(
                    connection_id=request.connection_id,
                    sql=explain_sql,
                    timeout=10,
                )
                if result.get("success") and result.get("rows"):
                    import json
                    plan_data = result["rows"]
                    if plan_data and isinstance(plan_data, list):
                        first = plan_data[0]
                        qp = first.get("QUERY PLAN") or first.get("query plan") or first.get("query_plan")
                        if qp:
                            if isinstance(qp, str):
                                qp = json.loads(qp)
                            if isinstance(qp, list) and len(qp) > 0:
                                plan_node = qp[0].get("Plan", qp[0])
                                estimated_rows = plan_node.get("Plan Rows")
                                startup = plan_node.get("Startup Cost", 0)
                                total = plan_node.get("Total Cost", 0)
                                estimated_cost = f"{startup:.1f}..{total:.1f}"
                                plan = qp
                                
                                if total > 10000:
                                    warnings.append(ValidationWarning(level="warning", message=f"High estimated cost: {total:.0f}", suggestion="This query may take a while"))
                                
                                plan_str = json.dumps(qp, indent=2)
                                if "Seq Scan" in plan_str and estimated_rows and estimated_rows > 10000:
                                    warnings.append(ValidationWarning(level="warning", message="Sequential scan on large table", suggestion="Consider adding an index"))
            finally:
                chat_service.close()
        except Exception as e:
            logger.warning(f"EXPLAIN failed: {e}")
            plan_text = f"Could not run EXPLAIN: {str(e)}"
    
    dur = int((time.time() - t0) * 1000)
    is_safe = not any(w.level == "danger" for w in warnings)
    
    return ValidateResponse(
        is_safe=is_safe,
        estimated_cost=estimated_cost,
        estimated_rows=estimated_rows,
        plan=plan,
        plan_text=plan_text,
        warnings=warnings,
        execution_time_ms=dur,
    )
