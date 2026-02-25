"""Admin API endpoints"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
import logging
from datetime import datetime
from cryptography.fernet import Fernet

from app.database import get_db
from app.models import Connection, Database
from app.services.schema_service import SchemaExtractor
from app.services.indexing_service import IndexingService
from app.services.ollama_service import OllamaService
from app.services.vector_service import VectorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _extract_and_index_database(
    connection_id: int,
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
    db_type: str
):
    """Background task to extract schema and index database"""
    try:
        logger.info(f"Starting schema extraction for connection {connection_id}")
        
        # Extract schema
        schema_data = await SchemaExtractor.extract_schema(
            db_type=db_type,
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            timeout=10
        )
        
        logger.info(f"Schema extracted: {len(schema_data.get('tables', []))} tables")
        
        # Index the schema
        ollama_service = OllamaService()
        vector_service = VectorService()
        indexing_service = IndexingService(ollama_service, vector_service)
        
        result = await indexing_service.index_schema(
            connection_id=connection_id,
            database_name=database,
            schema_data=schema_data,
            db_type=db_type,
            host=host,
            port=port,
            username=username,
            password=password
        )
        
        logger.info(f"Indexing completed: {result}")
        
    except Exception as e:
        logger.error(f"Background task failed for connection {connection_id}: {str(e)}")


class RegisterDBRequest(BaseModel):
    """Register database request"""
    name: str
    host: str
    port: int
    username: str
    password: str
    database: str
    database_type: str = "postgres"  # postgres, mysql, sqlserver


class RegisterDBResponse(BaseModel):
    """Register database response"""
    id: int
    name: str
    status: str
    indexing_scheduled: bool


class ConnectionInfo(BaseModel):
    """Connection info"""
    id: int
    name: str
    host: str
    port: int
    is_active: bool
    
    class Config:
        from_attributes = True


@router.post("/register-db", response_model=RegisterDBResponse)
async def register_database(
    request: RegisterDBRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Register a new database for chatbot context"""
    
    try:
        logger.info(f"Registering database: {request.name}")
        
        # Create connection record
        connection = Connection(
            name=request.name,
            host=request.host,
            port=request.port,
            username=request.username,
            password=request.password,  # TODO: Encrypt password
            database=request.database,
            database_type=request.database_type,
            is_active=True,
            created_at=datetime.utcnow()
        )
        db.add(connection)
        db.flush()
        
        logger.info(f"Created connection record with ID {connection.id}")
        db.commit()
        
        # Schedule schema extraction and indexing as background task
        background_tasks.add_task(
            _extract_and_index_database,
            connection.id,
            request.host,
            request.port,
            request.username,
            request.password,
            request.database,
            request.database_type
        )
        
        return RegisterDBResponse(
            id=connection.id,
            name=request.name,
            status="registered",
            indexing_scheduled=True
        )
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error registering database: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/databases", response_model=List[ConnectionInfo])
async def list_databases(db: Session = Depends(get_db)):
    """List all registered databases"""
    
    try:
        connections = db.query(Connection).filter(Connection.is_active == True).all()
        return connections
    
    except Exception as e:
        logger.error(f"Error listing databases: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reindex/{connection_id}")
async def trigger_reindex(
    connection_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Manually trigger context reindexing"""
    
    try:
        # Get connection
        connection = db.query(Connection).filter(Connection.id == connection_id).first()
        if not connection:
            raise HTTPException(status_code=404, detail="Connection not found")
        
        # Schedule reindexing
        background_tasks.add_task(
            _extract_and_index_database,
            connection.id,
            connection.host,
            connection.port,
            connection.username,
            connection.password,
            connection.database,
            connection.database_type
        )
        
        return {
            "status": "indexing_started",
            "connection_id": connection_id,
            "estimated_duration_seconds": 30
        }
    
    except Exception as e:
        logger.error(f"Error triggering reindex: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/audit")
async def query_audit_log(
    connection_id: int,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Get query audit log"""
    
    try:
        from app.models import Query
        
        # Fetch query audit logs
        queries = db.query(Query).filter(
            Query.connection_id == connection_id
        ).order_by(Query.created_at.desc()).limit(limit).all()
        
        return {
            "connection_id": connection_id,
            "queries": [
                {
                    "id": q.id,
                    "prompt": q.prompt,
                    "generated_sql": q.generated_sql,
                    "execution_time_ms": q.execution_time_ms,
                    "error": q.error,
                    "created_at": q.created_at.isoformat()
                }
                for q in queries
            ],
            "total": len(queries)
        }
    
    except Exception as e:
        logger.error(f"Error fetching audit log: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
