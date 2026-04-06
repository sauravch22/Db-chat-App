"""NoSQL database API — connect, explore schema, and execute queries
for MongoDB, Redis, Elasticsearch, and Neo4j."""

import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import Connection
from app.services.nosql_service import get_nosql_handler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nosql", tags=["NoSQL"])

NOSQL_TYPES = [
    {"id": "mongodb", "name": "MongoDB", "default_port": 27017,
     "uri_template": "mongodb://{username}:{password}@{host}:{port}/{database}"},
    {"id": "redis", "name": "Redis", "default_port": 6379,
     "uri_template": "redis://{username}:{password}@{host}:{port}/0"},
    {"id": "elasticsearch", "name": "Elasticsearch", "default_port": 9200,
     "uri_template": "http://{host}:{port}"},
    {"id": "neo4j", "name": "Neo4j", "default_port": 7687,
     "uri_template": "bolt://{host}:{port}"},
]


@router.get("/types")
async def list_nosql_types(user: dict = Depends(get_current_user)):
    return NOSQL_TYPES


def _build_uri(conn) -> str:
    dt = conn.database_type.lower()
    for t in NOSQL_TYPES:
        if t["id"] == dt:
            return t["uri_template"].format(
                username=conn.username or "",
                password=conn.password or "",
                host=conn.host,
                port=conn.port,
                database=conn.database or "",
            )
    return f"{conn.host}:{conn.port}"


@router.get("/schema/{connection_id}")
async def nosql_schema(connection_id: int, user: dict = Depends(get_current_user)):
    if not has_db_permission(user, connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required on this database")
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == connection_id,
                                            Connection.is_active == True).first()
        if not conn:
            raise HTTPException(404, "Connection not found")
        handler = get_nosql_handler(conn.database_type, uri=_build_uri(conn),
                                     database=conn.database, url=_build_uri(conn),
                                     username=conn.username, password=conn.password)
        schema = handler.extract_schema()
        return schema
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("NoSQL schema error: %s", e, exc_info=True)
        raise HTTPException(500, str(e))
    finally:
        db.close()


class NoSQLQueryRequest(BaseModel):
    connection_id: int
    query: str
    collection: Optional[str] = None
    index: Optional[str] = None


@router.post("/execute")
async def nosql_execute(request: NoSQLQueryRequest, user: dict = Depends(get_current_user)):
    if not has_db_permission(user, request.connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required on this database")
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == request.connection_id,
                                            Connection.is_active == True).first()
        if not conn:
            raise HTTPException(404, "Connection not found")
        dt = conn.database_type.lower()
        handler = get_nosql_handler(dt, uri=_build_uri(conn), database=conn.database,
                                     url=_build_uri(conn), username=conn.username,
                                     password=conn.password)

        if dt in ("mongodb", "mongo"):
            query_parsed = json.loads(request.query)
            coll = request.collection or query_parsed.get("collection", "")
            pipeline = query_parsed.get("pipeline")
            if pipeline:
                result = handler.execute_pipeline(coll, pipeline)
            else:
                result = handler.execute_find(coll, query_parsed.get("filter", {}),
                                               query_parsed.get("projection"),
                                               query_parsed.get("limit", 100))
        elif dt == "redis":
            result = handler.execute_command(request.query)
        elif dt in ("elasticsearch", "elastic", "es"):
            query_parsed = json.loads(request.query)
            idx = request.index or query_parsed.get("index", "_all")
            body = query_parsed.get("body", query_parsed)
            result = handler.execute_query(idx, body)
        elif dt == "neo4j":
            result = handler.execute_cypher(request.query)
        else:
            raise HTTPException(400, f"Unsupported NoSQL type: {dt}")
        return result
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON query")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("NoSQL execute error: %s", e, exc_info=True)
        raise HTTPException(500, str(e))
    finally:
        db.close()
