"""Data Pipeline API — basic ETL between database connections."""

import json
import logging
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from app.api.deps import get_current_user
from app.database import SessionLocal
from app.models import Connection
from app.services.schema_service import SchemaExtractor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["Data Pipeline"])


class PipelineStep(BaseModel):
    type: str  # extract | transform | load
    connection_id: Optional[int] = None
    sql: Optional[str] = None
    target_table: Optional[str] = None
    transform_expression: Optional[str] = None


class PipelineRequest(BaseModel):
    name: str
    source_connection_id: int
    target_connection_id: int
    extract_sql: str
    target_table: str
    create_table: bool = True
    mode: str = "replace"  # replace | append


@router.post("/execute")
async def execute_pipeline(req: PipelineRequest, user: dict = Depends(get_current_user)):
    """Execute a simple ETL pipeline: extract from source, load into target."""
    db = SessionLocal()
    try:
        source = db.query(Connection).filter(Connection.id == req.source_connection_id, Connection.is_active == True).first()
        target = db.query(Connection).filter(Connection.id == req.target_connection_id, Connection.is_active == True).first()
        if not source or not target:
            raise HTTPException(404, "Source or target connection not found")

        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        t0 = time.time()

        src_str = SchemaExtractor.build_connection_string(source.database_type, source.host, source.port, source.username, source.password, source.database)
        tgt_str = SchemaExtractor.build_connection_string(target.database_type, target.host, target.port, target.username, target.password, target.database)

        src_engine = create_engine(src_str, poolclass=NullPool)
        tgt_engine = create_engine(tgt_str, poolclass=NullPool)

        try:
            with src_engine.connect() as src_conn:
                result = src_conn.execute(text(req.extract_sql))
                columns = list(result.keys())
                rows = result.fetchall()

            if not rows:
                return {"success": True, "rows_transferred": 0, "message": "No rows to transfer", "elapsed_ms": int((time.time() - t0) * 1000)}

            import pandas as pd
            df = pd.DataFrame(rows, columns=columns)

            if req.mode == "replace":
                df.to_sql(req.target_table, tgt_engine, if_exists="replace", index=False)
            else:
                df.to_sql(req.target_table, tgt_engine, if_exists="append", index=False)

            elapsed = int((time.time() - t0) * 1000)
            return {"success": True, "rows_transferred": len(df), "columns": columns,
                    "target_table": req.target_table, "mode": req.mode, "elapsed_ms": elapsed}
        finally:
            src_engine.dispose()
            tgt_engine.dispose()
    except Exception as e:
        logger.error("Pipeline error: %s", e, exc_info=True)
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.get("/preview")
async def preview_pipeline(connection_id: int, sql: str, limit: int = 10,
                             user: dict = Depends(get_current_user)):
    """Preview source data before running a pipeline."""
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == connection_id, Connection.is_active == True).first()
        if not conn:
            raise HTTPException(404, "Connection not found")
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool
        conn_str = SchemaExtractor.build_connection_string(conn.database_type, conn.host, conn.port, conn.username, conn.password, conn.database)
        engine = create_engine(conn_str, poolclass=NullPool)
        try:
            with engine.connect() as c:
                r = c.execute(text(f"SELECT * FROM ({sql}) AS preview LIMIT {limit}"))
                cols = list(r.keys())
                rows = [dict(zip(cols, row)) for row in r.fetchall()]
                return {"columns": cols, "rows": rows, "row_count": len(rows)}
        finally:
            engine.dispose()
    finally:
        db.close()
