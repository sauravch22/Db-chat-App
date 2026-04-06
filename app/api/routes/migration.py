"""NL to Schema Migration API — generate ALTER TABLE / CREATE TABLE from natural language."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.api.deps import get_current_user
from app.database import SessionLocal
from app.models import Connection
from app.services.ollama_service import OllamaService
from app.services.metadata_service import MetadataService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/migration", tags=["Schema Migration"])


class MigrationRequest(BaseModel):
    connection_id: int
    description: str
    dry_run: bool = True


@router.post("/generate")
async def generate_migration(req: MigrationRequest, user: dict = Depends(get_current_user)):
    """Generate SQL migration from natural language description."""
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == req.connection_id,
                                            Connection.is_active == True).first()
        if not conn:
            raise HTTPException(404, "Connection not found")

        meta = MetadataService()
        schema_ctx = meta.get_column_schema(req.connection_id, [])
        meta.close()

        svc = OllamaService()
        dialect = conn.database_type.lower()
        dialect_map = {"postgres": "PostgreSQL", "postgresql": "PostgreSQL",
                        "mysql": "MySQL", "sqlite": "SQLite", "duckdb": "DuckDB",
                        "sqlserver": "SQL Server", "mssql": "SQL Server"}
        dialect_name = dialect_map.get(dialect, "PostgreSQL")

        system = f"""You are a {dialect_name} schema migration expert.
Given the current schema and a natural language description of the desired change,
generate the appropriate SQL DDL statements (ALTER TABLE, CREATE TABLE, etc.).

Rules:
1. Output ONLY the SQL DDL statements — no explanation
2. Use {dialect_name} syntax
3. Include IF NOT EXISTS / IF EXISTS where appropriate
4. If adding columns, provide sensible defaults
5. If creating indexes, use appropriate index types
6. Wrap in a transaction if multiple statements
7. Add a comment at the top describing what the migration does"""

        prompt = f"""Current schema:
{schema_ctx or "(No schema indexed yet — generate CREATE TABLE statements)"}

Requested change: {req.description}

SQL migration:"""

        migration_sql = await svc._call_chat_completions(system, prompt, max_tokens=1024)

        result = {
            "description": req.description,
            "dialect": dialect_name,
            "migration_sql": migration_sql,
            "dry_run": req.dry_run,
            "executed": False,
        }

        if not req.dry_run:
            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import NullPool
            from app.services.schema_service import SchemaExtractor
            conn_str = SchemaExtractor.build_connection_string(
                conn.database_type, conn.host, conn.port,
                conn.username, conn.password, conn.database
            )
            engine = create_engine(conn_str, poolclass=NullPool)
            try:
                with engine.connect() as c:
                    for stmt in migration_sql.split(";"):
                        stmt = stmt.strip()
                        if stmt and not stmt.startswith("--"):
                            c.execute(text(stmt))
                    c.commit()
                result["executed"] = True
                result["message"] = "Migration executed successfully"
            except Exception as e:
                result["executed"] = False
                result["error"] = str(e)
            finally:
                engine.dispose()

        return result
    except Exception as e:
        logger.error("Migration error: %s", e, exc_info=True)
        raise HTTPException(500, str(e))
    finally:
        db.close()
