"""Connection testing API — verify database connectivity before registration."""

import logging
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.api.deps import get_current_user
from app.services.schema_service import SchemaExtractor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/connection", tags=["Connection"])

NOSQL_TYPES = {"mongodb", "mongo", "redis", "elasticsearch", "elastic", "es", "neo4j"}


class TestConnectionRequest(BaseModel):
    database_type: str
    host: str
    port: int
    username: Optional[str] = ""
    password: Optional[str] = ""
    database: Optional[str] = ""


@router.post("/test")
async def test_connection(req: TestConnectionRequest, user: dict = Depends(get_current_user)):
    """Test a database connection without registering it."""
    dt = req.database_type.lower()

    if dt in NOSQL_TYPES:
        from app.services.nosql_service import get_nosql_handler, MongoHandler
        nosql_types_map = {
            "mongodb": "mongodb", "mongo": "mongodb",
            "redis": "redis",
            "elasticsearch": "elasticsearch", "elastic": "elasticsearch", "es": "elasticsearch",
            "neo4j": "neo4j",
        }
        uri_templates = {
            "mongodb": f"mongodb://{req.username}:{req.password}@{req.host}:{req.port}/{req.database}",
            "redis": f"redis://{req.host}:{req.port}/0" if not req.password else f"redis://:{req.password}@{req.host}:{req.port}/0",
            "elasticsearch": f"http://{req.host}:{req.port}",
            "neo4j": f"bolt://{req.host}:{req.port}",
        }
        ntype = nosql_types_map.get(dt, dt)
        uri = uri_templates.get(ntype, "")
        try:
            handler = get_nosql_handler(ntype, uri=uri, database=req.database, url=uri,
                                         username=req.username, password=req.password)
            result = handler.test_connection()
            return {"success": result.get("ok", False), "message": "Connection successful" if result.get("ok") else result.get("error", "Failed"),
                    "details": result}
        except Exception as e:
            return {"success": False, "message": str(e)}
    else:
        try:
            conn_str = SchemaExtractor.build_connection_string(
                dt, req.host, req.port, req.username, req.password, req.database
            )
            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import NullPool
            engine = create_engine(conn_str, poolclass=NullPool, connect_args={"connect_timeout": 5} if dt in ("postgres", "postgresql") else {})
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return {"success": True, "message": "Connection successful"}
        except Exception as e:
            return {"success": False, "message": str(e)}
