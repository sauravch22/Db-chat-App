"""Data Lineage API – table dependencies, usage analysis, and impact assessment."""

import json
from typing import Optional, List, Dict, Any
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Depends, Query as QParam
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import (Connection, Database, Table, Column, ForeignKeyModel,
                        ChatHistory, Query, SavedQuery)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lineage", tags=["Data Lineage"])


class TableDependency(BaseModel):
    table_name: str
    dependency_type: str  # fk_parent | fk_child | query_co_occurrence | view_dependency
    related_table: str
    via_column: Optional[str] = None
    strength: float = 1.0


class TableUsage(BaseModel):
    table_name: str
    query_count: int = 0
    unique_users: int = 0
    last_queried_at: Optional[str] = None
    common_co_tables: List[str] = []


class ImpactAssessment(BaseModel):
    table_name: str
    direct_dependents: List[str] = []
    indirect_dependents: List[str] = []
    affected_saved_queries: int = 0
    affected_dashboards: int = 0
    total_impact_score: int = 0


class LineageResponse(BaseModel):
    connection_id: int
    dependencies: List[TableDependency]
    table_usage: List[TableUsage]


@router.get("/{connection_id}", response_model=LineageResponse)
async def get_lineage(
    connection_id: int,
    user: dict = Depends(get_current_user),
):
    """Get data lineage and dependency graph for a connection."""
    if not has_db_permission(user, connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required")
    
    db = SessionLocal()
    try:
        databases = db.query(Database).filter(Database.connection_id == connection_id).all()
        if not databases:
            return LineageResponse(connection_id=connection_id, dependencies=[], table_usage=[])
        
        db_ids = [d.id for d in databases]
        tables = db.query(Table).filter(Table.database_id.in_(db_ids)).all()
        table_names = {t.name for t in tables}
        
        # FK dependencies
        deps = []
        fks = db.query(ForeignKeyModel).filter(ForeignKeyModel.database_id.in_(db_ids)).all()
        for fk in fks:
            deps.append(TableDependency(
                table_name=fk.table_name,
                dependency_type="fk_child",
                related_table=fk.referenced_table,
                via_column=f"{fk.column_name} -> {fk.referenced_column}",
                strength=1.0,
            ))
            deps.append(TableDependency(
                table_name=fk.referenced_table,
                dependency_type="fk_parent",
                related_table=fk.table_name,
                via_column=f"{fk.referenced_column} <- {fk.column_name}",
                strength=1.0,
            ))
        
        # Query co-occurrence analysis
        histories = (
            db.query(ChatHistory)
            .filter(
                ChatHistory.connection_id == connection_id,
                ChatHistory.selected_tables.isnot(None),
                ChatHistory.status == "success",
            )
            .order_by(ChatHistory.created_at.desc())
            .limit(200)
            .all()
        )
        
        co_occurrence = defaultdict(lambda: defaultdict(int))
        table_query_counts = defaultdict(int)
        table_users = defaultdict(set)
        table_last_queried = {}
        
        for h in histories:
            try:
                sel_tables = json.loads(h.selected_tables) if h.selected_tables else []
            except (json.JSONDecodeError, TypeError):
                sel_tables = []
            for t in sel_tables:
                table_query_counts[t] += 1
                table_users[t].add(h.user_id)
                if t not in table_last_queried:
                    table_last_queried[t] = h.created_at
            for i, t1 in enumerate(sel_tables):
                for t2 in sel_tables[i+1:]:
                    co_occurrence[t1][t2] += 1
                    co_occurrence[t2][t1] += 1
        
        for t1, related in co_occurrence.items():
            for t2, count in related.items():
                if count >= 2:
                    deps.append(TableDependency(
                        table_name=t1,
                        dependency_type="query_co_occurrence",
                        related_table=t2,
                        strength=min(count / 10.0, 1.0),
                    ))
        
        # Table usage stats
        usage = []
        for t in tables:
            common_co = sorted(co_occurrence.get(t.name, {}).items(), key=lambda x: -x[1])[:5]
            lq = table_last_queried.get(t.name)
            usage.append(TableUsage(
                table_name=t.name,
                query_count=table_query_counts.get(t.name, 0),
                unique_users=len(table_users.get(t.name, set())),
                last_queried_at=lq.isoformat() if lq else None,
                common_co_tables=[c[0] for c in common_co],
            ))
        
        usage.sort(key=lambda u: -u.query_count)
        
        return LineageResponse(
            connection_id=connection_id,
            dependencies=deps,
            table_usage=usage,
        )
    finally:
        db.close()


@router.get("/impact/{connection_id}/{table_name}", response_model=ImpactAssessment)
async def assess_impact(
    connection_id: int,
    table_name: str,
    user: dict = Depends(get_current_user),
):
    """Assess the impact of changing a specific table."""
    if not has_db_permission(user, connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required")
    
    db = SessionLocal()
    try:
        databases = db.query(Database).filter(Database.connection_id == connection_id).all()
        db_ids = [d.id for d in databases]
        
        # Direct FK dependents
        fks = db.query(ForeignKeyModel).filter(
            ForeignKeyModel.database_id.in_(db_ids),
            ForeignKeyModel.referenced_table == table_name,
        ).all()
        direct = list(set(fk.table_name for fk in fks))
        
        # Indirect dependents (follow FK chain)
        indirect = set()
        to_check = list(direct)
        checked = {table_name}
        while to_check:
            t = to_check.pop(0)
            if t in checked:
                continue
            checked.add(t)
            child_fks = db.query(ForeignKeyModel).filter(
                ForeignKeyModel.database_id.in_(db_ids),
                ForeignKeyModel.referenced_table == t,
            ).all()
            for cfk in child_fks:
                if cfk.table_name not in checked:
                    indirect.add(cfk.table_name)
                    to_check.append(cfk.table_name)
        indirect -= set(direct)
        
        # Affected saved queries
        all_saved = db.query(SavedQuery).filter(SavedQuery.connection_id == connection_id).all()
        affected_sq = sum(1 for sq in all_saved if table_name.lower() in (sq.sql or "").lower())
        
        # Affected dashboards
        from app.models import DashboardPin
        all_pins = db.query(DashboardPin).filter(DashboardPin.connection_id == connection_id).all()
        affected_dash = len(set(p.dashboard_id for p in all_pins if table_name.lower() in (p.sql or "").lower()))
        
        score = len(direct) * 3 + len(indirect) * 1 + affected_sq * 2 + affected_dash * 2
        
        return ImpactAssessment(
            table_name=table_name,
            direct_dependents=direct,
            indirect_dependents=list(indirect),
            affected_saved_queries=affected_sq,
            affected_dashboards=affected_dash,
            total_impact_score=score,
        )
    finally:
        db.close()
