"""Indexing service for embedding and storing schema"""

import logging
import json
from typing import Dict, List, Any
import asyncio
from datetime import datetime

from app.services.ollama_service import OllamaService
from app.services.vector_service import VectorService
from app.database import SessionLocal
from app.models import Database, Table, Column

logger = logging.getLogger(__name__)


class IndexingService:
    """Index database schema into vector store"""
    
    def __init__(self, ollama_service: OllamaService, vector_service: VectorService):
        self.ollama = ollama_service
        self.vector = vector_service
    
    async def index_schema(
        self,
        connection_id: int,
        database_name: str,
        schema_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Index schema into vector database and save metadata
        
        Args:
            connection_id: ID of the database connection
            database_name: Name of the database
            schema_data: Schema data with tables and columns
        
        Returns:
            {
                "indexed_tables": 5,
                "indexed_columns": 42,
                "total_vectors": 47,
                "duration_seconds": 12.5
            }
        """
        
        import time
        start_time = time.time()
        db = SessionLocal()
        
        try:
            indexed_tables = 0
            indexed_columns = 0
            vector_ids = []
            
            # Create or update database record
            database = db.query(Database).filter(
                Database.connection_id == connection_id,
                Database.name == database_name
            ).first()
            
            if not database:
                database = Database(
                    connection_id=connection_id,
                    name=database_name,
                    last_indexed_at=datetime.utcnow()
                )
                db.add(database)
                db.flush()
                logger.info(f"Created database record: {database_name}")
            else:
                database.last_indexed_at = datetime.utcnow()
                logger.info(f"Updated database record: {database_name}")
            
            tables = schema_data.get("tables", [])
            
            for table in tables:
                table_name = table["name"]
                columns = table.get("columns", [])
                row_count = table.get("row_count", 0)
                
                # Create or update table record
                table_record = db.query(Table).filter(
                    Table.database_id == database.id,
                    Table.name == table_name
                ).first()
                
                if not table_record:
                    table_record = Table(
                        database_id=database.id,
                        name=table_name,
                        sample_count=row_count,
                        is_indexed=True,
                        last_indexed_at=datetime.utcnow()
                    )
                    db.add(table_record)
                    db.flush()
                    logger.info(f"Created table record: {table_name}")
                else:
                    table_record.sample_count = row_count
                    table_record.is_indexed = True
                    table_record.last_indexed_at = datetime.utcnow()
                
                # Create table summary
                col_summary = ", ".join([f"{c['name']} ({c['type']})" for c in columns])
                table_text = f"Table: {table_name}. Columns: {col_summary}. Rows: {row_count}"
                
                # Generate embedding for table
                table_embedding = await self.ollama.embed_text(table_text)
                
                # Store table vector
                table_vector_id = f"conn_{connection_id}_table_{table_name}"
                metadata = {
                    "connection_id": connection_id,
                    "database": database_name,
                    "type": "table",
                    "table_name": table_name,
                    "column_count": len(columns),
                    "row_count": row_count,
                    "description": table_text
                }
                
                await self.vector.upsert_vector(
                    vector_id=table_vector_id,
                    embedding=table_embedding,
                    metadata=metadata
                )
                
                vector_ids.append(table_vector_id)
                indexed_tables += 1
                
                # Index individual columns
                for column in columns:
                    col_name = column["name"]
                    col_type = column["type"]
                    col_nullable = column.get("nullable", True)
                    
                    # Create or update column record
                    col_record = db.query(Column).filter(
                        Column.table_id == table_record.id,
                        Column.name == col_name
                    ).first()
                    
                    if not col_record:
                        col_record = Column(
                            table_id=table_record.id,
                            name=col_name,
                            data_type=col_type,
                            is_nullable=col_nullable
                        )
                        db.add(col_record)
                        db.flush()
                    
                    col_text = f"Column: {col_name} in table {table_name}. Type: {col_type}. Nullable: {col_nullable}"
                    
                    col_embedding = await self.ollama.embed_text(col_text)
                    
                    col_vector_id = f"conn_{connection_id}_col_{table_name}_{col_name}"
                    col_metadata = {
                        "connection_id": connection_id,
                        "database": database_name,
                        "type": "column",
                        "table_name": table_name,
                        "column_name": col_name,
                        "column_type": col_type,
                        "nullable": col_nullable,
                        "description": col_text
                    }
                    
                    await self.vector.upsert_vector(
                        vector_id=col_vector_id,
                        embedding=col_embedding,
                        metadata=col_metadata
                    )
                    
                    vector_ids.append(col_vector_id)
                    indexed_columns += 1
            
            # Commit all database changes
            db.commit()
            
            duration = time.time() - start_time
            
            result = {
                "indexed_tables": indexed_tables,
                "indexed_columns": indexed_columns,
                "total_vectors": len(vector_ids),
                "duration_seconds": round(duration, 2)
            }
            
            logger.info(f"Indexed {indexed_tables} tables, {indexed_columns} columns for connection {connection_id}")
            return result
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error indexing schema: {str(e)}", exc_info=True)
            raise
        finally:
            db.close()
