"""Chat service - Main orchestration for natural language queries"""

import logging
import time
from typing import Dict, List, Any, Optional
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.pool import NullPool
import re

from app.services.ollama_service import OllamaService
from app.services.vector_service import VectorService
from app.services.cache_service import CacheService
from app.database import SessionLocal
from app.models import Connection, Database, Table, Column

logger = logging.getLogger(__name__)


class ChatService:
    """Main chat orchestration service"""
    
    def __init__(self):
        self.ollama = OllamaService()
        self.vector = VectorService()
        self.cache = CacheService()
        self.db = SessionLocal()
    
    async def process_query(
        self,
        connection_id: int,
        user_prompt: str,
        top_k_tables: int = 5,
        timeout: int = 30
    ) -> Dict[str, Any]:
        start_time = time.time()
        try:
            logger.info(f"Processing query for connection {connection_id}")
            connection = self.db.query(Connection).filter(
                Connection.id == connection_id,
                Connection.is_active == True
            ).first()
            if not connection:
                return {
                    "status": "error",
                    "error": f"Connection {connection_id} not found or inactive",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info("Classifying intent for prompt")
            intent = await self.ollama.classify_intent(user_prompt)
            logger.info(f"Intent classified as: {intent}")

            if intent == "catalog":
                catalog_result = await self._handle_catalog_query(connection, user_prompt)
                catalog_result["execution_time_ms"] = int((time.time() - start_time) * 1000)
                return catalog_result

            logger.info(f"Embedding prompt: {user_prompt[:50]}...")
            prompt_embedding = await self.ollama.embed_text(user_prompt)

            logger.info(f"Searching for top {top_k_tables} relevant tables")
            relevant_results = await self.vector.search(
                embedding=prompt_embedding,
                top_k=top_k_tables * 2,
                filters=None
            )

            table_results = [
                r for r in relevant_results
                if r.get("payload", {}).get("type") == "table"
            ][:top_k_tables]

            if not table_results:
                logger.warning(f"No relevant tables found for prompt: {user_prompt}")
                return {
                    "status": "error",
                    "error": "No relevant tables found for your query",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info(f"Fetching schema for {len(table_results)} relevant tables")
            schema_context = await self._build_schema_context(
                connection_id,
                table_results
            )

            if not schema_context:
                return {
                    "status": "error",
                    "error": "Failed to fetch schema context",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info("Generating SQL with Ollama")
            sample_info = "Sample tables available with realistic data patterns"
            sql = await self.ollama.generate_sql(
                user_prompt=user_prompt,
                schema_context=schema_context,
                sample_info=sample_info
            )

            logger.info(f"Generated SQL: {sql}")
            logger.info("Validating SQL")
            validation_error = self._validate_sql(sql)
            if validation_error:
                return {
                    "status": "error",
                    "error": f"Invalid SQL: {validation_error}",
                    "sql": sql,
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info("Executing query on user database")
            exec_start = time.time()
            result = await self._execute_query(
                connection=connection,
                sql=sql,
                timeout=timeout
            )
            exec_time = int((time.time() - exec_start) * 1000)

            if result.get("status") == "error":
                return {
                    **result,
                    "sql": sql,
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info(f"Formatting {result['row_count']} result rows")
            answer = await self._format_answer(
                user_prompt=user_prompt,
                sql=sql,
                rows=result["rows"],
                columns=result["columns"],
                row_count=result["row_count"]
            )

            return {
                "status": "success",
                "answer": answer,
                "sql": sql,
                "rows": result["rows"],
                "columns": result["columns"],
                "row_count": result["row_count"],
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "query_time_ms": exec_time
            }
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": f"Query processing failed: {str(e)}",
                "execution_time_ms": int((time.time() - start_time) * 1000)
            }

    async def _build_schema_context(
        self,
        connection_id: int,
        table_results: List[Dict]
    ) -> Optional[str]:
        try:
            context_parts = []
            for result in table_results:
                table_name = result.get("payload", {}).get("table_name")
                table = self.db.query(Table).filter(
                    Table.database_id.in_(
                        self.db.query(Database.id).filter(
                            Database.connection_id == connection_id
                        )
                    ),
                    Table.name == table_name
                ).first()
                if not table:
                    continue
                columns = self.db.query(Column).filter(
                    Column.table_id == table.id
                ).all()
                col_descriptions = ", ".join([
                    f"{c.name} ({c.data_type}{' ? nullable' if c.is_nullable else ''})"
                    for c in columns
                ])
                context_parts.append(
                    f"Table: {table_name}\nColumns: {col_descriptions}"
                )
            return "\n\n".join(context_parts) if context_parts else None
        except Exception as e:
            logger.error(f"Error building schema context: {str(e)}")
            return None

    async def _handle_catalog_query(self, connection: Connection, prompt: str) -> Dict[str, Any]:
        """Handle catalog/introspection queries by querying information_schema and pg_catalog on the target DB."""
        try:
            db_url = f"postgresql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}?sslmode=require"
            engine = create_engine(db_url, poolclass=NullPool, connect_args={"connect_timeout": 10})

            lower = prompt.lower()
            result: Dict[str, Any] = {"status": "success", "type": "catalog", "answers": {}}

            if any(k in lower for k in ["tables", "list tables", "what tables"]):
                with engine.connect() as conn:
                    res = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"))
                    tables = [r[0] for r in res.fetchall()]
                result["answers"]["tables"] = tables

            m = re.search(r"schema of ([a-zA-Z_][a-zA-Z0-9_]*)", lower)
            if m:
                tbl = m.group(1)
                with engine.connect() as conn:
                    cols = conn.execute(
                        text("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position;"),
                        {"t": tbl}
                    ).fetchall()
                result["answers"][f"schema:{tbl}"] = [dict(r._mapping) for r in cols]

            m2 = re.search(r"columns in ([a-zA-Z_][a-zA-Z0-9_]*) .*index", lower)
            if m2:
                tbl = m2.group(1)
                with engine.connect() as conn:
                    idx_sql = text("""
                        SELECT i.relname as indexname, array_to_string(array_agg(a.attname), ',') as columns
                        FROM pg_class t
                        JOIN pg_index ix ON t.oid = ix.indrelid
                        JOIN pg_class i ON i.oid = ix.indexrelid
                        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                        WHERE t.relname = :t
                        GROUP BY i.relname;
                    """)
                    rows = conn.execute(idx_sql, {"t": tbl}).fetchall()
                result["answers"][f"indexes:{tbl}"] = [dict(r._mapping) for r in rows]

            if any(k in lower for k in ["open connections", "connections", "active connections"]):
                with engine.connect() as conn:
                    cnt = conn.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();")).scalar()
                    actives_res = conn.execute(text("SELECT pid, usename, state, now() - query_start AS duration, query FROM pg_stat_activity WHERE datname = current_database() ORDER BY now() - query_start DESC LIMIT 10;"))
                    act_rows = actives_res.fetchall()
                result["answers"]["open_connections"] = int(cnt)
                result["answers"]["active_queries"] = [dict(r._mapping) for r in act_rows]

            if any(k in lower for k in ["slow queries", "slow query", "long running", "long-running"]):
                with engine.connect() as conn:
                    slow_res = conn.execute(text("SELECT pid, usename, state, now() - query_start AS duration, query FROM pg_stat_activity WHERE state = 'active' AND datname = current_database() ORDER BY now() - query_start DESC LIMIT 10;"))
                    slow = slow_res.fetchall()
                result["answers"]["slow_queries"] = [dict(r._mapping) for r in slow]

            engine.dispose()
            return result

        except Exception as e:
            logger.error(f"Catalog query failed: {str(e)}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def _validate_sql(self, sql: str) -> Optional[str]:
        if not sql:
            return "SQL is empty"
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT"):
            return "Only SELECT queries are allowed"
        forbidden = ["DELETE", "DROP", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "CREATE"]
        for cmd in forbidden:
            if cmd in sql_upper:
                return f"Command '{cmd}' is not allowed"
        return None

    async def _execute_query(
        self,
        connection: Connection,
        sql: str,
        timeout: int = 30
    ) -> Dict[str, Any]:
        exec_start = time.time()
        try:
            if connection.database_type.lower() == "postgres":
                conn_string = f"postgresql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}?sslmode=require"
            elif connection.database_type.lower() == "mysql":
                conn_string = f"mysql+pymysql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}"
            else:
                return {"status": "error", "error": f"Unsupported database type: {connection.database_type}"}

            engine = create_engine(
                conn_string,
                poolclass=NullPool,
                connect_args={"connect_timeout": timeout} if connection.database_type.lower() == "postgres" else {}
            )

            logger.info(f"Executing on {connection.database_type} database")
            with engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = result.fetchall()
                columns = list(result.keys())
                rows_as_dicts = [dict(zip(columns, [v for v in row])) for row in rows]
            engine.dispose()
            exec_time = int((time.time() - exec_start) * 1000)
            logger.info(f"Query executed in {exec_time}ms, returned {len(rows_as_dicts)} rows")
            return {"status": "success", "rows": rows_as_dicts, "columns": columns, "row_count": len(rows_as_dicts), "execution_time_ms": exec_time}
        except Exception as e:
            logger.error(f"Error executing query: {str(e)}")
            return {"status": "error", "error": f"Query execution failed: {str(e)}"}

    async def _format_answer(self, user_prompt: str, sql: str, rows: List[Dict], columns: List[str], row_count: int) -> str:
        try:
            if row_count == 0:
                return "No results found matching your query."
            if row_count == 1:
                row = rows[0]
                values = ", ".join([f"{k}: {v}" for k, v in row.items()])
                return f"Found 1 result: {values}"
            if row_count <= 10:
                lines = [f"Found {row_count} results:"]
                for i, row in enumerate(rows, 1):
                    values = ", ".join([f"{k}: {v}" for k, v in row.items()])
                    lines.append(f"{i}. {values}")
                return "\n".join(lines)
            else:
                first_col = columns[0]
                values = [str(row.get(first_col, "?")) for row in rows[:5]]
                return f"Found {row_count} results. First 5 {first_col}s: {', '.join(values)}..."
        except Exception as e:
            logger.error(f"Error formatting answer: {str(e)}")
            return f"Query returned {row_count} rows."

    def close(self):
        if self.db:
            self.db.close()

    def __del__(self):
        self.close()
"""Chat service - Main orchestration for natural language queries"""

import logging
import time
from typing import Dict, List, Any, Optional
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.pool import NullPool
import re

from app.services.ollama_service import OllamaService
from app.services.vector_service import VectorService
from app.services.cache_service import CacheService
from app.database import SessionLocal
from app.models import Connection, Database, Table, Column

logger = logging.getLogger(__name__)


class ChatService:
    """Main chat orchestration service"""
    
    def __init__(self):
        self.ollama = OllamaService()
        self.vector = VectorService()
        self.cache = CacheService()
        self.db = SessionLocal()
    
    async def process_query(
        self,
        connection_id: int,
        user_prompt: str,
        top_k_tables: int = 5,
        timeout: int = 30
    ) -> Dict[str, Any]:
        start_time = time.time()
        try:
            logger.info(f"Processing query for connection {connection_id}")
            connection = self.db.query(Connection).filter(
                Connection.id == connection_id,
                Connection.is_active == True
            ).first()
            if not connection:
                return {
                    "status": "error",
                    "error": f"Connection {connection_id} not found or inactive",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info("Classifying intent for prompt")
            intent = await self.ollama.classify_intent(user_prompt)
            logger.info(f"Intent classified as: {intent}")

            if intent == "catalog":
                catalog_result = await self._handle_catalog_query(connection, user_prompt)
                catalog_result["execution_time_ms"] = int((time.time() - start_time) * 1000)
                return catalog_result

            logger.info(f"Embedding prompt: {user_prompt[:50]}...")
            prompt_embedding = await self.ollama.embed_text(user_prompt)

            logger.info(f"Searching for top {top_k_tables} relevant tables")
            relevant_results = await self.vector.search(
                embedding=prompt_embedding,
                top_k=top_k_tables * 2,
                filters=None
            )

            table_results = [
                r for r in relevant_results
                if r["payload"].get("type") == "table"
            ][:top_k_tables]

            if not table_results:
                logger.warning(f"No relevant tables found for prompt: {user_prompt}")
                return {
                    "status": "error",
                    "error": "No relevant tables found for your query",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info(f"Fetching schema for {len(table_results)} relevant tables")
            schema_context = await self._build_schema_context(
                connection_id,
                table_results
            )

            if not schema_context:
                return {
                    "status": "error",
                    "error": "Failed to fetch schema context",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info("Generating SQL with Ollama")
            sample_info = "Sample tables available with realistic data patterns"
            sql = await self.ollama.generate_sql(
                user_prompt=user_prompt,
                schema_context=schema_context,
                sample_info=sample_info
            )

            logger.info(f"Generated SQL: {sql}")
            logger.info("Validating SQL")
            validation_error = self._validate_sql(sql)
            if validation_error:
                return {
                    "status": "error",
                    "error": f"Invalid SQL: {validation_error}",
                    "sql": sql,
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info("Executing query on user database")
            exec_start = time.time()
            result = await self._execute_query(
                connection=connection,
                sql=sql,
                timeout=timeout
            )
            exec_time = int((time.time() - exec_start) * 1000)

            if result.get("status") == "error":
                return {
                    **result,
                    "sql": sql,
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info(f"Formatting {result['row_count']} result rows")
            answer = await self._format_answer(
                user_prompt=user_prompt,
                sql=sql,
                rows=result["rows"],
                columns=result["columns"],
                row_count=result["row_count"]
            )

            return {
                "status": "success",
                "answer": answer,
                "sql": sql,
                "rows": result["rows"],
                "columns": result["columns"],
                "row_count": result["row_count"],
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "query_time_ms": exec_time
            }
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": f"Query processing failed: {str(e)}",
                "execution_time_ms": int((time.time() - start_time) * 1000)
            }

    async def _build_schema_context(
        self,
        connection_id: int,
        table_results: List[Dict]
    ) -> Optional[str]:
        try:
            context_parts = []
            for result in table_results:
                table_name = result["payload"].get("table_name")
                table = self.db.query(Table).filter(
                    Table.database_id.in_(
                        self.db.query(Database.id).filter(
                            Database.connection_id == connection_id
                        )
                    ),
                    Table.name == table_name
                ).first()
                if not table:
                    continue
                columns = self.db.query(Column).filter(
                    Column.table_id == table.id
                ).all()
                col_descriptions = ", ".join([
                    f"{c.name} ({c.data_type}{' ? nullable' if c.is_nullable else ''})"
                    for c in columns
                ])
                context_parts.append(
                    f"Table: {table_name}\nColumns: {col_descriptions}"
                )
            return "\n\n".join(context_parts) if context_parts else None
        except Exception as e:
            logger.error(f"Error building schema context: {str(e)}")
            return None

    async def _handle_catalog_query(self, connection: Connection, prompt: str) -> Dict[str, Any]:
        """Handle catalog/introspection queries by querying information_schema and pg_catalog on the target DB."""
        try:
            db_url = f"postgresql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}?sslmode=require"
            engine = create_engine(db_url, poolclass=NullPool, connect_args={"connect_timeout": 10})

            lower = prompt.lower()
            result: Dict[str, Any] = {"status": "success", "type": "catalog", "answers": {}}

            if any(k in lower for k in ["tables", "list tables", "what tables"]):
                with engine.connect() as conn:
                    res = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"))
                    tables = [r[0] for r in res.fetchall()]
                result["answers"]["tables"] = tables

            m = re.search(r"schema of ([a-zA-Z_][a-zA-Z0-9_]*)", lower)
            if m:
                tbl = m.group(1)
                with engine.connect() as conn:
                    cols = conn.execute(
                        text("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position;"),
                        {"t": tbl}
                    ).fetchall()
                result["answers"][f"schema:{tbl}"] = [dict(r._mapping) for r in cols]

            m2 = re.search(r"columns in ([a-zA-Z_][a-zA-Z0-9_]*) .*index", lower)
            if m2:
                tbl = m2.group(1)
                with engine.connect() as conn:
                    idx_sql = text("""
                        SELECT i.relname as indexname, array_to_string(array_agg(a.attname), ',') as columns
                        FROM pg_class t
                        JOIN pg_index ix ON t.oid = ix.indrelid
                        JOIN pg_class i ON i.oid = ix.indexrelid
                        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                        WHERE t.relname = :t
                        GROUP BY i.relname;
                    """)
                    rows = conn.execute(idx_sql, {"t": tbl}).fetchall()
                result["answers"][f"indexes:{tbl}"] = [dict(r._mapping) for r in rows]

            if any(k in lower for k in ["open connections", "connections", "active connections"]):
                with engine.connect() as conn:
                    cnt = conn.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();")).scalar()
                    actives = conn.execute(text("SELECT pid, usename, state, now() - query_start AS duration, query FROM pg_stat_activity WHERE datname = current_database() ORDER BY now() - query_start DESC LIMIT 10;"))
                    act_rows = actives.fetchall()
                result["answers"]["open_connections"] = int(cnt)
                result["answers"]["active_queries"] = [dict(r._mapping) for r in act_rows]

            if any(k in lower for k in ["slow queries", "slow query", "long running", "long-running"]):
                with engine.connect() as conn:
                    rows = conn.execute(text("SELECT pid, usename, state, now() - query_start AS duration, query FROM pg_stat_activity WHERE state = 'active' AND datname = current_database() ORDER BY now() - query_start DESC LIMIT 10;"))
                    slow = rows.fetchall()
                result["answers"]["slow_queries"] = [dict(r._mapping) for r in slow]

            engine.dispose()
            return result

        except Exception as e:
            logger.error(f"Catalog query failed: {str(e)}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def _validate_sql(self, sql: str) -> Optional[str]:
        if not sql:
            return "SQL is empty"
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT"):
            return "Only SELECT queries are allowed"
        forbidden = ["DELETE", "DROP", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "CREATE"]
        for cmd in forbidden:
            if cmd in sql_upper:
                return f"Command '{cmd}' is not allowed"
        return None

    async def _execute_query(
        self,
        connection: Connection,
        sql: str,
        timeout: int = 30
    ) -> Dict[str, Any]:
        exec_start = time.time()
        try:
            if connection.database_type.lower() == "postgres":
                conn_string = f"postgresql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}?sslmode=require"
            elif connection.database_type.lower() == "mysql":
                conn_string = f"mysql+pymysql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}"
            else:
                return {
                    "status": "error",
                    "error": f"Unsupported database type: {connection.database_type}"
                }

            engine = create_engine(
                conn_string,
                poolclass=NullPool,
                connect_args={"connect_timeout": timeout} if connection.database_type.lower() == "postgres" else {}
            )

            logger.info(f"Executing on {connection.database_type} database")
            with engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = result.fetchall()
                columns = list(result.keys())
                rows_as_dicts = [
                    dict(zip(columns, [v for v in row]))
                    for row in rows
                ]
            engine.dispose()
            exec_time = int((time.time() - exec_start) * 1000)
            logger.info(f"Query executed in {exec_time}ms, returned {len(rows_as_dicts)} rows")
            return {
                "status": "success",
                "rows": rows_as_dicts,
                "columns": columns,
                "row_count": len(rows_as_dicts),
                "execution_time_ms": exec_time
            }
        except Exception as e:
            logger.error(f"Error executing query: {str(e)}")
            return {
                "status": "error",
                "error": f"Query execution failed: {str(e)}"
            }

    async def _format_answer(
        self,
        user_prompt: str,
        sql: str,
        rows: List[Dict],
        columns: List[str],
        row_count: int
    ) -> str:
        try:
            if row_count == 0:
                return "No results found matching your query."
            if row_count == 1:
                row = rows[0]
                values = ", ".join([f"{k}: {v}" for k, v in row.items()])
                return f"Found 1 result: {values}"
            if row_count <= 10:
                lines = [f"Found {row_count} results:"]
                for i, row in enumerate(rows, 1):
                    values = ", ".join([f"{k}: {v}" for k, v in row.items()])
                    lines.append(f"{i}. {values}")
                return "\n".join(lines)
            else:
                first_col = columns[0]
                values = [str(row.get(first_col, "?")) for row in rows[:5]]
                return f"Found {row_count} results. First 5 {first_col}s: {', '.join(values)}..."
        except Exception as e:
            logger.error(f"Error formatting answer: {str(e)}")
            return f"Query returned {row_count} rows."

    def close(self):
        if self.db:
            self.db.close()

    def __del__(self):
        self.close()
"""Chat service - Main orchestration for natural language queries"""

import logging
import time
from typing import Dict, List, Any, Optional
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.pool import NullPool
import re

from app.services.ollama_service import OllamaService
from app.services.vector_service import VectorService
from app.services.cache_service import CacheService
from app.database import SessionLocal
from app.models import Connection, Database, Table, Column

logger = logging.getLogger(__name__)


class ChatService:
    """Main chat orchestration service"""
    
    def __init__(self):
        self.ollama = OllamaService()
        self.vector = VectorService()
        self.cache = CacheService()
        self.db = SessionLocal()
    
    async def process_query(
        self,
        connection_id: int,
        user_prompt: str,
        top_k_tables: int = 5,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Process natural language query and return results
        
        Flow:
        1. Embed user prompt
        2. Search for relevant tables in Qdrant
        3. Fetch schema context from PostgreSQL
        4. Generate SQL with Ollama
        5. Validate SQL (SELECT only)
        6. Execute on user database
        7. Format results
        
        Args:
            connection_id: Database connection ID
            user_prompt: Natural language query from user
            top_k_tables: Number of top tables to include in context
            timeout: Query execution timeout in seconds
        
        Returns:
            {
                "answer": "...",  # Natural language result
                "sql": "SELECT...",  # Generated SQL
                "rows": [...],  # Result rows
                "columns": [...],  # Column names
                "row_count": 5,  # Number of results
                "execution_time_ms": 123,
                "status": "success|error",
                "error": "..." (if error)
            }
        """
        start_time = time.time()
        
        try:
            # Step 1: Validate connection exists
            logger.info(f"Processing query for connection {connection_id}")
            connection = self.db.query(Connection).filter(
                Connection.id == connection_id,
                Connection.is_active == True
            ).first()
            
            if not connection:
                return {
                    "status": "error",
                    "error": f"Connection {connection_id} not found or inactive",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }
            
            # Step 2: Classify intent (catalog vs data)
            logger.info("Classifying intent for prompt")
            intent = await self.ollama.classify_intent(user_prompt)
            logger.info(f"Intent classified as: {intent}")

            if intent == "catalog":
                # Handle catalog/introspection queries separately
                catalog_result = await self._handle_catalog_query(connection, user_prompt)
                catalog_result["execution_time_ms"] = int((time.time() - start_time) * 1000)
                return catalog_result

            # Step 3: Embed user prompt
            logger.info(f"Embedding prompt: {user_prompt[:50]}...")
            prompt_embedding = await self.ollama.embed_text(user_prompt)
            
            # Step 3: Search for relevant tables
            logger.info(f"Searching for top {top_k_tables} relevant tables")
            relevant_results = await self.vector.search(
                embedding=prompt_embedding,
                top_k=top_k_tables * 2,  # Get more to filter
                filters=None
            )
            
            # Filter to only table results (not column results for now)
            table_results = [
                r for r in relevant_results
                if r["payload"].get("type") == "table"
            ][:top_k_tables]
            
            if not table_results:
                logger.warning(f"No relevant tables found for prompt: {user_prompt}")
                return {
                    "status": "error",
                    "error": "No relevant tables found for your query",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }
            
            # Step 4: Fetch schema context
            logger.info(f"Fetching schema for {len(table_results)} relevant tables")
            schema_context = await self._build_schema_context(
                connection_id,
                table_results
            )
            
            if not schema_context:
                return {
                    "status": "error",
                    "error": "Failed to fetch schema context",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }
            
            # Step 5: Generate SQL
            logger.info("Generating SQL with Ollama")
            sample_info = "Sample tables available with realistic data patterns"
            
            sql = await self.ollama.generate_sql(
                user_prompt=user_prompt,
                schema_context=schema_context,
                sample_info=sample_info
            )
            
            logger.info(f"Generated SQL: {sql}")
            
            # Step 6: Validate SQL
            logger.info("Validating SQL")
            validation_error = self._validate_sql(sql)
            if validation_error:
                return {
                    "status": "error",
                    "error": f"Invalid SQL: {validation_error}",
                    "sql": sql,
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }
            
            # Step 7: Execute query
            logger.info("Executing query on user database")
            exec_start = time.time()
            result = await self._execute_query(
                connection=connection,
                sql=sql,
                timeout=timeout
            )
            exec_time = int((time.time() - exec_start) * 1000)
            
            if result.get("status") == "error":
                return {
                    **result,
                    "sql": sql,
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }
            
            # Step 8: Format results with natural language answer
            logger.info(f"Formatting {result['row_count']} result rows")
            answer = await self._format_answer(
                user_prompt=user_prompt,
                sql=sql,
                rows=result["rows"],
                columns=result["columns"],
                row_count=result["row_count"]
            )
            
            return {
                "status": "success",
                "answer": answer,
                "sql": sql,
                "rows": result["rows"],
                "columns": result["columns"],
                "row_count": result["row_count"],
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "query_time_ms": exec_time
            }
        
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": f"Query processing failed: {str(e)}",
                "execution_time_ms": int((time.time() - start_time) * 1000)
            }
    
    async def _build_schema_context(
        self,
        connection_id: int,
        table_results: List[Dict]
    ) -> Optional[str]:
        """Build schema context from relevant tables"""
        
        try:
            context_parts = []
            
            for result in table_results:
                table_name = result["payload"].get("table_name")
                
                # Get table columns from database
                table = self.db.query(Table).filter(
                    Table.database_id.in_(
                        self.db.query(Database.id).filter(
                            Database.connection_id == connection_id
                        )
                    ),
                    Table.name == table_name
                ).first()
                
                if not table:
                    continue
                
                # Get columns
                columns = self.db.query(Column).filter(
                    Column.table_id == table.id
                ).all()
                
                # Build schema description
                col_descriptions = ", ".join([
                    f"{c.name} ({c.data_type}{'? nullable' if c.is_nullable else ''})"
                    for c in columns
                ])
                
                context_parts.append(
                    f"Table: {table_name}\nColumns: {col_descriptions}"
                )
            
            return "\n\n".join(context_parts) if context_parts else None
        
        except Exception as e:
            logger.error(f"Error building schema context: {str(e)}")
            return None

    async def _handle_catalog_query(self, connection: Connection, prompt: str) -> Dict[str, Any]:
        """Handle catalog/introspection queries by querying information_schema and pg_catalog on the target DB."""
        try:
            db_url = f"postgresql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}?sslmode=require"
            engine = create_engine(db_url, poolclass=NullPool, connect_args={"connect_timeout": 10})

            # Decide which catalog info is requested based on keywords
            lower = prompt.lower()
            result: Dict[str, Any] = {"status": "success", "type": "catalog", "answers": {}}

            # Tables list
            if any(k in lower for k in ["tables", "list tables", "what tables"]):
                with engine.connect() as conn:
                    res = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"))
                    tables = [r[0] for r in res.fetchall()]
                result["answers"]["tables"] = tables

            # Schema for a specific table
            m = re.search(r"schema of ([a-zA-Z_][a-zA-Z0-9_]*)", lower)
            if m:
                tbl = m.group(1)
                with engine.connect() as conn:
                    cols = conn.execute(text("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position;"), {"t": tbl}).fetchall()
                result["answers"][f"schema:{tbl}"] = [dict(r._mapping) for r in cols]

            # Indexes for a table or which columns have indexes
            m2 = re.search(r"columns in ([a-zA-Z_][a-zA-Z0-9_]*) .*index", lower)
            if m2:
                tbl = m2.group(1)
                with engine.connect() as conn:
                    idx_sql = text("""
                        SELECT i.relname as indexname, array_to_string(array_agg(a.attname), ',') as columns
                        FROM pg_class t
                        JOIN pg_index ix ON t.oid = ix.indrelid
                        JOIN pg_class i ON i.oid = ix.indexrelid
                        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                        WHERE t.relname = :t
                        GROUP BY i.relname;
                    """)
                    rows = conn.execute(idx_sql, {"t": tbl}).fetchall()
                result["answers"][f"indexes:{tbl}"] = [dict(r._mapping) for r in rows]

            # Open connections count
            if any(k in lower for k in ["open connections", "connections", "active connections"]):
                with engine.connect() as conn:
                    cnt = conn.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();")).scalar()
                    actives = conn.execute(text("SELECT pid, usename, state, now() - query_start AS duration, query FROM pg_stat_activity WHERE datname = current_database() ORDER BY now() - query_start DESC LIMIT 10;"))
                    act_rows = actives.fetchall()
                result["answers"]["open_connections"] = int(cnt)
                result["answers"]["active_queries"] = [dict(r._mapping) for r in act_rows]

            # Slow queries (active longest)
            if any(k in lower for k in ["slow queries", "slow query", "long running", "long-running"]):
                with engine.connect() as conn:
                    slow_res = conn.execute(text("SELECT pid, usename, state, now() - query_start AS duration, query FROM pg_stat_activity WHERE state = 'active' AND datname = current_database() ORDER BY now() - query_start DESC LIMIT 10;"))
                    slow = slow_res.fetchall()
                result["answers"]["slow_queries"] = [dict(r._mapping) for r in slow]

            engine.dispose()
            return result

        except Exception as e:
            logger.error(f"Catalog query failed: {str(e)}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    def _validate_sql(self, sql: str) -> Optional[str]:
        """Validate SQL query - only SELECT allowed"""
        
        if not sql:
            return "SQL is empty"
        
        # Normalize
        sql_upper = sql.strip().upper()
        
        # Only SELECT allowed
        if not sql_upper.startswith("SELECT"):
            return "Only SELECT queries are allowed"
        
        # Check for dangerous commands
        forbidden = ["DELETE", "DROP", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "CREATE"]
        for cmd in forbidden:
            if cmd in sql_upper:
                return f"Command '{cmd}' is not allowed"
        
        return None
    
    async def _execute_query(
        self,
        connection: Connection,
        sql: str,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """Execute query on user database"""
        
        exec_start = time.time()
        
        try:
            # Build connection string
            if connection.database_type.lower() == "postgres":
                conn_string = f"postgresql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}?sslmode=require"
            elif connection.database_type.lower() == "mysql":
                conn_string = f"mysql+pymysql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}"
            else:
                return {
                    "status": "error",
                    "error": f"Unsupported database type: {connection.database_type}"
                }
            
            # Create connection
            engine = create_engine(
                conn_string,
                poolclass=NullPool,
                connect_args={"connect_timeout": timeout} if connection.database_type.lower() == "postgres" else {}
            )
            
            # Execute query
            logger.info(f"Executing on {connection.database_type} database")
            with engine.connect() as conn:
                result = conn.execute(text(sql))
                
                # Get results
                rows = result.fetchall()
                columns = list(result.keys())
                
                # Convert rows to list of dicts
                rows_as_dicts = [
                    dict(zip(columns, [v for v in row]))
                    for row in rows
                ]
            
            engine.dispose()
            
            exec_time = int((time.time() - exec_start) * 1000)
            logger.info(f"Query executed in {exec_time}ms, returned {len(rows_as_dicts)} rows")
            
            return {
                "status": "success",
                "rows": rows_as_dicts,
                "columns": columns,
                "row_count": len(rows_as_dicts),
                "execution_time_ms": exec_time
            }
        
        except Exception as e:
            logger.error(f"Error executing query: {str(e)}")
            return {
                "status": "error",
                "error": f"Query execution failed: {str(e)}"
            }
    
    async def _format_answer(
        self,
        user_prompt: str,
        sql: str,
        rows: List[Dict],
        columns: List[str],
        row_count: int
    ) -> str:
        """Format natural language answer from results"""
        
        try:
            if row_count == 0:
                return "No results found matching your query."
            
            if row_count == 1:
                # Single row - format as statement
                row = rows[0]
                values = ", ".join([f"{k}: {v}" for k, v in row.items()])
                return f"Found 1 result: {values}"
            
            # Multiple rows - format summary
            if row_count <= 10:
                # Small result set - show all
                lines = [f"Found {row_count} results:"]
                for i, row in enumerate(rows, 1):
                    values = ", ".join([f"{k}: {v}" for k, v in row.items()])
                    lines.append(f"{i}. {values}")
                return "\n".join(lines)
            
            else:
                # Large result set - show summary
                first_col = columns[0]
                values = [str(row.get(first_col, "?")) for row in rows[:5]]
                return f"Found {row_count} results. First 5 {first_col}s: {', '.join(values)}..."
        
        except Exception as e:
            logger.error(f"Error formatting answer: {str(e)}")
            return f"Query returned {row_count} rows."
    
    def close(self):
        """Close database session"""
        if self.db:
            self.db.close()
    
    def __del__(self):
        """Cleanup"""
        self.close()
