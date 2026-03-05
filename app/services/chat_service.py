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
from app.services.metadata_service import MetadataService
from app.database import SessionLocal
from app.models import Connection, Database, Table, Column

logger = logging.getLogger(__name__)


class ChatService:
    """Main chat orchestration service"""
    
    def __init__(self):
        self.ollama = OllamaService()
        self.vector = VectorService()
        self.cache = CacheService()
        self.metadata = MetadataService()
        self.db = SessionLocal()
    
    async def process_query(
        self,
        connection_id: int,
        user_prompt: str,
        top_k_tables: int = 5,
        timeout: int = 30,
        thread_history: list = None
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
            # Fast keyword pre-check: structural words always mean catalog
            _structural_keywords = [
                "schema", "schemas", "describe", "definition", "indexes", "indices", "ddl",
                "structure of", "columns of", "primary key", "primary keys", "foreign key", "foreign keys",
                "constraints", "row count", "row size", "table size", "how many rows",
                "list tables", "show tables", "all tables", "what tables",
                "list all tables", "show all tables"
            ]
            if any(kw in user_prompt.lower() for kw in _structural_keywords):
                intent = "catalog"
                logger.info("Intent pre-classified as catalog (structural keyword match)")
            else:
                intent = await self.ollama.classify_intent(user_prompt)
                logger.info(f"Intent classified as: {intent}")

            if intent == "catalog":
                catalog_result = await self._handle_catalog_query(connection, user_prompt)
                # If catalog handler found no matching pattern, fall back to data path
                if catalog_result.get("answers"):
                    answer_text = self._format_catalog_answers(catalog_result["answers"])
                    return {
                        "status": "success",
                        "answer": answer_text,
                        "sql": None,
                        "rows": None,
                        "columns": None,
                        "row_count": None,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "query_time_ms": None
                    }
                logger.info("Catalog handler returned empty answers, falling back to data path")

            logger.info(f"Embedding prompt: {user_prompt[:50]}...")
            prompt_embedding = await self.ollama.embed_text(user_prompt)

            logger.info("Fetching table summaries for v2 table selection")
            table_summaries = self.metadata.get_table_summaries(connection_id)
            table_names = []

            if table_summaries:
                allowed_tables = {t["name"] for t in table_summaries}
                identified = await self.ollama.identify_tables(user_prompt, table_summaries)
                identified = [t for t in identified if t in allowed_tables]
                if identified:
                    max_tables = max(top_k_tables, 5)
                    identified = identified[:max_tables]
                    summary_text = "\n".join([t["summary"] for t in table_summaries if t["name"] in identified])
                    similarity = await self.ollama.verify_intent_similarity(prompt_embedding, summary_text)
                    if similarity >= 0.35:
                        table_names = identified
                        logger.info(f"LLM table selection accepted (similarity={similarity:.2f}): {table_names}")
                    else:
                        logger.info(f"LLM table selection rejected (similarity={similarity:.2f}), falling back to vector search")

            if not table_names:
                logger.info(f"Searching for top {top_k_tables} relevant tables for connection_id={connection_id}")
                relevant_results = await self.vector.search(
                    embedding=prompt_embedding,
                    top_k=top_k_tables * 10,
                    filters={
                        "must": [
                            {"key": "connection_id", "match": {"value": connection_id}},
                            {"key": "type", "match": {"value": "table"}}
                        ]
                    }
                )

                logger.info(f"Vector search returned {len(relevant_results)} results")
                table_names = []
                seen_tables = set()
                for r in relevant_results:
                    table_name = r.get("payload", {}).get("table_name")
                    if table_name and table_name not in seen_tables:
                        table_names.append(table_name)
                        seen_tables.add(table_name)
                        if len(table_names) >= top_k_tables:
                            break

                # If still not enough tables, fallback to mixed table+column search
                if len(table_names) < top_k_tables:
                    mixed_results = await self.vector.search(
                        embedding=prompt_embedding,
                        top_k=top_k_tables * 10,
                        filters={
                            "must": [
                                {"key": "connection_id", "match": {"value": connection_id}}
                            ]
                        }
                    )
                    for r in mixed_results:
                        table_name = r.get("payload", {}).get("table_name")
                        if table_name and table_name not in seen_tables:
                            table_names.append(table_name)
                            seen_tables.add(table_name)
                            if len(table_names) >= top_k_tables:
                                break

            logger.info(f"\n{'='*80}")
            logger.info(f"SELECTED TABLES: {table_names}")
            logger.info(f"Number of tables selected: {len(table_names)}")
            logger.info(f"{'='*80}\n")
            
            if not table_names:
                logger.warning(f"No relevant tables found for prompt: {user_prompt}")
                return {
                    "status": "error",
                    "error": "No relevant tables found for your query",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }

            logger.info(f"Fetching schema for {len(table_names)} relevant tables")
            schema_context = self.metadata.get_column_schema(
                connection_id,
                table_names
            )

            if not schema_context:
                return {
                    "status": "error",
                    "error": "Failed to fetch schema context",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }
            
            logger.info(f"\n{'='*80}")
            logger.info(f"SCHEMA CONTEXT (length: {len(schema_context)} chars):")
            logger.info(f"{'='*80}")
            logger.info(schema_context)
            logger.info(f"{'='*80}\n")

            logger.info(f"\n{'='*80}")
            logger.info("GENERATING SQL WITH OLLAMA")
            logger.info(f"User Prompt: {user_prompt}")
            logger.info(f"{'='*80}\n")
            
            sample_info = "Sample tables available with realistic data patterns"
            
            # Use reasoning mode if enabled (Phase 3 enhancement)
            from app.config import Settings
            settings = Settings()
            use_reasoning = settings.USE_REASONING_MODE
            logger.info(f"USE_REASONING_MODE: {use_reasoning}")
            
            reasoning = ""
            if thread_history:
                # Thread context replaces reasoning — prior queries provide context
                logger.info(f"Thread-aware SQL generation: {len(thread_history)} prior exchanges")
                sql = await self.ollama.generate_sql(
                    user_prompt=user_prompt,
                    schema_context=schema_context,
                    sample_info=sample_info,
                    thread_history=thread_history
                )
            elif use_reasoning:
                logger.info("Using two-step reasoning mode")
                reasoning, sql = await self.ollama.generate_sql_with_reasoning(
                    user_prompt=user_prompt,
                    schema_context=schema_context,
                    sample_info=sample_info
                )
                logger.info(f"\n{'='*80}")
                logger.info(f"FULL REASONING:\n{reasoning}")
                logger.info(f"{'='*80}\n")
            else:
                logger.info("Using direct SQL generation")
                sql = await self.ollama.generate_sql(
                    user_prompt=user_prompt,
                    schema_context=schema_context,
                    sample_info=sample_info
                )

            # Sanitize: replace MySQL-style backticks with PostgreSQL double-quotes
            sql = sql.replace('`', '"')

            logger.info(f"\n{'='*80}")
            logger.info(f"GENERATED SQL:")
            logger.info(f"{'='*80}")
            logger.info(sql)
            logger.info(f"{'='*80}\n")

            async def _regenerate_sql_with_error(error_text: str) -> Optional[str]:
                # Create enhanced schema context with prominent error information
                enhanced_context = (
                    f"!!! CRITICAL ERROR TO FIX !!!\n"
                    f"The previous SQL query failed with this error:\n"
                    f"{error_text}\n\n"
                    f"PREVIOUS SQL THAT FAILED:\n{sql}\n\n"
                    f"ORIGINAL USER QUESTION: {user_prompt}\n\n"
                    f"{'=' * 80}\n"
                    f"AVAILABLE SCHEMA (use ONLY these tables/columns):\n"
                    f"{schema_context}\n"
                    f"{'=' * 80}\n\n"
                    f"INSTRUCTIONS:\n"
                    f"1. If error mentions 'Unknown column': Use ONLY columns shown in COLUMNS section of schema\n"
                    f"2. If error mentions 'Unknown table': Use ONLY tables with '=== TABLE:' headers in schema\n"
                    f"3. Always use table.column format (table-qualified names)\n"
                    f"4. Use GLOBAL FOREIGN KEY RELATIONSHIPS for joins\n"
                    f"5. Every table in SELECT/WHERE/GROUP BY/ORDER BY must be in FROM or JOIN clause\n"
                    f"6. If you JOIN a subquery/CTE, include the join key columns in its SELECT list\n"
                    f"7. For per-entity totals vs average, compute per-entity aggregates first, then compare to AVG of those aggregates\n"
                )
                repair_prompt = f"Fix the failed SQL query to answer: {user_prompt}"
                
                regenerated = await self.ollama.generate_sql(
                    user_prompt=repair_prompt,
                    schema_context=enhanced_context,
                    sample_info=sample_info
                )
                return regenerated.replace('`', '"') if regenerated else None

            identifier_error = self._verify_sql_identifiers(sql, schema_context)
            if identifier_error:
                logger.warning(f"\nIDENTIFIER VALIDATION ERROR: {identifier_error}")
                logger.info(f"Attempting to regenerate SQL...\n")
                regenerated_sql = await _regenerate_sql_with_error(identifier_error)
                if regenerated_sql:
                    logger.info(f"\n{'='*80}")
                    logger.info(f"REGENERATED SQL (after error):")
                    logger.info(f"{'='*80}")
                    logger.info(regenerated_sql)
                    logger.info(f"{'='*80}\n")
                    identifier_error = self._verify_sql_identifiers(regenerated_sql, schema_context)
                    if not identifier_error:
                        sql = regenerated_sql
                if identifier_error:
                    logger.error(f"\nFINAL ERROR - Could not fix identifier issues: {identifier_error}")
                    return {
                        "status": "error",
                        "error": f"Invalid SQL: {identifier_error}",
                        "sql": sql,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "selected_tables": table_names,
                        "schema_context": schema_context
                    }

            logger.info("Validating SQL")
            validation_error = self._validate_sql(sql)
            if validation_error:
                regenerated_sql = await _regenerate_sql_with_error(validation_error)
                if regenerated_sql:
                    validation_error = self._validate_sql(regenerated_sql)
                    if not validation_error:
                        sql = regenerated_sql
                if validation_error:
                    return {
                        "status": "error",
                        "error": f"Invalid SQL: {validation_error}",
                        "sql": sql,
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                        "selected_tables": table_names,
                        "schema_context": schema_context
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
                error_text = result.get("error", "")
                # Attempt a single repair pass using LLM with error context
                should_repair = any(k in error_text for k in [
                    "UndefinedColumn",
                    "UndefinedTable",
                    "AmbiguousColumn",
                    "GroupingError",
                    "CardinalityViolation",
                    "unterminated quoted",
                    "unterminated quoted string",
                    "invalid reference"
                ])
                if should_repair:
                    current_sql = sql
                    current_error = error_text
                    last_retry_result = None

                    for _ in range(2):
                        # Ask LLM to fix the SQL based on error message
                        # Enhance schema context with prominent error information
                        enhanced_context = (
                            f"!!! CRITICAL ERROR TO FIX !!!\n"
                            f"The previous SQL query failed with this error:\n"
                            f"{current_error}\n\n"
                            f"PREVIOUS SQL THAT FAILED:\n{current_sql}\n\n"
                            f"ORIGINAL USER QUESTION: {user_prompt}\n\n"
                            f"{'=' * 80}\n"
                            f"AVAILABLE SCHEMA (use ONLY these tables/columns):\n"
                            f"{schema_context}\n"
                            f"{'=' * 80}\n\n"
                            f"INSTRUCTIONS:\n"
                            f"1. If error mentions 'column does not exist' or 'UndefinedColumn': Use ONLY columns listed in schema above\n"
                            f"2. If error mentions 'missing FROM-clause' or 'UndefinedTable': Add missing table to FROM/JOIN\n"
                            f"3. If error mentions 'ambiguous column': Always use table.column format (never unqualified)\n"
                            f"4. If error mentions 'more than one row' or 'CardinalityViolation': Subquery must return single value, add LIMIT 1 or aggregate\n"
                            f"5. If error mentions 'syntax error': Check SQL syntax carefully, proper parentheses, valid keywords\n"
                            f"6. Use GLOBAL FOREIGN KEY RELATIONSHIPS shown in schema for joins\n"
                            f"7. If you JOIN a subquery/CTE, include the join key columns in its SELECT list\n"
                            f"8. For per-entity totals vs average, compute per-entity aggregates first, then compare to AVG of those aggregates\n"
                        )
                        repair_prompt = f"Fix the failed SQL query to answer: {user_prompt}"

                        regenerated_sql = await self.ollama.generate_sql(
                            user_prompt=repair_prompt,
                            schema_context=enhanced_context,
                            sample_info=sample_info
                        )
                        regenerated_sql = regenerated_sql.replace('`', '"')

                        identifier_error = self._verify_sql_identifiers(regenerated_sql, schema_context)
                        if identifier_error:
                            return {
                                "status": "error",
                                "error": f"Invalid SQL: {identifier_error}",
                                "sql": regenerated_sql,
                                "execution_time_ms": int((time.time() - start_time) * 1000),
                                "selected_tables": table_names,
                                "schema_context": schema_context
                            }
                        validation_error = self._validate_sql(regenerated_sql)
                        if validation_error:
                            return {
                                "status": "error",
                                "error": f"Invalid SQL: {validation_error}",
                                "sql": regenerated_sql,
                                "execution_time_ms": int((time.time() - start_time) * 1000),
                                "selected_tables": table_names,
                                "schema_context": schema_context
                            }

                        last_retry_result = await self._execute_query(
                            connection=connection,
                            sql=regenerated_sql,
                            timeout=timeout
                        )
                        if last_retry_result.get("status") == "success":
                            answer = await self._format_answer(
                                user_prompt=user_prompt,
                                sql=regenerated_sql,
                                rows=last_retry_result["rows"],
                                columns=last_retry_result["columns"],
                                row_count=last_retry_result["row_count"]
                            )
                            return {
                                "status": "success",
                                "answer": answer,
                                "sql": regenerated_sql,
                                "rows": last_retry_result["rows"],
                                "columns": last_retry_result["columns"],
                                "row_count": last_retry_result["row_count"],
                                "execution_time_ms": int((time.time() - start_time) * 1000),
                                "query_time_ms": exec_time
                            }

                        current_sql = regenerated_sql
                        current_error = last_retry_result.get("error", "")

                    if last_retry_result:
                        return {
                            **last_retry_result,
                            "sql": current_sql,
                            "execution_time_ms": int((time.time() - start_time) * 1000),
                            "selected_tables": table_names,
                            "schema_context": schema_context
                        }

                error_response = {
                    **result,
                    "sql": sql,
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                    # Debug info
                    "selected_tables": table_names,
                    "schema_context": schema_context
                }
                logger.info(f"Returning error response with selected_tables={table_names}, schema_context_len={len(schema_context) if schema_context else 0}")
                return error_response

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
                "query_time_ms": exec_time,
                # Debug info
                "selected_tables": table_names,
                "schema_context": schema_context
            }
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": f"Query processing failed: {str(e)}",
                "execution_time_ms": int((time.time() - start_time) * 1000)
            }

    def _format_catalog_answers(self, answers: dict) -> str:
        """Convert catalog answers dict into a human-readable string."""
        parts = []
        for key, value in answers.items():
            if key == "tables":
                parts.append("Tables in database:\n" + "\n".join(f"  - {t}" for t in value))
            elif key.startswith("schema:"):
                tbl = key.split(":", 1)[1]
                col_lines = "\n".join(
                    f"  {c['column_name']} — {c['data_type']}"
                    f"{' (nullable)' if c.get('is_nullable') == 'YES' else ''}"
                    f"{' default: ' + str(c['column_default']) if c.get('column_default') else ''}"
                    for c in value
                )
                parts.append(f"Schema of '{tbl}':\n{col_lines}")
            elif key.startswith("indexes:"):
                tbl = key.split(":", 1)[1]
                idx_lines = "\n".join(
                    f"  {r['indexname']}: ({r['columns']})"
                    for r in value
                )
                parts.append(f"Indexes on '{tbl}':\n{idx_lines}")
            elif key.startswith("primary_key:"):
                tbl = key.split(":", 1)[1]
                if value:
                    parts.append(f"Primary key of '{tbl}': {', '.join(value)}")
                else:
                    parts.append(f"No primary key found on '{tbl}'")
            elif key.startswith("foreign_keys:"):
                tbl = key.split(":", 1)[1]
                if value:
                    fk_lines = "\n".join(
                        f"  {r['column_name']} → {r['foreign_table']}.{r['foreign_column']}"
                        for r in value
                    )
                    parts.append(f"Foreign keys of '{tbl}':\n{fk_lines}")
                else:
                    parts.append(f"No foreign keys found on '{tbl}'")
            elif key.startswith("constraints:"):
                tbl = key.split(":", 1)[1]
                if value:
                    con_lines = "\n".join(
                        f"  [{r['constraint_type']}] {r['constraint_name']}: {r['column_name']}"
                        for r in value
                    )
                    parts.append(f"Constraints on '{tbl}':\n{con_lines}")
                else:
                    parts.append(f"No constraints found on '{tbl}'")
            elif key.startswith("row_count:"):
                tbl = key.split(":", 1)[1]
                parts.append(f"Row count of '{tbl}': {value:,}")
            elif key == "open_connections":
                parts.append(f"Open connections: {value}")
            elif key == "active_queries":
                q_lines = "\n".join(
                    f"  pid={r['pid']} state={r['state']} duration={r['duration']}"
                    for r in value[:5]
                )
                parts.append(f"Active queries:\n{q_lines}")
            elif key == "slow_queries":
                q_lines = "\n".join(
                    f"  pid={r['pid']} duration={r['duration']} query={str(r['query'])[:80]}"
                    for r in value[:5]
                )
                parts.append(f"Slow queries:\n{q_lines}")
            else:
                parts.append(f"{key}:\n{value}")
        return "\n\n".join(parts)

    async def _build_schema_context(
        self,
        connection_id: int,
        table_names: List[str]
    ) -> Optional[str]:
        try:
            context_parts = []
            for table_name in table_names:
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

            # Fetch all known table names for this connection ONCE — shared by all handlers.
            # This powers multi-table detection: any known table name appearing as a whole
            # word in the prompt is treated as an intended target table.
            _known_tables_list = [
                t.name for t in self.db.query(Table).filter(
                    Table.database_id.in_(
                        self.db.query(Database.id).filter(
                            Database.connection_id == connection.id
                        )
                    )
                ).all()
            ]
            _known_tables_set = set(_known_tables_list)
            _prompt_words = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', lower))
            # Tables explicitly mentioned in the prompt (preserves metadata order)
            # Includes simple plural matches (albums -> album, employees -> employee)
            _mentioned_tables = []
            for t in _known_tables_list:
                if t in _prompt_words:
                    _mentioned_tables.append(t)
                    continue
                if t.endswith("y") and f"{t[:-1]}ies" in _prompt_words:
                    _mentioned_tables.append(t)
                    continue
                if f"{t}s" in _prompt_words:
                    _mentioned_tables.append(t)

            _list_tables_phrases = [
                "list tables", "show tables", "all tables", "what tables",
                "list all tables", "show all tables", "tables in the database",
                "tables in this database", "tables in the db"
            ]
            if any(k in lower for k in _list_tables_phrases):
                with engine.connect() as conn:
                    res = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"))
                    tables = [r[0] for r in res.fetchall()]
                result["answers"]["tables"] = tables

            # Detect schema intent broadly (handles singular/plural/describe)
            _schema_intent = re.search(
                r"\bschemas?\b|\bdescribe\b|\bdefinition\b|\bstructure\b",
                lower
            )
            if _schema_intent:
                # Method A: regex findall for explicit 'schema of X' / 'describe X' patterns
                # filtered through known table names to prevent false positives
                regex_tables = [
                    t for t in (
                        (g1 or g2).strip()
                        for g1, g2 in re.findall(
                            r"(?:schema|definition|structure)s?\s+(?:of|for)\s+(?:the\s+)?([a-zA-Z_][a-zA-Z0-9_]*)"
                            r"|describe\s+(?:the\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:table\b)?",
                            lower
                        )
                        if g1 or g2
                    )
                    if t in _known_tables_set
                ]
                # Method B: cross-reference all known table names against whole words
                # in the prompt — catches comma/and-separated multi-table lists
                word_tables = [t for t in _known_tables_list if t in _prompt_words]
                # Union both methods, preserve order, deduplicate
                seen_schema = set()
                schema_tables = []
                for t in regex_tables + word_tables:
                    if t not in seen_schema:
                        seen_schema.add(t)
                        schema_tables.append(t)
                for tbl in schema_tables:
                    with engine.connect() as conn:
                        cols = conn.execute(
                            text("SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position;"),
                            {"t": tbl}
                        ).fetchall()
                    result["answers"][f"schema:{tbl}"] = [dict(r._mapping) for r in cols]

            # INDEXES — multi-table aware
            if re.search(r'\bindexes?\b|\bindices\b', lower) and _mentioned_tables:
                for tbl in _mentioned_tables:
                    with engine.connect() as conn:
                        rows = conn.execute(text("""
                            SELECT i.relname as indexname,
                                   array_to_string(array_agg(a.attname ORDER BY a.attnum), ',') as columns
                            FROM pg_class t
                            JOIN pg_index ix ON t.oid = ix.indrelid
                            JOIN pg_class i  ON i.oid  = ix.indexrelid
                            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                            WHERE t.relname = :t
                            GROUP BY i.relname;
                        """), {"t": tbl}).fetchall()
                    result["answers"][f"indexes:{tbl}"] = [dict(r._mapping) for r in rows]

            # PRIMARY KEY — multi-table aware
            if re.search(r'\bprimary\s+keys?\b', lower) and _mentioned_tables:
                for tbl in _mentioned_tables:
                    with engine.connect() as conn:
                        pk_rows = conn.execute(text("""
                            SELECT kcu.column_name
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                              ON tc.constraint_name = kcu.constraint_name
                             AND tc.table_schema    = kcu.table_schema
                            WHERE tc.constraint_type = 'PRIMARY KEY'
                              AND tc.table_schema    = 'public'
                              AND tc.table_name      = :t
                            ORDER BY kcu.ordinal_position;
                        """), {"t": tbl}).fetchall()
                    result["answers"][f"primary_key:{tbl}"] = [r[0] for r in pk_rows]

            # FOREIGN KEYS — multi-table aware
            if re.search(r'\bforeign\s+keys?\b', lower) and _mentioned_tables:
                for tbl in _mentioned_tables:
                    with engine.connect() as conn:
                        fk_rows = conn.execute(text("""
                            SELECT kcu.column_name,
                                   ccu.table_name  AS foreign_table,
                                   ccu.column_name AS foreign_column
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                              ON tc.constraint_name = kcu.constraint_name
                             AND tc.table_schema    = kcu.table_schema
                            JOIN information_schema.constraint_column_usage ccu
                              ON ccu.constraint_name = tc.constraint_name
                             AND ccu.table_schema    = tc.table_schema
                            WHERE tc.constraint_type = 'FOREIGN KEY'
                              AND tc.table_schema    = 'public'
                              AND tc.table_name      = :t;
                        """), {"t": tbl}).fetchall()
                    result["answers"][f"foreign_keys:{tbl}"] = [dict(r._mapping) for r in fk_rows]

            # ALL CONSTRAINTS — multi-table aware (skip if PK/FK already handled)
            _has_pk_intent = bool(re.search(r'\bprimary\s+keys?\b', lower))
            _has_fk_intent = bool(re.search(r'\bforeign\s+keys?\b', lower))
            if re.search(r'\bconstraints?\b', lower) and not _has_pk_intent and not _has_fk_intent and _mentioned_tables:
                for tbl in _mentioned_tables:
                    with engine.connect() as conn:
                        con_rows = conn.execute(text("""
                            SELECT tc.constraint_name, tc.constraint_type, kcu.column_name
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                              ON tc.constraint_name = kcu.constraint_name
                             AND tc.table_schema    = kcu.table_schema
                            WHERE tc.table_schema = 'public'
                              AND tc.table_name   = :t
                            ORDER BY tc.constraint_type, kcu.ordinal_position;
                        """), {"t": tbl}).fetchall()
                    result["answers"][f"constraints:{tbl}"] = [dict(r._mapping) for r in con_rows]

            # ROW COUNT — multi-table aware
            if re.search(r'\brow\s+count\b|\brow\s+size\b|\btable\s+size\b|\bhow\s+many\s+rows\b', lower) and _mentioned_tables:
                for tbl in _mentioned_tables:
                    with engine.connect() as conn:
                        cnt = conn.execute(text(f'SELECT COUNT(*) FROM "{tbl}"')).scalar()
                    result["answers"][f"row_count:{tbl}"] = int(cnt)

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

    def _verify_sql_identifiers(self, sql: str, schema_context: str) -> Optional[str]:
        """Verify tables and qualified columns exist in schema context."""
        if not sql or not schema_context:
            return None

        table_columns: Dict[str, List[str]] = {}
        current_table = None
        in_columns_section = False
        for line in schema_context.splitlines():
            stripped = line.strip()
            if stripped.startswith("Table:"):
                current_table = stripped.split("Table:", 1)[1].strip()
                table_columns[current_table] = []
                in_columns_section = False
            elif stripped.startswith("=== TABLE:"):
                current_table = stripped.split("=== TABLE:", 1)[1].strip("= ")
                table_columns[current_table] = []
                in_columns_section = False
            elif stripped.startswith("Columns:") or stripped.startswith("COLUMNS:"):
                in_columns_section = True
                # Check if columns are on the same line (old format)
                cols_after = stripped.split(":", 1)[1].strip()
                if cols_after:
                    col_names = []
                    for part in cols_after.split(","):
                        part = part.strip()
                        if not part:
                            continue
                        col_name = part.split("(", 1)[0].strip()
                        if col_name:
                            col_names.append(col_name)
                    if current_table:
                        table_columns[current_table] = col_names
                    in_columns_section = False
            elif in_columns_section and current_table and line and not line[0].isspace() is False:
                # Column definition on separate line (new enhanced format)
                if ":" in stripped and not stripped.startswith("Foreign") and not stripped.startswith("Join"):
                    col_token = stripped.split(":", 1)[0].strip()
                    if col_token and not col_token.startswith("-"):
                        if "." in col_token:
                            table_part, col_part = col_token.split(".", 1)
                            if table_part == current_table:
                                table_columns[current_table].append(col_part)
                        else:
                            table_columns[current_table].append(col_token)
                elif stripped.startswith("Foreign") or stripped.startswith("Join"):
                    in_columns_section = False

        if not table_columns:
            return None

        def _strip_quotes(name: str) -> str:
            return name.strip('"').strip('`')

        alias_map: Dict[str, str] = {}

        for match in re.finditer(r"\bFROM\s+([^\s,]+)(?:\s+(?:AS\s+)?(\w+))?", sql, flags=re.IGNORECASE):
            table_token = match.group(1)
            alias = match.group(2)
            if table_token.startswith("("):
                continue
            table_name = _strip_quotes(table_token.split(".")[-1])
            if alias:
                alias_map[alias] = table_name

        for match in re.finditer(r"\bJOIN\s+([^\s,]+)(?:\s+(?:AS\s+)?(\w+))?", sql, flags=re.IGNORECASE):
            table_token = match.group(1)
            alias = match.group(2)
            if table_token.startswith("("):
                continue
            table_name = _strip_quotes(table_token.split(".")[-1])
            if alias:
                alias_map[alias] = table_name

        for match in re.finditer(r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\b", sql):
            table_token = match.group(1)
            col_token = match.group(2)
            table_name = alias_map.get(table_token, table_token)
            if table_name not in table_columns:
                continue
            if col_token not in table_columns[table_name]:
                return f"Unknown column '{table_token}.{col_token}'"

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

    async def execute_query(
        self,
        connection_id: int,
        sql: str,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute a SQL query on a connected database
        
        Args:
            connection_id: ID of the database connection
            sql: SQL query to execute
            timeout: Query timeout in seconds
        
        Returns:
            Dictionary with success status, columns, rows, and execution time
        """
        start_time = time.time()
        
        try:
            # Validate SQL - only SELECT allowed
            sql_upper = sql.strip().upper()
            if not sql_upper.startswith('SELECT'):
                return {
                    "success": False,
                    "error": "Only SELECT queries are allowed",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }
            
            # Get connection from database
            connection = self.db.query(Connection).filter(
                Connection.id == connection_id,
                Connection.is_active == True
            ).first()
            
            if not connection:
                return {
                    "success": False,
                    "error": f"Connection {connection_id} not found or inactive",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }
            
            # Build connection string
            if connection.database_type.lower() == "postgres":
                conn_string = f"postgresql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}"
            elif connection.database_type.lower() == "mysql":
                conn_string = f"mysql+pymysql://{connection.username}:{connection.password}@{connection.host}:{connection.port}/{connection.database}"
            else:
                return {
                    "success": False,
                    "error": f"Unsupported database type: {connection.database_type}",
                    "execution_time_ms": int((time.time() - start_time) * 1000)
                }
            
            # Execute query
            exec_start = time.time()
            engine = create_engine(
                conn_string,
                poolclass=NullPool,
                connect_args={"connect_timeout": timeout} if connection.database_type.lower() == "postgres" else {}
            )
            
            logger.info(f"Executing query on {connection.database_type} database")
            with engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = result.fetchall()
                columns = list(result.keys())
                
                # Convert rows to dictionaries
                rows_as_dicts = [dict(zip(columns, row)) for row in rows]
            
            engine.dispose()
            exec_time = int((time.time() - exec_start) * 1000)
            
            # Add column metadata
            columns_with_type = [{"name": col, "type": "string"} for col in columns]
            
            logger.info(f"Query executed in {exec_time}ms, returned {len(rows_as_dicts)} rows")
            
            return {
                "success": True,
                "columns": columns_with_type,
                "rows": rows_as_dicts,
                "row_count": len(rows_as_dicts),
                "execution_time_ms": exec_time
            }
        
        except Exception as e:
            logger.error(f"Error executing query: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": f"Query execution failed: {str(e)}",
                "execution_time_ms": int((time.time() - start_time) * 1000)
            }

    def _extract_tables_from_sql(self, sql: str) -> list:
        """Extract table names from a SQL query (best effort)."""
        tables = set()
        pattern = r'(?:FROM|JOIN)\s+"?(\w+)"?'
        for match in re.finditer(pattern, sql, re.IGNORECASE):
            tables.add(match.group(1))
        return list(tables)

    def close(self):
        if self.db:
            self.db.close()
        if self.metadata:
            self.metadata.close()

    def __del__(self):
        self.close()