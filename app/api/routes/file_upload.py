"""File upload API — CSV, Excel, Parquet files loaded into DuckDB for querying."""

import logging
import os
import tempfile
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from typing import Optional

from app.api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["File Upload"])

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "dbchat_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

_duckdb_connections = {}


def _get_duck(session_id: str):
    import duckdb
    if session_id not in _duckdb_connections:
        db_path = os.path.join(UPLOAD_DIR, f"{session_id}.duckdb")
        _duckdb_connections[session_id] = duckdb.connect(db_path)
    return _duckdb_connections[session_id]


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    table_name: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Upload CSV/Excel/Parquet and load into an in-memory DuckDB for querying."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("csv", "tsv", "xlsx", "xls", "parquet", "json", "jsonl"):
        raise HTTPException(400, f"Unsupported file type: .{ext}. Use CSV, Excel, Parquet, or JSON.")

    session_id = str(user.get("sub", "default"))
    tname = table_name or file.filename.rsplit(".", 1)[0].replace(" ", "_").replace("-", "_")
    tname = "".join(c if c.isalnum() or c == "_" else "_" for c in tname)[:60]

    file_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}_{file.filename}")
    try:
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        duck = _get_duck(session_id)

        if ext == "csv" or ext == "tsv":
            duck.execute(f"CREATE OR REPLACE TABLE \"{tname}\" AS SELECT * FROM read_csv_auto('{file_path}')")
        elif ext in ("xlsx", "xls"):
            duck.execute("INSTALL spatial; LOAD spatial;")
            duck.execute(f"CREATE OR REPLACE TABLE \"{tname}\" AS SELECT * FROM st_read('{file_path}')")
        elif ext == "parquet":
            duck.execute(f"CREATE OR REPLACE TABLE \"{tname}\" AS SELECT * FROM read_parquet('{file_path}')")
        elif ext in ("json", "jsonl"):
            duck.execute(f"CREATE OR REPLACE TABLE \"{tname}\" AS SELECT * FROM read_json_auto('{file_path}')")

        count = duck.execute(f"SELECT COUNT(*) FROM \"{tname}\"").fetchone()[0]
        cols = [desc[0] for desc in duck.execute(f"SELECT * FROM \"{tname}\" LIMIT 0").description]

        return {
            "success": True,
            "table_name": tname,
            "row_count": count,
            "columns": cols,
            "session_id": session_id,
            "message": f"Loaded {count} rows into table '{tname}'",
        }
    except Exception as e:
        logger.error("File upload failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


@router.get("/tables")
async def list_uploaded_tables(user: dict = Depends(get_current_user)):
    session_id = str(user.get("sub", "default"))
    try:
        duck = _get_duck(session_id)
        tables = duck.execute("SHOW TABLES").fetchall()
        result = []
        for (tname,) in tables:
            count = duck.execute(f"SELECT COUNT(*) FROM \"{tname}\"").fetchone()[0]
            cols = [desc[0] for desc in duck.execute(f"SELECT * FROM \"{tname}\" LIMIT 0").description]
            result.append({"name": tname, "row_count": count, "columns": cols})
        return result
    except Exception:
        return []


@router.post("/query")
async def query_uploaded(
    sql: str,
    user: dict = Depends(get_current_user),
):
    """Execute SQL against uploaded file data."""
    session_id = str(user.get("sub", "default"))
    try:
        duck = _get_duck(session_id)
        result = duck.execute(sql)
        cols = [desc[0] for desc in result.description] if result.description else []
        rows = result.fetchall()
        rows_dicts = [dict(zip(cols, row)) for row in rows]
        return {"success": True, "columns": cols, "rows": rows_dicts[:500],
                "row_count": len(rows_dicts)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.delete("/table/{table_name}")
async def drop_uploaded_table(table_name: str, user: dict = Depends(get_current_user)):
    session_id = str(user.get("sub", "default"))
    try:
        duck = _get_duck(session_id)
        duck.execute(f"DROP TABLE IF EXISTS \"{table_name}\"")
        return {"deleted": True}
    except Exception as e:
        return {"deleted": False, "error": str(e)}
