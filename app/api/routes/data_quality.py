"""Data Quality API — scan tables for nulls, duplicates, anomalies, and freshness."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.database import SessionLocal
from app.models import Connection
from app.services.schema_service import SchemaExtractor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quality", tags=["Data Quality"])


class QualityScanRequest(BaseModel):
    connection_id: int
    table_name: str


@router.post("/scan")
async def scan_table_quality(req: QualityScanRequest, user: dict = Depends(get_current_user)):
    """Run a comprehensive data quality scan on a table."""
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == req.connection_id,
                                            Connection.is_active == True).first()
        if not conn:
            raise HTTPException(404, "Connection not found")

        from sqlalchemy import create_engine, text, inspect
        from sqlalchemy.pool import NullPool
        conn_str = SchemaExtractor.build_connection_string(
            conn.database_type, conn.host, conn.port,
            conn.username, conn.password, conn.database
        )
        engine = create_engine(conn_str, poolclass=NullPool, connect_args={"connect_timeout": 10} if conn.database_type.lower() in ("postgres", "postgresql") else {})

        report = {"table": req.table_name, "columns": [], "overall_score": 0,
                   "total_rows": 0, "issues": []}

        try:
            inspector = inspect(engine)
            columns = inspector.get_columns(req.table_name)

            with engine.connect() as c:
                row_count = c.execute(text(f'SELECT COUNT(*) FROM "{req.table_name}"')).scalar()
                report["total_rows"] = row_count

                if row_count == 0:
                    report["issues"].append({"severity": "warning", "message": "Table is empty"})
                    report["overall_score"] = 0
                    return report

                total_score = 0
                for col_info in columns:
                    col_name = col_info["name"]
                    col_report = {"name": col_name, "type": str(col_info["type"]),
                                   "nullable": col_info.get("nullable", True)}

                    null_count = c.execute(text(
                        f'SELECT COUNT(*) FROM "{req.table_name}" WHERE "{col_name}" IS NULL'
                    )).scalar()
                    col_report["null_count"] = null_count
                    col_report["null_pct"] = round(100 * null_count / row_count, 1) if row_count else 0
                    col_report["completeness"] = round(100 - col_report["null_pct"], 1)

                    try:
                        distinct = c.execute(text(
                            f'SELECT COUNT(DISTINCT "{col_name}") FROM "{req.table_name}" WHERE "{col_name}" IS NOT NULL'
                        )).scalar()
                        col_report["distinct_count"] = distinct
                        col_report["uniqueness"] = round(100 * distinct / (row_count - null_count), 1) if (row_count - null_count) > 0 else 0
                    except Exception:
                        col_report["distinct_count"] = None
                        col_report["uniqueness"] = None

                    col_score = col_report["completeness"]
                    if col_report["null_pct"] > 50:
                        report["issues"].append({
                            "severity": "warning",
                            "message": f"Column '{col_name}' is {col_report['null_pct']}% NULL",
                        })
                    if col_report.get("uniqueness") is not None and col_report["uniqueness"] < 5 and col_report["distinct_count"] and col_report["distinct_count"] < 3:
                        report["issues"].append({
                            "severity": "info",
                            "message": f"Column '{col_name}' has very low cardinality ({col_report['distinct_count']} distinct values)",
                        })

                    total_score += col_score
                    report["columns"].append(col_report)

                report["overall_score"] = round(total_score / len(columns), 1) if columns else 0
        finally:
            engine.dispose()

        return report
    except Exception as e:
        logger.error("Quality scan error: %s", e, exc_info=True)
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.get("/score/{connection_id}")
async def connection_quality_overview(connection_id: int, user: dict = Depends(get_current_user)):
    """Get a quick quality overview for all tables in a connection."""
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == connection_id,
                                            Connection.is_active == True).first()
        if not conn:
            raise HTTPException(404, "Connection not found")

        from sqlalchemy import create_engine, text, inspect
        from sqlalchemy.pool import NullPool
        conn_str = SchemaExtractor.build_connection_string(
            conn.database_type, conn.host, conn.port,
            conn.username, conn.password, conn.database
        )
        engine = create_engine(conn_str, poolclass=NullPool, connect_args={"connect_timeout": 10} if conn.database_type.lower() in ("postgres", "postgresql") else {})
        try:
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            overview = []
            with engine.connect() as c:
                for tname in tables:
                    if tname.startswith("pg_"):
                        continue
                    try:
                        row_count = c.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar()
                        cols = inspector.get_columns(tname)
                        null_cols = 0
                        for col in cols:
                            nn = c.execute(text(f'SELECT COUNT(*) FROM "{tname}" WHERE "{col["name"]}" IS NULL')).scalar()
                            if nn and row_count and nn / row_count > 0.5:
                                null_cols += 1
                        score = round(100 * (1 - null_cols / len(cols)), 1) if cols else 100
                        overview.append({"table": tname, "row_count": row_count,
                                          "column_count": len(cols), "quality_score": score,
                                          "high_null_columns": null_cols})
                    except Exception:
                        continue
            return overview
        finally:
            engine.dispose()
    finally:
        db.close()
