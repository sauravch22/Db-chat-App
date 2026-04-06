"""Query Template Library API — pre-built BI templates with variable substitution."""

import json
import logging
from fastapi import APIRouter, HTTPException, Depends, Query as QParam
from pydantic import BaseModel
from typing import Optional, List

from app.api.deps import get_current_user
from app.database import SessionLocal
from app.models import QueryTemplate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/templates", tags=["Query Templates"])

BUILTIN_TEMPLATES = [
    {
        "name": "Row Count per Table",
        "description": "Get row count for a specific table",
        "category": "General",
        "sql_template": "SELECT COUNT(*) AS row_count FROM {{table}}",
        "variables": [{"name": "table", "label": "Table name", "default": ""}],
    },
    {
        "name": "Top N Records",
        "description": "Get the top N records from a table ordered by a column",
        "category": "General",
        "sql_template": "SELECT * FROM {{table}} ORDER BY {{order_col}} DESC LIMIT {{limit}}",
        "variables": [
            {"name": "table", "label": "Table", "default": ""},
            {"name": "order_col", "label": "Order by column", "default": "id"},
            {"name": "limit", "label": "Limit", "default": "10"},
        ],
    },
    {
        "name": "Revenue by Period",
        "description": "Aggregate revenue (SUM) grouped by a date truncation",
        "category": "Finance",
        "sql_template": "SELECT DATE_TRUNC('{{period}}', {{date_col}}) AS period, SUM({{amount_col}}) AS total FROM {{table}} GROUP BY 1 ORDER BY 1",
        "variables": [
            {"name": "table", "label": "Table", "default": "orders"},
            {"name": "date_col", "label": "Date column", "default": "created_at"},
            {"name": "amount_col", "label": "Amount column", "default": "total"},
            {"name": "period", "label": "Period (day/week/month/year)", "default": "month"},
        ],
    },
    {
        "name": "Group Distribution",
        "description": "Count records grouped by a categorical column",
        "category": "Analytics",
        "sql_template": "SELECT {{group_col}}, COUNT(*) AS count FROM {{table}} GROUP BY {{group_col}} ORDER BY count DESC",
        "variables": [
            {"name": "table", "label": "Table", "default": ""},
            {"name": "group_col", "label": "Group by column", "default": "status"},
        ],
    },
    {
        "name": "Duplicate Finder",
        "description": "Find duplicate values in a column",
        "category": "Data Quality",
        "sql_template": "SELECT {{col}}, COUNT(*) AS occurrences FROM {{table}} GROUP BY {{col}} HAVING COUNT(*) > 1 ORDER BY occurrences DESC",
        "variables": [
            {"name": "table", "label": "Table", "default": ""},
            {"name": "col", "label": "Column to check", "default": "email"},
        ],
    },
    {
        "name": "Null Analysis",
        "description": "Count NULL vs non-NULL values in a column",
        "category": "Data Quality",
        "sql_template": "SELECT COUNT(*) AS total, COUNT({{col}}) AS non_null, COUNT(*) - COUNT({{col}}) AS null_count, ROUND(100.0 * (COUNT(*) - COUNT({{col}})) / NULLIF(COUNT(*), 0), 1) AS null_pct FROM {{table}}",
        "variables": [
            {"name": "table", "label": "Table", "default": ""},
            {"name": "col", "label": "Column", "default": ""},
        ],
    },
    {
        "name": "Recent Activity",
        "description": "Records created in the last N days",
        "category": "Monitoring",
        "sql_template": "SELECT * FROM {{table}} WHERE {{date_col}} >= NOW() - INTERVAL '{{days}} days' ORDER BY {{date_col}} DESC LIMIT {{limit}}",
        "variables": [
            {"name": "table", "label": "Table", "default": ""},
            {"name": "date_col", "label": "Date column", "default": "created_at"},
            {"name": "days", "label": "Days back", "default": "7"},
            {"name": "limit", "label": "Max rows", "default": "100"},
        ],
    },
    {
        "name": "Column Statistics",
        "description": "Min, max, avg, stddev for a numeric column",
        "category": "Analytics",
        "sql_template": "SELECT MIN({{col}}) AS min_val, MAX({{col}}) AS max_val, ROUND(AVG({{col}})::numeric, 2) AS avg_val, ROUND(STDDEV({{col}})::numeric, 2) AS stddev_val, COUNT({{col}}) AS count FROM {{table}}",
        "variables": [
            {"name": "table", "label": "Table", "default": ""},
            {"name": "col", "label": "Numeric column", "default": "amount"},
        ],
    },
    {
        "name": "Year-over-Year Comparison",
        "description": "Compare metric across years",
        "category": "Finance",
        "sql_template": "SELECT EXTRACT(YEAR FROM {{date_col}}) AS year, EXTRACT(MONTH FROM {{date_col}}) AS month, SUM({{amount_col}}) AS total FROM {{table}} GROUP BY 1, 2 ORDER BY 1, 2",
        "variables": [
            {"name": "table", "label": "Table", "default": "orders"},
            {"name": "date_col", "label": "Date column", "default": "order_date"},
            {"name": "amount_col", "label": "Amount column", "default": "total"},
        ],
    },
    {
        "name": "Table Schema Info",
        "description": "Get column details for a table (PostgreSQL)",
        "category": "Schema",
        "db_type": "postgres",
        "sql_template": "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name = '{{table}}' ORDER BY ordinal_position",
        "variables": [
            {"name": "table", "label": "Table name", "default": ""},
        ],
    },
]


def _seed_builtins(db):
    """Insert builtin templates if table is empty."""
    existing = db.query(QueryTemplate).filter(QueryTemplate.is_builtin == True).count()
    if existing > 0:
        return
    for t in BUILTIN_TEMPLATES:
        db.add(QueryTemplate(
            name=t["name"],
            description=t.get("description"),
            category=t["category"],
            db_type=t.get("db_type"),
            sql_template=t["sql_template"],
            variables=json.dumps(t["variables"]),
            is_builtin=True,
        ))
    db.commit()
    logger.info("Seeded %d builtin query templates", len(BUILTIN_TEMPLATES))


@router.get("")
async def list_templates(
    category: Optional[str] = QParam(None),
    db_type: Optional[str] = QParam(None),
    user: dict = Depends(get_current_user),
):
    """List available query templates, optionally filtered by category or db_type."""
    db = SessionLocal()
    try:
        _seed_builtins(db)
        q = db.query(QueryTemplate)
        if category:
            q = q.filter(QueryTemplate.category == category)
        if db_type:
            q = q.filter((QueryTemplate.db_type == None) | (QueryTemplate.db_type == db_type))
        templates = q.order_by(QueryTemplate.category, QueryTemplate.name).all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "db_type": t.db_type,
                "sql_template": t.sql_template,
                "variables": json.loads(t.variables) if t.variables else [],
                "is_builtin": t.is_builtin,
                "use_count": t.use_count,
            }
            for t in templates
        ]
    finally:
        db.close()


@router.get("/categories")
async def list_categories(user: dict = Depends(get_current_user)):
    """List distinct template categories."""
    db = SessionLocal()
    try:
        _seed_builtins(db)
        rows = db.query(QueryTemplate.category).distinct().all()
        return [r[0] for r in rows if r[0]]
    finally:
        db.close()


class RenderRequest(BaseModel):
    template_id: int
    variables: dict


@router.post("/render")
async def render_template(
    request: RenderRequest,
    user: dict = Depends(get_current_user),
):
    """Substitute variables into a template and return the final SQL."""
    db = SessionLocal()
    try:
        t = db.query(QueryTemplate).filter(QueryTemplate.id == request.template_id).first()
        if not t:
            raise HTTPException(404, "Template not found")

        sql = t.sql_template
        for k, v in request.variables.items():
            sql = sql.replace("{{" + k + "}}", str(v))

        t.use_count = (t.use_count or 0) + 1
        db.commit()

        return {"sql": sql, "template_name": t.name}
    finally:
        db.close()


class CreateTemplateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    category: str
    db_type: Optional[str] = None
    sql_template: str
    variables: Optional[List[dict]] = None


@router.post("/create")
async def create_template(
    request: CreateTemplateRequest,
    user: dict = Depends(get_current_user),
):
    """Create a user-defined template."""
    db = SessionLocal()
    try:
        t = QueryTemplate(
            name=request.name,
            description=request.description,
            category=request.category,
            db_type=request.db_type,
            sql_template=request.sql_template,
            variables=json.dumps(request.variables or []),
            is_builtin=False,
            created_by=int(user["sub"]),
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        return {"id": t.id, "name": t.name}
    finally:
        db.close()


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    user: dict = Depends(get_current_user),
):
    """Delete a user-created template (cannot delete builtins)."""
    db = SessionLocal()
    try:
        t = db.query(QueryTemplate).filter(QueryTemplate.id == template_id).first()
        if not t:
            raise HTTPException(404, "Template not found")
        if t.is_builtin:
            raise HTTPException(400, "Cannot delete built-in templates")
        db.delete(t)
        db.commit()
        return {"deleted": True}
    finally:
        db.close()
