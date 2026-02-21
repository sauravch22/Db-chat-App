"""Schema extraction service for different database types"""

import logging
from typing import Dict, List, Any
import asyncio
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)


class SchemaExtractor:
    """Extract schema from user databases"""
    
    @staticmethod
    def build_connection_string(
        db_type: str,
        host: str,
        port: int,
        username: str,
        password: str,
        database: str
    ) -> str:
        """Build database connection string"""
        
        if db_type.lower() == "postgres":
            # Use SSL mode for Postgres (required for cloud services like Neon)
            return f"postgresql://{username}:{password}@{host}:{port}/{database}?sslmode=require"
        elif db_type.lower() == "mysql":
            return f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"
        elif db_type.lower() == "sqlserver":
            return f"mssql+pyodbc://{username}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server"
        else:
            raise ValueError(f"Unsupported database type: {db_type}")
    
    @staticmethod
    async def extract_schema(
        db_type: str,
        host: str,
        port: int,
        username: str,
        password: str,
        database: str,
        timeout: int = 10
    ) -> Dict[str, Any]:
        """
        Extract schema from database
        
        Returns:
            {
                "database": "dbname",
                "tables": [
                    {
                        "name": "users",
                        "columns": [
                            {"name": "id", "type": "INTEGER", "nullable": False},
                            {"name": "email", "type": "VARCHAR", "nullable": False}
                        ],
                        "row_count": 1500
                    }
                ]
            }
        """
        
        try:
            conn_string = SchemaExtractor.build_connection_string(
                db_type, host, port, username, password, database
            )
            logger.info(f"Connecting to {db_type} at {host}:{port}/{database}")
            logger.info(f"Connection string: {conn_string.split('@')[0]}@[hidden]")
            
            # Create engine with appropriate timeout based on DB type
            connect_args = {}
            if db_type.lower() == "postgres":
                connect_args = {"connect_timeout": timeout}
            else:
                connect_args = {"timeout": timeout}
            
            logger.info(f"Creating engine with connect_args: {connect_args}")
            engine = create_engine(
                conn_string,
                poolclass=NullPool,
                connect_args=connect_args
            )
            logger.info(f"Engine created successfully")
            
            # Run extraction in thread pool to avoid blocking
            logger.info(f"Starting schema extraction in thread pool")
            loop = asyncio.get_event_loop()
            schema = await loop.run_in_executor(
                None,
                SchemaExtractor._do_extract,
                engine,
                database
            )
            
            logger.info(f"Schema extraction completed, disposing engine")
            engine.dispose()
            return schema
            
        except Exception as e:
            logger.error(f"Error extracting schema: {str(e)}", exc_info=True)
            raise
    
    @staticmethod
    def _do_extract(engine, database: str) -> Dict[str, Any]:
        """Synchronous schema extraction"""
        
        logger.info(f"_do_extract started for database: {database}")
        inspector = inspect(engine)
        logger.info(f"Inspector created")
        tables = inspector.get_table_names()
        logger.info(f"Found {len(tables)} tables")
        
        schema_data = {
            "database": database,
            "tables": []
        }
        
        for table_name in tables:
            # Skip system tables
            if table_name.startswith('pg_') or table_name.startswith('information_schema'):
                continue
            
            logger.info(f"Processing table: {table_name}")
            columns = inspector.get_columns(table_name)
            
            column_list = [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "primary_key": col.get("primary_key", False)
                }
                for col in columns
            ]
            
            # Try to get row count
            row_count = 0
            try:
                with engine.connect() as conn:
                    result = conn.execute(text(f"SELECT COUNT(*) as cnt FROM {table_name}"))
                    row_count = result.scalar() or 0
            except Exception as e:
                logger.warning(f"Could not get row count for {table_name}: {e}")
            
            schema_data["tables"].append({
                "name": table_name,
                "columns": column_list,
                "row_count": row_count
            })
        
        logger.info(f"_do_extract completed, returning {len(schema_data['tables'])} tables")
        return schema_data
