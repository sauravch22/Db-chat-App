"""Indexing service for embedding and storing schema"""

import logging
import json
from typing import Dict, List, Any, Optional
import asyncio
from datetime import datetime

from app.services.ollama_service import OllamaService
from app.services.vector_service import VectorService
from app.services.schema_service import SchemaExtractor
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from app.database import SessionLocal
from app.models import Database, Table, Column
from app.models import ForeignKeyModel as ForeignKey

logger = logging.getLogger(__name__)


class IndexingService:
    """Index database schema into vector store"""
    
    def __init__(self, ollama_service: OllamaService, vector_service: VectorService):
        self.ollama = ollama_service
        self.vector = vector_service

    def _quote_ident(self, name: str, db_type: str) -> str:
        if db_type and db_type.lower() == "mysql":
            return f"`{name}`"
        return f"\"{name}\""

    def _is_categorical_type(self, col_type: str) -> bool:
        if not col_type:
            return False
        t = col_type.lower()
        return any(k in t for k in ["char", "text", "uuid", "enum", "varchar", "bpchar"])

    def _sample_data_variations(
        self,
        engine,
        table_name: str,
        columns: List[Dict[str, Any]],
        db_type: str,
        limit: int = 50
    ) -> Dict[str, List[str]]:
        samples: Dict[str, List[str]] = {}
        try:
            with engine.connect() as conn:
                for col in columns:
                    col_name = col.get("name")
                    col_type = col.get("type")
                    if not col_name or not self._is_categorical_type(str(col_type)):
                        continue

                    table_ident = self._quote_ident(table_name, db_type)
                    col_ident = self._quote_ident(col_name, db_type)
                    sql = text(
                        f"SELECT DISTINCT {col_ident} AS v "
                        f"FROM {table_ident} "
                        f"WHERE {col_ident} IS NOT NULL "
                        f"LIMIT {int(limit)}"
                    )
                    rows = conn.execute(sql).fetchall()
                    values = [str(r[0]) for r in rows if r[0] is not None]
                    samples[col_name] = values
        except Exception as e:
            logger.warning(f"Data sampling failed for {table_name}: {str(e)}")
        return samples
    
    async def index_schema(
        self,
        connection_id: int,
        database_name: str,
        schema_data: Dict[str, Any],
        db_type: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None
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

            data_engine = None
            if all([db_type, host, port, username, password, database_name]):
                conn_string = SchemaExtractor.build_connection_string(
                    db_type, host, port, username, password, database_name
                )
                connect_args = {"connect_timeout": 10} if db_type.lower() in ("postgres", "postgresql") else {"timeout": 10}
                data_engine = create_engine(
                    conn_string,
                    poolclass=NullPool,
                    connect_args=connect_args
                )
            
            # Extract foreign keys using SQLAlchemy inspector
            fk_map = {}
            if data_engine is not None:
                try:
                    fk_map = SchemaExtractor.get_foreign_keys(data_engine)
                    logger.info(f"Extracted {sum(len(v) for v in fk_map.values())} foreign keys")
                except Exception as e:
                    logger.warning(f"Could not extract FKs: {e}")
            
            # Delete existing FK records for this database (to handle schema changes)
            db.query(ForeignKey).filter(ForeignKey.database_id == database.id).delete()
            db.flush()
            logger.info(f"Cleared existing FK records for database {database_name}")
            
            # Store FK relationships in database
            fk_count = 0
            for table_name, table_fks in fk_map.items():
                for col_name, fk_info in table_fks.items():
                    fk_record = ForeignKey(
                        database_id=database.id,
                        table_name=table_name,
                        column_name=col_name,
                        referenced_table=fk_info.get("references_table"),
                        referenced_column=fk_info.get("references_column"),
                        constraint_name=fk_info.get("constraint_name")
                    )
                    db.add(fk_record)
                    fk_count += 1
            
            if fk_count > 0:
                db.flush()
                logger.info(f"Stored {fk_count} FK relationships in database")
            
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
                table_record.context = table_text
                
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
                    
                    # Set primary key flag from schema
                    col_record.is_primary_key = column.get("primary_key", False)
                    
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

                # Data-variation sampling and embeddings (optional)
                if data_engine is not None:
                    sampled_values = self._sample_data_variations(
                        engine=data_engine,
                        table_name=table_name,
                        columns=columns,
                        db_type=db_type,
                        limit=50
                    )

                    for col_name, values in sampled_values.items():
                        if not values:
                            continue

                        # Persist sample values for quick context (truncate for size)
                        col_record = db.query(Column).filter(
                            Column.table_id == table_record.id,
                            Column.name == col_name
                        ).first()
                        if col_record:
                            col_record.sample_values = json.dumps(values[:20])

                        for value in values:
                            value_text = f"Value: {value}. Column: {col_name}. Table: {table_name}."
                            value_embedding = await self.ollama.embed_text(value_text)
                            value_vector_id = f"conn_{connection_id}_data_{table_name}_{col_name}_{hash(value)}"
                            value_metadata = {
                                "connection_id": connection_id,
                                "database": database_name,
                                "type": "data",
                                "table_name": table_name,
                                "column_name": col_name,
                                "value": str(value),
                                "description": value_text
                            }
                            await self.vector.upsert_vector(
                                vector_id=value_vector_id,
                                embedding=value_embedding,
                                metadata=value_metadata
                            )
                            vector_ids.append(value_vector_id)
            
            # Commit all database changes
            db.commit()

            if data_engine is not None:
                data_engine.dispose()
            
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
