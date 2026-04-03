"""Admin API endpoints"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import logging
from datetime import datetime
from cryptography.fernet import Fernet

from app.database import get_db
from app.models import Connection, Database, Table, Column
from app.services.schema_service import SchemaExtractor
from app.services.indexing_service import IndexingService
from app.services.ollama_service import OllamaService
from app.services.vector_service import VectorService
from app.services.activity_service import log_activity, Actions
from app.api.deps import get_current_user, has_db_permission, has_any_onboard

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
    req: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Register a new database for chatbot context"""
    if not has_any_onboard(user):
        await log_activity(req, user=user, action=Actions.PERM_DENIED, status="denied",
                           detail={"attempted": "register_db", "db_name": request.name}, db=db)
        raise HTTPException(status_code=403, detail="You must be an admin of at least one database to register new ones")
    
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
        
        # Auto-assign creator as admin of the new database
        from app.services.auth_service import grant_all_on_connection
        grant_all_on_connection(db, int(user["sub"]), connection.id)
        logger.info(f"User '{user['username']}' auto-assigned as admin of connection {connection.id}")
        
        await log_activity(req, user=user, action=Actions.REGISTER_DB,
                           connection_id=connection.id, resource_type="connection",
                           resource_id=connection.id,
                           detail={"name": request.name, "host": request.host,
                                   "database": request.database, "type": request.database_type}, db=db)

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
async def list_databases(
    req: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List databases the current user has access to"""
    
    try:
        perms = user.get("perms", {})
        is_global_admin = "db_onboard" in perms.get("*", [])
        
        if is_global_admin:
            connections = db.query(Connection).filter(Connection.is_active == True).all()
        else:
            conn_ids = [int(k) for k in perms.keys() if k != "*" and perms[k]]
            if not conn_ids:
                return []
            connections = db.query(Connection).filter(
                Connection.is_active == True, Connection.id.in_(conn_ids)
            ).all()
        await log_activity(req, user=user, action=Actions.LIST_DATABASES,
                           detail={"count": len(connections)}, db=db)
        return connections
    
    except Exception as e:
        logger.error(f"Error listing databases: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reindex/{connection_id}")
async def trigger_reindex(
    connection_id: int,
    req: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Manually trigger context reindexing"""
    if not has_db_permission(user, connection_id, "db_reindex"):
        await log_activity(req, user=user, action=Actions.PERM_DENIED,
                           connection_id=connection_id, status="denied",
                           detail={"attempted": "reindex"}, db=db)
        raise HTTPException(status_code=403, detail="Permission 'db_reindex' required on this database")
    
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
        
        await log_activity(req, user=user, action=Actions.REINDEX,
                           connection_id=connection_id, resource_type="connection",
                           resource_id=connection_id, db=db)

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
    req: Request,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get query audit log"""
    if not has_db_permission(user, connection_id, "prompt_query"):
        await log_activity(req, user=user, action=Actions.PERM_DENIED,
                           connection_id=connection_id, status="denied",
                           detail={"attempted": "view_audit"}, db=db)
        raise HTTPException(status_code=403, detail="Permission required on this database")
    
    try:
        from app.models import Query
        
        # Fetch query audit logs
        queries = db.query(Query).filter(
            Query.connection_id == connection_id
        ).order_by(Query.created_at.desc()).limit(limit).all()
        
        await log_activity(req, user=user, action=Actions.VIEW_AUDIT,
                           connection_id=connection_id, db=db)

        return {
            "connection_id": connection_id,
            "queries": [
                {
                    "id": q.id,
                    "prompt": q.user_prompt,
                    "generated_sql": q.generated_sql,
                    "status": q.result_status,
                    "error": q.error_message,
                    "execution_time_ms": q.execution_time_ms,
                    "created_at": q.created_at.isoformat()
                }
                for q in queries
            ],
            "total": len(queries)
        }
    
    except Exception as e:
        logger.error(f"Error fetching audit log: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# v2 ADMIN ENDPOINTS: Summary Management & Data Embedding Refresh
# ============================================================================

class TableSummaryResponse(BaseModel):
    """Table summary response"""
    table_id: int
    table_name: str
    summary: Optional[str]
    summary_generated_at: Optional[str]
    summary_human_override: bool
    column_count: int
    row_count: Optional[int]


class SummaryListResponse(BaseModel):
    """List of table summaries"""
    connection_id: int
    database_name: str
    summaries: List[TableSummaryResponse]
    total: int


class UpdateSummaryRequest(BaseModel):
    """Update table summary request"""
    summary: str
    is_human_override: bool = True


class RefreshDataEmbeddingsRequest(BaseModel):
    """Trigger data embedding refresh"""
    refresh_mode: str = "full"  # full, incremental, column-list
    column_list: Optional[List[int]] = None  # Only for column-list mode
    dry_run: bool = False


@router.get("/summaries/{connection_id}", response_model=SummaryListResponse)
async def get_table_summaries(
    connection_id: int,
    req: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get all table summaries for a connection"""
    if not has_db_permission(user, connection_id, "prompt_query"):
        await log_activity(req, user=user, action=Actions.PERM_DENIED,
                           connection_id=connection_id, status="denied",
                           detail={"attempted": "view_summaries"}, db=db)
        raise HTTPException(status_code=403, detail="Permission required on this database")
    
    try:
        # Verify connection exists
        connection = db.query(Connection).filter(Connection.id == connection_id).first()
        if not connection:
            raise HTTPException(status_code=404, detail="Connection not found")
        
        # Get all databases for this connection
        databases = db.query(Database).filter(Database.connection_id == connection_id).all()
        if not databases:
            return SummaryListResponse(
                connection_id=connection_id,
                database_name="",
                summaries=[],
                total=0
            )
        
        # Get all tables (typically one database per connection in this system)
        db_name = databases[0].name if databases else ""
        tables = db.query(Table).filter(Table.database_id.in_([d.id for d in databases])).all()
        
        summaries = []
        for table in tables:
            summaries.append(TableSummaryResponse(
                table_id=table.id,
                table_name=table.name,
                summary=table.summary,
                summary_generated_at=table.summary_generated_at.isoformat() if table.summary_generated_at else None,
                summary_human_override=table.summary_human_override,
                column_count=len(table.columns),
                row_count=table.sample_count
            ))
        
        await log_activity(req, user=user, action=Actions.VIEW_SUMMARIES,
                           connection_id=connection_id, detail={"table_count": len(summaries)}, db=db)

        return SummaryListResponse(
            connection_id=connection_id,
            database_name=db_name,
            summaries=summaries,
            total=len(summaries)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching table summaries: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/summaries/{table_id}")
async def update_table_summary(
    table_id: int,
    request: UpdateSummaryRequest,
    req: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Update a table summary (human override)"""
    
    try:
        table = db.query(Table).filter(Table.id == table_id).first()
        if not table:
            raise HTTPException(status_code=404, detail="Table not found")
        
        # Resolve connection_id via table → database → connection
        database_obj = db.query(Database).filter(Database.id == table.database_id).first()
        if not database_obj or not has_db_permission(user, database_obj.connection_id, "db_reindex"):
            raise HTTPException(status_code=403, detail="Permission 'db_reindex' required on this database")
        
        # Update summary fields
        table.summary = request.summary
        table.summary_human_override = request.is_human_override
        table.summary_generated_at = datetime.utcnow()
        table.updated_at = datetime.utcnow()
        
        db.commit()
        
        logger.info(f"Updated summary for table {table_id} (override={request.is_human_override})")
        
        await log_activity(req, user=user, action=Actions.UPDATE_SUMMARY,
                           connection_id=database_obj.connection_id,
                           resource_type="table", resource_id=table_id,
                           detail={"table_name": table.name, "override": request.is_human_override}, db=db)

        return {
            "success": True,
            "table_id": table_id,
            "table_name": table.name,
            "summary": table.summary,
            "human_override": table.summary_human_override,
            "updated_at": table.updated_at.isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating table summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _refresh_data_embeddings_task(
    connection_id: int,
    refresh_mode: str = "full",
    column_list: Optional[List[int]] = None
):
    """Background task to refresh data variation embeddings"""
    try:
        from app.services.indexing_service import IndexingService
        from app.services.ollama_service import OllamaService
        from app.services.vector_service import VectorService
        
        logger.info(f"Starting data embedding refresh for connection {connection_id} (mode={refresh_mode})")
        
        # Initialize services
        ollama_service = OllamaService()
        vector_service = VectorService()
        indexing_service = IndexingService(ollama_service, vector_service)
        
        # Get connection and databases
        from app.database import SessionLocal
        db = SessionLocal()
        
        try:
            connection = db.query(Connection).filter(Connection.id == connection_id).first()
            if not connection:
                logger.error(f"Connection {connection_id} not found")
                return
            
            databases = db.query(Database).filter(Database.connection_id == connection_id).all()
            
            for database in databases:
                tables = db.query(Table).filter(Table.database_id == database.id).all()
                
                for table in tables:
                    # Filter by column list if specified
                    if column_list and refresh_mode == "column-list":
                        columns_to_refresh = [c for c in table.columns if c.id in column_list]
                    else:
                        columns_to_refresh = table.columns
                    
                    if not columns_to_refresh:
                        continue
                    
                    # Refresh data embeddings for the table's columns
                    try:
                        result = await indexing_service._sample_data_variations(
                            connection_id=connection_id,
                            table=table,
                            columns=columns_to_refresh,
                            db_type=connection.database_type,
                            host=connection.host,
                            port=connection.port,
                            username=connection.username,
                            password=connection.password,
                            database=connection.database
                        )
                        
                        # Update refresh log
                        from app.models import DataEmbeddingRefreshLog
                        for column in columns_to_refresh:
                            log_entry = DataEmbeddingRefreshLog(
                                connection_id=connection_id,
                                table_id=table.id,
                                column_id=column.id,
                                last_sampled_at=datetime.utcnow(),
                                sample_count=50,  # Default sampling size
                                refresh_status="completed"
                            )
                            db.add(log_entry)
                        
                        db.commit()
                        logger.info(f"Refreshed data embeddings for table {table.name}")
                    
                    except Exception as e:
                        logger.error(f"Error refreshing embeddings for table {table.name}: {str(e)}")
                        
                        # Log failure
                        from app.models import DataEmbeddingRefreshLog
                        for column in columns_to_refresh:
                            log_entry = DataEmbeddingRefreshLog(
                                connection_id=connection_id,
                                table_id=table.id,
                                column_id=column.id,
                                refresh_status="failed",
                                error_message=str(e)
                            )
                            db.add(log_entry)
                        db.commit()
        
        finally:
            db.close()
        
        logger.info(f"Data embedding refresh completed for connection {connection_id}")
    
    except Exception as e:
        logger.error(f"Background data embedding refresh failed: {str(e)}")


@router.post("/refresh-data-embeddings/{connection_id}")
async def trigger_refresh_data_embeddings(
    connection_id: int,
    request: RefreshDataEmbeddingsRequest,
    req: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Trigger data variation embedding refresh for a connection"""
    if not has_db_permission(user, connection_id, "db_reindex"):
        await log_activity(req, user=user, action=Actions.PERM_DENIED,
                           connection_id=connection_id, status="denied",
                           detail={"attempted": "refresh_embeddings"}, db=db)
        raise HTTPException(status_code=403, detail="Permission 'db_reindex' required on this database")
    
    try:
        # Verify connection exists
        connection = db.query(Connection).filter(Connection.id == connection_id).first()
        if not connection:
            raise HTTPException(status_code=404, detail="Connection not found")
        
        if request.dry_run:
            # Just return what would be refreshed
            databases = db.query(Database).filter(Database.connection_id == connection_id).all()
            tables = db.query(Table).filter(Table.database_id.in_([d.id for d in databases])).all()
            
            if request.refresh_mode == "column-list" and request.column_list:
                affected_tables = set()
                for col_id in request.column_list:
                    from app.models import Column
                    col = db.query(Column).filter(Column.id == col_id).first()
                    if col:
                        affected_tables.add(col.table_id)
                column_count = len(request.column_list)
            else:
                affected_tables = {t.id for t in tables}
                column_count = sum(len(t.columns) for t in tables)
            
            return {
                "dry_run": True,
                "connection_id": connection_id,
                "refresh_mode": request.refresh_mode,
                "affected_tables": len(affected_tables),
                "affected_columns": column_count,
                "message": "No changes made (dry-run mode)"
            }
        
        # Schedule background task
        background_tasks.add_task(
            _refresh_data_embeddings_task,
            connection_id,
            request.refresh_mode,
            request.column_list
        )
        
        logger.info(f"Scheduled data embedding refresh for connection {connection_id}")
        
        await log_activity(req, user=user, action=Actions.REFRESH_EMBEDDINGS,
                           connection_id=connection_id, resource_type="connection",
                           resource_id=connection_id,
                           detail={"mode": request.refresh_mode}, db=db)

        return {
            "success": True,
            "connection_id": connection_id,
            "refresh_mode": request.refresh_mode,
            "status": "refresh_scheduled",
            "estimated_duration_seconds": 120,
            "message": "Data embedding refresh task scheduled in background"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering data embedding refresh: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
