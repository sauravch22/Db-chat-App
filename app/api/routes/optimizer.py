"""AI Query Optimizer — analyzes slow queries and suggests improvements."""

import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import Connection
from app.services.ollama_service import OllamaService
from app.services.schema_service import SchemaExtractor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/optimizer", tags=["Query Optimizer"])


class OptimizeRequest(BaseModel):
    connection_id: int
    sql: str


@router.post("/analyze")
async def analyze_query(req: OptimizeRequest, user: dict = Depends(get_current_user)):
    """Analyze a SQL query for performance issues and suggest optimizations."""
    if not has_db_permission(user, req.connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required on this database")
    sql_upper = req.sql.strip().upper()
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        raise HTTPException(400, "Only SELECT queries can be analyzed")
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == req.connection_id,
                                            Connection.is_active == True).first()
        if not conn:
            raise HTTPException(404, "Connection not found")

        analysis = {"sql": req.sql, "issues": [], "suggestions": [],
                     "explain_plan": None, "optimized_sql": None}

        if conn.database_type.lower() in ("postgres", "postgresql"):
            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import NullPool
            conn_str = SchemaExtractor.build_connection_string(
                conn.database_type, conn.host, conn.port,
                conn.username, conn.password, conn.database
            )
            engine = create_engine(conn_str, poolclass=NullPool,
                                    connect_args={"connect_timeout": 10})
            try:
                with engine.connect() as c:
                    explain_sql = f"EXPLAIN (FORMAT JSON, ANALYZE false) {req.sql}"
                    plan_result = c.execute(text(explain_sql))
                    plan = plan_result.fetchone()[0]
                    analysis["explain_plan"] = plan

                    if isinstance(plan, list) and plan:
                        node = plan[0].get("Plan", {})
                        total_cost = node.get("Total Cost", 0)
                        node_type = node.get("Node Type", "")

                        if total_cost > 10000:
                            analysis["issues"].append({
                                "severity": "high",
                                "message": f"High estimated cost: {total_cost:.0f}",
                            })
                        if "Seq Scan" in node_type:
                            analysis["issues"].append({
                                "severity": "medium",
                                "message": f"Sequential scan on {node.get('Relation Name', 'table')}",
                                "suggestion": "Consider adding an index on filtered columns",
                            })

                        def _walk_plan(n):
                            if "Plans" in n:
                                for child in n["Plans"]:
                                    if child.get("Node Type") == "Seq Scan" and child.get("Total Cost", 0) > 1000:
                                        analysis["issues"].append({
                                            "severity": "medium",
                                            "message": f"Expensive sequential scan on {child.get('Relation Name', '')}",
                                        })
                                    _walk_plan(child)
                        _walk_plan(node)
            except Exception as e:
                analysis["issues"].append({"severity": "info", "message": f"Could not run EXPLAIN: {e}"})
            finally:
                engine.dispose()

        svc = OllamaService()
        try:
            system = """You are a database performance expert. Analyze the SQL query and provide:
1. Performance issues (be specific about which parts are slow and why)
2. Optimization suggestions (rewrite suggestions, index recommendations)
3. An optimized version of the query if possible

Output JSON with keys: issues (array of strings), suggestions (array of strings), optimized_sql (string or null)"""

            prompt = f"SQL: {req.sql}"
            if analysis["explain_plan"]:
                prompt += f"\n\nEXPLAIN plan: {json.dumps(analysis['explain_plan'][:1])}"

            raw = await svc._call_chat_completions(system, prompt, max_tokens=800)
            raw = raw.replace("```json", "").replace("```", "").strip()
            try:
                ai_analysis = json.loads(raw)
                if ai_analysis.get("suggestions"):
                    analysis["suggestions"].extend(ai_analysis["suggestions"])
                if ai_analysis.get("issues"):
                    for iss in ai_analysis["issues"]:
                        analysis["issues"].append({"severity": "info", "message": iss})
                if ai_analysis.get("optimized_sql"):
                    analysis["optimized_sql"] = ai_analysis["optimized_sql"]
            except json.JSONDecodeError:
                analysis["suggestions"].append(raw[:500])
        except Exception as e:
            logger.warning("AI optimizer failed: %s", e)

        return analysis
    finally:
        db.close()
