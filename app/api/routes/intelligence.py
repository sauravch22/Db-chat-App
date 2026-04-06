"""Connection Intelligence API – DB stats, performance monitoring, and recommendations."""

import time
import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import Connection, Database, Table, Column, Query, ChatHistory
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/intelligence", tags=["Connection Intelligence"])


class TableSize(BaseModel):
    table_name: str
    estimated_rows: Optional[int] = None
    total_size: Optional[str] = None
    index_size: Optional[str] = None


class ActiveQuery(BaseModel):
    pid: Optional[int] = None
    state: Optional[str] = None
    query: Optional[str] = None
    duration: Optional[str] = None
    username: Optional[str] = None


class IndexRecommendation(BaseModel):
    table_name: str
    column_name: str
    reason: str
    estimated_benefit: str


class ConnectionStats(BaseModel):
    connection_id: int
    database_name: str
    database_type: str
    total_tables: int = 0
    total_columns: int = 0
    total_queries_run: int = 0
    avg_query_time_ms: Optional[float] = None
    table_sizes: List[TableSize] = []
    active_queries: List[ActiveQuery] = []
    index_recommendations: List[IndexRecommendation] = []
    db_version: Optional[str] = None
    db_size: Optional[str] = None
    uptime: Optional[str] = None
    connection_count: Optional[int] = None


@router.get("/{connection_id}", response_model=ConnectionStats)
async def get_connection_stats(
    connection_id: int,
    user: dict = Depends(get_current_user),
):
    """Get comprehensive stats and intelligence for a database connection."""
    if not has_db_permission(user, connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required")
    
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == connection_id).first()
        if not conn:
            raise HTTPException(404, "Connection not found")
        
        databases = db.query(Database).filter(Database.connection_id == connection_id).all()
        db_ids = [d.id for d in databases]
        db_name = databases[0].name if databases else conn.database
        
        tables = db.query(Table).filter(Table.database_id.in_(db_ids)).all() if db_ids else []
        total_cols = sum(len(t.columns) for t in tables)
        
        # Query stats from chat history
        from sqlalchemy import func
        query_stats = db.query(
            func.count(ChatHistory.id),
            func.avg(ChatHistory.execution_time_ms),
        ).filter(
            ChatHistory.connection_id == connection_id,
            ChatHistory.status == "success",
        ).first()
        
        total_queries = query_stats[0] or 0
        avg_time = float(query_stats[1]) if query_stats[1] else None
        
        # Live stats from the actual database
        table_sizes = []
        active_queries = []
        db_version = None
        db_size = None
        connection_count = None
        
        db_type = conn.database_type.lower()
        if db_type in ("postgres", "postgresql"):
            chat_service = ChatService()
            try:
                # Table sizes
                size_result = await chat_service.execute_query(
                    connection_id=connection_id,
                    sql="""SELECT schemaname || '.' || tablename AS table_name,
                           pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS total_size,
                           pg_size_pretty(pg_indexes_size(schemaname || '.' || tablename)) AS index_size,
                           (SELECT reltuples::bigint FROM pg_class WHERE oid = (schemaname || '.' || tablename)::regclass) AS est_rows
                    FROM pg_tables WHERE schemaname = 'public' ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC LIMIT 20""",
                    timeout=10,
                )
                if size_result.get("success"):
                    for row in (size_result.get("rows") or []):
                        table_sizes.append(TableSize(
                            table_name=row.get("table_name", ""),
                            estimated_rows=int(row["est_rows"]) if row.get("est_rows") else None,
                            total_size=row.get("total_size"),
                            index_size=row.get("index_size"),
                        ))
                
                # Active queries
                aq_result = await chat_service.execute_query(
                    connection_id=connection_id,
                    sql="""SELECT pid, state, left(query, 200) as query, 
                           age(now(), query_start)::text as duration, usename as username
                    FROM pg_stat_activity WHERE state != 'idle' AND pid != pg_backend_pid()
                    ORDER BY query_start LIMIT 20""",
                    timeout=5,
                )
                if aq_result.get("success"):
                    for row in (aq_result.get("rows") or []):
                        active_queries.append(ActiveQuery(
                            pid=row.get("pid"),
                            state=row.get("state"),
                            query=row.get("query"),
                            duration=row.get("duration"),
                            username=row.get("username"),
                        ))
                
                # DB version and size
                ver_result = await chat_service.execute_query(
                    connection_id=connection_id, sql="SELECT version()", timeout=5)
                if ver_result.get("success") and ver_result.get("rows"):
                    db_version = str(ver_result["rows"][0].get("version", ""))[:100]
                
                size_q = await chat_service.execute_query(
                    connection_id=connection_id,
                    sql=f"SELECT pg_size_pretty(pg_database_size(current_database())) as db_size",
                    timeout=5)
                if size_q.get("success") and size_q.get("rows"):
                    db_size = size_q["rows"][0].get("db_size")
                
                conn_q = await chat_service.execute_query(
                    connection_id=connection_id,
                    sql="SELECT count(*) as cnt FROM pg_stat_activity",
                    timeout=5)
                if conn_q.get("success") and conn_q.get("rows"):
                    connection_count = conn_q["rows"][0].get("cnt")
            except Exception as e:
                logger.warning(f"Failed to get live stats: {e}")
            finally:
                chat_service.close()
        
        # Generate index recommendations based on query patterns
        recommendations = _generate_index_recommendations(db, connection_id, tables)
        
        return ConnectionStats(
            connection_id=connection_id,
            database_name=db_name,
            database_type=conn.database_type,
            total_tables=len(tables),
            total_columns=total_cols,
            total_queries_run=total_queries,
            avg_query_time_ms=round(avg_time, 1) if avg_time else None,
            table_sizes=table_sizes,
            active_queries=active_queries,
            index_recommendations=recommendations,
            db_version=db_version,
            db_size=db_size,
            connection_count=connection_count,
        )
    finally:
        db.close()


def _generate_index_recommendations(db, connection_id: int, tables: list) -> List[IndexRecommendation]:
    """Analyze query patterns to suggest indexes."""
    recs = []
    
    histories = (
        db.query(ChatHistory.sql)
        .filter(
            ChatHistory.connection_id == connection_id,
            ChatHistory.status == "success",
            ChatHistory.sql.isnot(None),
        )
        .order_by(ChatHistory.created_at.desc())
        .limit(100)
        .all()
    )
    
    import re
    where_cols = {}
    join_cols = {}
    
    for (sql,) in histories:
        if not sql:
            continue
        sql_lower = sql.lower()
        
        where_matches = re.findall(r'where\s+.*?(\w+)\s*[=<>]', sql_lower)
        for col in where_matches:
            where_cols[col] = where_cols.get(col, 0) + 1
        
        join_matches = re.findall(r'join\s+\w+\s+\w*\s*on\s+.*?(\w+)\.(\w+)\s*=', sql_lower)
        for _, col in join_matches:
            join_cols[col] = join_cols.get(col, 0) + 1
    
    table_col_names = set()
    for t in tables:
        for c in t.columns:
            table_col_names.add(c.name.lower())
    
    for col, count in sorted(where_cols.items(), key=lambda x: -x[1])[:5]:
        if col in table_col_names and count >= 3:
            recs.append(IndexRecommendation(
                table_name="(multiple)",
                column_name=col,
                reason=f"Frequently used in WHERE clauses ({count} times)",
                estimated_benefit="Faster filtered queries",
            ))
    
    for col, count in sorted(join_cols.items(), key=lambda x: -x[1])[:3]:
        if col in table_col_names and count >= 2:
            recs.append(IndexRecommendation(
                table_name="(multiple)",
                column_name=col,
                reason=f"Frequently used in JOIN conditions ({count} times)",
                estimated_benefit="Faster join operations",
            ))
    
    return recs[:8]
