"""Chat service - Main orchestration for natural language queries"""

import logging
import time
import uuid
import re
from typing import Dict, List, Any, Optional
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.pool import NullPool

from app.services.ollama_service import OllamaService
from app.services.vector_service import VectorService
from app.services.metadata_service import MetadataService
from app.services.schema_service import SchemaExtractor
from app.database import SessionLocal
from app.models import Connection, Database, Table, Column
from app.config import Settings

logger = logging.getLogger(__name__)

_settings = Settings()

# ── Tunable constants ─────────────────────────────────────
MAX_RESULT_ROWS = 5000
SIMILARITY_THRESHOLD = 0.35
MAX_REPAIR_ATTEMPTS = 2
VECTOR_SEARCH_MULTIPLIER = 10
ENGINE_CACHE_TTL = 3600
MAX_PROMPT_LENGTH = 10_000

NOSQL_TYPES = frozenset({
    "mongodb", "mongo", "redis", "elasticsearch", "elastic", "es", "neo4j",
})

FORBIDDEN_SQL_COMMANDS = ("DELETE", "DROP", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "CREATE")

_STRUCTURAL_KEYWORDS = (
    "schema", "schemas", "describe", "definition", "indexes", "indices", "ddl",
    "structure of", "columns of", "primary key", "primary keys",
    "foreign key", "foreign keys", "constraints",
    "row count", "row size", "table size", "how many rows",
    "list tables", "show tables", "all tables", "what tables",
    "list all tables", "show all tables",
)

_LIST_TABLES_PHRASES = (
    "list tables", "show tables", "all tables", "what tables",
    "list all tables", "show all tables", "tables in the database",
    "tables in this database", "tables in the db",
)

_REPAIRABLE_ERROR_MARKERS = (
    "UndefinedColumn", "UndefinedTable", "AmbiguousColumn",
    "GroupingError", "CardinalityViolation",
    "unterminated quoted", "unterminated quoted string",
    "invalid reference",
)

# ── Engine cache with TTL ─────────────────────────────────
_engine_cache: Dict[int, Any] = {}
_engine_cache_ts: Dict[int, float] = {}


def _get_engine(connection: "Connection", timeout: int = 30):
    """Get or create a cached SQLAlchemy engine, with TTL eviction."""
    cache_key = connection.id
    now = time.time()

    if cache_key in _engine_cache:
        if (now - _engine_cache_ts.get(cache_key, 0)) < ENGINE_CACHE_TTL:
            return _engine_cache[cache_key]
        try:
            _engine_cache[cache_key].dispose()
        except Exception:
            pass
        del _engine_cache[cache_key]
        _engine_cache_ts.pop(cache_key, None)

    conn_string = SchemaExtractor.build_connection_string(
        connection.database_type, connection.host, connection.port,
        connection.username, connection.password, connection.database,
    )
    dt = connection.database_type.lower()
    connect_args = {}
    if dt in ("postgres", "postgresql"):
        connect_args = {"connect_timeout": timeout}
    elif dt == "sqlite":
        connect_args = {"timeout": timeout}

    engine = create_engine(conn_string, poolclass=NullPool, connect_args=connect_args)
    _engine_cache[cache_key] = engine
    _engine_cache_ts[cache_key] = now
    return engine


def evict_engine(connection_id: int):
    """Explicitly remove a cached engine (call after credentials change)."""
    eng = _engine_cache.pop(connection_id, None)
    _engine_cache_ts.pop(connection_id, None)
    if eng:
        try:
            eng.dispose()
        except Exception:
            pass


def _sanitize_backticks(raw_sql: str, db_dialect: str) -> str:
    """Replace backticks with double-quotes unless dialect is MySQL."""
    if db_dialect in ("mysql",):
        return raw_sql
    return raw_sql.replace("`", '"')


class ChatService:
    """Main chat orchestration service"""

    def __init__(self):
        self.ollama = OllamaService()
        self.vector = VectorService()
        self.metadata = MetadataService()
        self.db = SessionLocal()
        self._closed = False

    # ── Public entry point ────────────────────────────────

    async def process_query(
        self,
        connection_id: int,
        user_prompt: str,
        top_k_tables: int = 5,
        timeout: int = 30,
        thread_history: list = None,
        user_id: int = None,
    ) -> Dict[str, Any]:
        qid = uuid.uuid4().hex[:8]
        start_time = time.time()

        # ── Input validation ──
        if not user_prompt or not user_prompt.strip():
            return {"status": "error", "error": "Query prompt cannot be empty",
                    "execution_time_ms": 0}
        user_prompt = user_prompt.strip()
        if len(user_prompt) > MAX_PROMPT_LENGTH:
            return {"status": "error",
                    "error": f"Query prompt exceeds maximum length ({MAX_PROMPT_LENGTH} chars)",
                    "execution_time_ms": 0}

        try:
            logger.info("[%s] query start  conn=%d  prompt=%.80s",
                        qid, connection_id, user_prompt)

            connection = self.db.query(Connection).filter(
                Connection.id == connection_id,
                Connection.is_active.is_(True),
            ).first()
            if not connection:
                logger.warning("[%s] Connection %d not found or inactive", qid, connection_id)
                return {
                    "status": "error",
                    "error": f"Connection {connection_id} not found or inactive",
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                }

            db_dialect = connection.database_type.lower()

            # ── NoSQL routing ──
            if db_dialect in NOSQL_TYPES:
                logger.info("[%s] Routing to NoSQL handler (%s)", qid, db_dialect)
                return await self._handle_nosql_query(connection, user_prompt)

            # ── Intent classification ──
            lower_prompt = user_prompt.lower()
            if any(kw in lower_prompt for kw in _STRUCTURAL_KEYWORDS):
                intent = "catalog"
                logger.info("[%s] intent=catalog (keyword match)", qid)
            else:
                intent = await self.ollama.classify_intent(user_prompt)
                logger.info("[%s] intent=%s (LLM)", qid, intent)

            if intent == "catalog":
                catalog_result = await self._handle_catalog_query(connection, user_prompt)
                if catalog_result.get("status") == "error":
                    logger.warning("[%s] Catalog handler error, falling back to data path: %s",
                                   qid, catalog_result.get("error", "unknown"))
                elif catalog_result.get("answers"):
                    elapsed = int((time.time() - start_time) * 1000)
                    logger.info("[%s] query done  type=catalog  elapsed=%dms", qid, elapsed)
                    return {
                        "status": "success",
                        "answer": self._format_catalog_answers(catalog_result["answers"]),
                        "sql": None, "rows": None, "columns": None,
                        "row_count": None,
                        "execution_time_ms": elapsed,
                        "query_time_ms": None,
                    }
                else:
                    logger.info("[%s] Catalog returned no answers, falling back to data path", qid)

            # ── Table selection ──
            embed_start = time.time()
            prompt_embedding = await self.ollama.embed_text(user_prompt)
            logger.debug("[%s] Embedding took %dms", qid,
                         int((time.time() - embed_start) * 1000))

            table_names = await self._select_tables(
                qid, user_prompt, prompt_embedding, connection_id, top_k_tables,
            )
            if not table_names:
                logger.warning("[%s] No relevant tables found", qid)
                return {
                    "status": "error",
                    "error": "No relevant tables found for your query",
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                }

            # ── Table-level access filtering ──
            if user_id:
                table_names = self._filter_tables_by_access(
                    user_id, connection_id, table_names, qid,
                )
                if not table_names:
                    return {
                        "status": "error",
                        "error": "You don't have access to the tables needed for this query. Contact your admin.",
                        "execution_time_ms": int((time.time() - start_time) * 1000),
                    }

            logger.info("[%s] selected %d tables: %s", qid, len(table_names), table_names)

            # ── Schema context ──
            schema_context = self.metadata.get_column_schema(connection_id, table_names)
            if not schema_context:
                logger.error("[%s] Schema context empty for tables %s", qid, table_names)
                return {
                    "status": "error",
                    "error": "Failed to fetch schema context for the selected tables",
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                }
            logger.debug("[%s] Schema context: %d chars", qid, len(schema_context))

            # ── Enrich with semantic knowledge (glossary + entity graph + corrections) ──
            try:
                from app.services.semantic_graph_service import SemanticGraphService
                sem_db = SessionLocal()
                try:
                    sem = SemanticGraphService(sem_db)
                    glossary_ctx = sem.build_glossary_context(connection_id)
                    entity_ctx = sem.build_entity_context(connection_id)
                    corrections_ctx = sem.build_corrections_context(connection_id, user_prompt)
                    extra_ctx = "\n\n".join(
                        part for part in (glossary_ctx, entity_ctx, corrections_ctx) if part
                    )
                    if extra_ctx:
                        schema_context = schema_context + "\n\n" + extra_ctx
                        logger.debug("[%s] Enriched schema with %d chars of semantic context",
                                     qid, len(extra_ctx))
                finally:
                    sem_db.close()
            except Exception as e:
                logger.debug("[%s] Semantic enrichment skipped: %s", qid, e)

            # ── SQL generation ──
            sql, reasoning, llm_ms = await self._generate_sql(
                qid, user_prompt, schema_context, db_dialect, thread_history,
            )
            sql = _sanitize_backticks(sql, db_dialect)
            logger.debug("[%s] Generated SQL (%dms): %s", qid, llm_ms, sql)

            # ── Pre-execution validation with single repair attempt ──
            sample_info = "Sample tables available with realistic data patterns"
            sql, pre_error = await self._pre_validate(
                qid, sql, schema_context, user_prompt, sample_info, db_dialect,
            )
            if pre_error:
                return {
                    "status": "error",
                    "error": f"Invalid SQL: {pre_error}",
                    "sql": sql,
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                    "selected_tables": table_names,
                }

            # ── Execute ──
            exec_start = time.time()
            result = await self._execute_query(connection, sql, timeout)
            exec_ms = int((time.time() - exec_start) * 1000)

            if result.get("status") == "error":
                repaired = await self._repair_loop(
                    qid, sql, result.get("error", ""), schema_context,
                    user_prompt, sample_info, db_dialect, connection, timeout,
                )
                if repaired:
                    answer = await self._format_answer(
                        user_prompt, repaired["sql"],
                        repaired["rows"], repaired["columns"], repaired["row_count"],
                    )
                    elapsed = int((time.time() - start_time) * 1000)
                    logger.info(
                        "[%s] query done  type=data(repaired)  rows=%d  "
                        "llm=%dms  exec=%dms  total=%dms",
                        qid, repaired["row_count"], llm_ms,
                        repaired["exec_ms"], elapsed,
                    )
                    return {
                        "status": "success", "answer": answer,
                        "sql": repaired["sql"],
                        "rows": repaired["rows"], "columns": repaired["columns"],
                        "row_count": repaired["row_count"],
                        "execution_time_ms": elapsed,
                        "query_time_ms": repaired["exec_ms"],
                        "selected_tables": table_names,
                    }
                return {
                    **result, "sql": sql,
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                    "selected_tables": table_names,
                }

            # ── Format answer ──
            answer = await self._format_answer(
                user_prompt, sql, result["rows"], result["columns"], result["row_count"],
            )
            elapsed = int((time.time() - start_time) * 1000)
            logger.info(
                "[%s] query done  type=data  rows=%d  llm=%dms  exec=%dms  total=%dms",
                qid, result["row_count"], llm_ms, exec_ms, elapsed,
            )
            return {
                "status": "success", "answer": answer, "sql": sql,
                "rows": result["rows"], "columns": result["columns"],
                "row_count": result["row_count"],
                "execution_time_ms": elapsed,
                "query_time_ms": exec_ms,
                "selected_tables": table_names,
            }

        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            logger.error("[%s] Unhandled error after %dms: %s", qid, elapsed, e, exc_info=True)
            return {
                "status": "error",
                "error": f"Query processing failed: {str(e)}",
                "execution_time_ms": elapsed,
            }

    # ── Table access control ─────────────────────────────

    def _filter_tables_by_access(
        self, user_id: int, connection_id: int,
        table_names: List[str], qid: str,
    ) -> List[str]:
        """Filter table list by the user's TableAccess allowlist.

        If no rows exist for this user+connection, all tables are allowed.
        """
        from app.models import TableAccess
        rows = (
            self.db.query(TableAccess.table_name)
            .filter(
                TableAccess.user_id == user_id,
                TableAccess.connection_id == connection_id,
            )
            .all()
        )
        if not rows:
            return table_names

        allowed = {r[0] for r in rows}
        filtered = [t for t in table_names if t in allowed]
        if len(filtered) < len(table_names):
            blocked = set(table_names) - allowed
            logger.info("[%s] Table access filter: blocked %s for user %d",
                        qid, blocked, user_id)
        return filtered

    # ── Table selection helpers ────────────────────────────

    async def _select_tables(
        self, qid: str, user_prompt: str, prompt_embedding: list,
        connection_id: int, top_k: int,
    ) -> List[str]:
        """Select relevant tables via LLM identification with vector fallback."""
        table_summaries = self.metadata.get_table_summaries(connection_id)

        if table_summaries:
            allowed = {t["name"] for t in table_summaries}
            identified = await self.ollama.identify_tables(user_prompt, table_summaries)
            identified = [t for t in identified if t in allowed][:max(top_k, 5)]
            if identified:
                summary_text = "\n".join(
                    t["summary"] for t in table_summaries if t["name"] in identified
                )
                sim = await self.ollama.verify_intent_similarity(
                    prompt_embedding, summary_text,
                )
                if sim >= SIMILARITY_THRESHOLD:
                    logger.debug("[%s] LLM table selection accepted (sim=%.2f)", qid, sim)
                    return identified
                logger.debug("[%s] LLM table selection rejected (sim=%.2f)", qid, sim)

        return await self._vector_table_search(qid, prompt_embedding, connection_id, top_k)

    async def _vector_table_search(
        self, qid: str, embedding: list, connection_id: int, top_k: int,
    ) -> List[str]:
        """Fallback table selection via vector similarity search."""
        table_names: List[str] = []
        seen: set = set()

        results = await self.vector.search(
            embedding=embedding,
            top_k=top_k * VECTOR_SEARCH_MULTIPLIER,
            filters={"must": [
                {"key": "connection_id", "match": {"value": connection_id}},
                {"key": "type", "match": {"value": "table"}},
            ]},
        )
        logger.debug("[%s] Vector search (table-only) returned %d hits", qid, len(results))

        for r in results:
            tbl = r.get("payload", {}).get("table_name")
            if tbl and tbl not in seen:
                table_names.append(tbl)
                seen.add(tbl)
                if len(table_names) >= top_k:
                    return table_names

        # Broaden to mixed table+column embeddings if not enough
        if len(table_names) < top_k:
            mixed = await self.vector.search(
                embedding=embedding,
                top_k=top_k * VECTOR_SEARCH_MULTIPLIER,
                filters={"must": [
                    {"key": "connection_id", "match": {"value": connection_id}},
                ]},
            )
            for r in mixed:
                tbl = r.get("payload", {}).get("table_name")
                if tbl and tbl not in seen:
                    table_names.append(tbl)
                    seen.add(tbl)
                    if len(table_names) >= top_k:
                        break

        return table_names

    # ── SQL generation ────────────────────────────────────

    async def _generate_sql(
        self, qid: str, user_prompt: str, schema_context: str,
        db_dialect: str, thread_history: list = None,
    ) -> tuple:
        """Generate SQL via LLM.  Returns (sql, reasoning, llm_time_ms)."""
        sample_info = "Sample tables available with realistic data patterns"
        use_reasoning = _settings.USE_REASONING_MODE
        reasoning = ""

        llm_start = time.time()
        if thread_history:
            logger.debug("[%s] Thread-aware generation (%d prior turns)", qid, len(thread_history))
            sql = await self.ollama.generate_sql(
                user_prompt=user_prompt, schema_context=schema_context,
                sample_info=sample_info, thread_history=thread_history,
                db_dialect=db_dialect,
            )
        elif use_reasoning:
            reasoning, sql = await self.ollama.generate_sql_with_reasoning(
                user_prompt=user_prompt, schema_context=schema_context,
                sample_info=sample_info,
            )
            logger.debug("[%s] Reasoning: %.300s", qid, reasoning)
        else:
            sql = await self.ollama.generate_sql(
                user_prompt=user_prompt, schema_context=schema_context,
                sample_info=sample_info, db_dialect=db_dialect,
            )

        llm_ms = int((time.time() - llm_start) * 1000)
        return sql, reasoning, llm_ms

    # ── Validation & repair ───────────────────────────────

    async def _pre_validate(
        self, qid: str, sql: str, schema_context: str,
        user_prompt: str, sample_info: str, db_dialect: str,
    ) -> tuple:
        """Run identifier + safety checks with one repair attempt each.

        Returns (possibly_fixed_sql, error_or_None).
        """
        # Identifier check
        id_error = self._verify_sql_identifiers(sql, schema_context)
        if id_error:
            logger.warning("[%s] Identifier error: %s — attempting repair", qid, id_error)
            fixed = await self._regenerate_sql(
                sql, id_error, user_prompt, schema_context, sample_info, db_dialect,
            )
            if fixed:
                fixed = _sanitize_backticks(fixed, db_dialect)
                new_err = self._verify_sql_identifiers(fixed, schema_context)
                if not new_err:
                    sql = fixed
                    id_error = None
                else:
                    id_error = new_err
            if id_error:
                logger.error("[%s] Could not fix identifier issues: %s", qid, id_error)
                return sql, id_error

        # Safety check
        val_error = self._validate_sql(sql)
        if val_error:
            logger.warning("[%s] Validation error: %s — attempting repair", qid, val_error)
            fixed = await self._regenerate_sql(
                sql, val_error, user_prompt, schema_context, sample_info, db_dialect,
            )
            if fixed:
                fixed = _sanitize_backticks(fixed, db_dialect)
                if not self._validate_sql(fixed):
                    sql = fixed
                    val_error = None
            if val_error:
                return sql, val_error

        return sql, None

    async def _regenerate_sql(
        self, failed_sql: str, error_text: str, user_prompt: str,
        schema_context: str, sample_info: str, db_dialect: str,
    ) -> Optional[str]:
        """Ask the LLM to fix a failed SQL query."""
        enhanced_context = (
            "!!! CRITICAL ERROR TO FIX !!!\n"
            f"The previous SQL query failed with this error:\n"
            f"{error_text}\n\n"
            f"PREVIOUS SQL THAT FAILED:\n{failed_sql}\n\n"
            f"ORIGINAL USER QUESTION: {user_prompt}\n\n"
            f"AVAILABLE SCHEMA (use ONLY these tables/columns):\n"
            f"{schema_context}\n\n"
            "INSTRUCTIONS:\n"
            "1. If error mentions 'Unknown column': Use ONLY columns shown in schema\n"
            "2. If error mentions 'Unknown table': Use ONLY tables in schema\n"
            "3. Always use table.column format (table-qualified names)\n"
            "4. Use GLOBAL FOREIGN KEY RELATIONSHIPS for joins\n"
            "5. Every table in SELECT/WHERE/GROUP BY/ORDER BY must be in FROM or JOIN\n"
            "6. If you JOIN a subquery/CTE, include join key columns in its SELECT\n"
            "7. For per-entity totals vs average, compute per-entity aggregates first\n"
            "8. If 'more than one row' or 'CardinalityViolation': add LIMIT 1 or aggregate\n"
            "9. If 'syntax error': check parentheses, valid keywords, proper quoting\n"
        )
        return await self.ollama.generate_sql(
            user_prompt=f"Fix the failed SQL query to answer: {user_prompt}",
            schema_context=enhanced_context,
            sample_info=sample_info,
            db_dialect=db_dialect,
        )

    async def _repair_loop(
        self, qid: str, original_sql: str, error_text: str,
        schema_context: str, user_prompt: str, sample_info: str,
        db_dialect: str, connection: Connection, timeout: int,
    ) -> Optional[Dict[str, Any]]:
        """Try to repair a failed SQL query up to MAX_REPAIR_ATTEMPTS times.

        Returns dict with sql/rows/columns/row_count/exec_ms on success, None on failure.
        """
        if not any(marker in error_text for marker in _REPAIRABLE_ERROR_MARKERS):
            return None

        current_sql = original_sql
        current_error = error_text

        for attempt in range(MAX_REPAIR_ATTEMPTS):
            logger.info("[%s] Repair attempt %d/%d", qid, attempt + 1, MAX_REPAIR_ATTEMPTS)

            regenerated = await self._regenerate_sql(
                current_sql, current_error, user_prompt,
                schema_context, sample_info, db_dialect,
            )
            if not regenerated:
                break

            regenerated = _sanitize_backticks(regenerated, db_dialect)

            id_err = self._verify_sql_identifiers(regenerated, schema_context)
            if id_err:
                current_sql, current_error = regenerated, id_err
                continue

            val_err = self._validate_sql(regenerated)
            if val_err:
                current_sql, current_error = regenerated, val_err
                continue

            retry_start = time.time()
            result = await self._execute_query(connection, regenerated, timeout)
            retry_ms = int((time.time() - retry_start) * 1000)

            if result.get("status") == "success":
                logger.info("[%s] Repair succeeded on attempt %d", qid, attempt + 1)
                return {
                    "sql": regenerated,
                    "rows": result["rows"],
                    "columns": result["columns"],
                    "row_count": result["row_count"],
                    "exec_ms": retry_ms,
                }

            current_sql = regenerated
            current_error = result.get("error", "")

        logger.warning("[%s] All %d repair attempts exhausted", qid, MAX_REPAIR_ATTEMPTS)
        return None

    # ── Catalog queries ───────────────────────────────────

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
                    f"  {r['indexname']}: ({r['columns']})" for r in value
                )
                parts.append(f"Indexes on '{tbl}':\n{idx_lines}")
            elif key.startswith("primary_key:"):
                tbl = key.split(":", 1)[1]
                parts.append(
                    f"Primary key of '{tbl}': {', '.join(value)}"
                    if value else f"No primary key found on '{tbl}'"
                )
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
        table_names: List[str],
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
                    Table.name == table_name,
                ).first()
                if not table:
                    continue
                columns = self.db.query(Column).filter(
                    Column.table_id == table.id
                ).all()
                col_descriptions = ", ".join(
                    f"{c.name} ({c.data_type}{' ? nullable' if c.is_nullable else ''})"
                    for c in columns
                )
                context_parts.append(
                    f"Table: {table_name}\nColumns: {col_descriptions}"
                )
            return "\n\n".join(context_parts) if context_parts else None
        except Exception as e:
            logger.error("Error building schema context: %s", e, exc_info=True)
            return None

    async def _handle_catalog_query(self, connection: Connection, prompt: str) -> Dict[str, Any]:
        """Handle catalog/introspection queries using SQLAlchemy inspector."""
        try:
            engine = _get_engine(connection, timeout=10)
            dt = connection.database_type.lower()
            is_pg = dt in ("postgres", "postgresql")

            lower = prompt.lower()
            result: Dict[str, Any] = {"status": "success", "type": "catalog", "answers": {}}

            known_tables_list = [
                t.name for t in self.db.query(Table).filter(
                    Table.database_id.in_(
                        self.db.query(Database.id).filter(
                            Database.connection_id == connection.id
                        )
                    )
                ).all()
            ]
            known_set = set(known_tables_list)
            prompt_words = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', lower))

            mentioned_tables: List[str] = []
            for t in known_tables_list:
                if t in prompt_words:
                    mentioned_tables.append(t)
                elif t.endswith("y") and f"{t[:-1]}ies" in prompt_words:
                    mentioned_tables.append(t)
                elif f"{t}s" in prompt_words:
                    mentioned_tables.append(t)

            with engine.connect() as conn:
                insp = inspect(engine)

                if any(k in lower for k in _LIST_TABLES_PHRASES):
                    result["answers"]["tables"] = sorted(insp.get_table_names())

                schema_intent = re.search(
                    r"\bschemas?\b|\bdescribe\b|\bdefinition\b|\bstructure\b", lower,
                )
                if schema_intent:
                    regex_tables = [
                        t for t in (
                            (g1 or g2).strip()
                            for g1, g2 in re.findall(
                                r"(?:schema|definition|structure)s?\s+(?:of|for)\s+(?:the\s+)?"
                                r"([a-zA-Z_][a-zA-Z0-9_]*)"
                                r"|describe\s+(?:the\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:table\b)?",
                                lower,
                            ) if g1 or g2
                        ) if t in known_set
                    ]
                    word_tables = [t for t in known_tables_list if t in prompt_words]
                    seen_schema: set = set()
                    schema_tables: List[str] = []
                    for t in regex_tables + word_tables:
                        if t not in seen_schema:
                            seen_schema.add(t)
                            schema_tables.append(t)
                    for tbl in schema_tables:
                        cols = insp.get_columns(tbl)
                        result["answers"][f"schema:{tbl}"] = [
                            {
                                "column_name": c["name"],
                                "data_type": str(c["type"]),
                                "is_nullable": "YES" if c.get("nullable") else "NO",
                                "column_default": (
                                    str(c.get("default", "")) if c.get("default") else None
                                ),
                            }
                            for c in cols
                        ]

                if re.search(r'\bindexes?\b|\bindices\b', lower) and mentioned_tables:
                    for tbl in mentioned_tables:
                        indexes = insp.get_indexes(tbl)
                        result["answers"][f"indexes:{tbl}"] = [
                            {"indexname": idx["name"],
                             "columns": ",".join(idx.get("column_names", []))}
                            for idx in indexes
                        ]

                if re.search(r'\bprimary\s+keys?\b', lower) and mentioned_tables:
                    for tbl in mentioned_tables:
                        pk = insp.get_pk_constraint(tbl) or {}
                        result["answers"][f"primary_key:{tbl}"] = pk.get("constrained_columns", [])

                if re.search(r'\bforeign\s+keys?\b', lower) and mentioned_tables:
                    for tbl in mentioned_tables:
                        fks = insp.get_foreign_keys(tbl)
                        result["answers"][f"foreign_keys:{tbl}"] = [
                            {
                                "column_name": (
                                    fk["constrained_columns"][0]
                                    if fk["constrained_columns"] else ""
                                ),
                                "foreign_table": fk["referred_table"],
                                "foreign_column": (
                                    fk["referred_columns"][0]
                                    if fk["referred_columns"] else ""
                                ),
                            }
                            for fk in fks
                        ]

                has_pk = bool(re.search(r'\bprimary\s+keys?\b', lower))
                has_fk = bool(re.search(r'\bforeign\s+keys?\b', lower))
                if re.search(r'\bconstraints?\b', lower) and not has_pk and not has_fk and mentioned_tables:
                    for tbl in mentioned_tables:
                        constraints: List[Dict] = []
                        pk = insp.get_pk_constraint(tbl) or {}
                        for col in pk.get("constrained_columns", []):
                            constraints.append({
                                "constraint_type": "PRIMARY KEY",
                                "constraint_name": pk.get("name", ""),
                                "column_name": col,
                            })
                        for fk in insp.get_foreign_keys(tbl):
                            for col in fk.get("constrained_columns", []):
                                constraints.append({
                                    "constraint_type": "FOREIGN KEY",
                                    "constraint_name": fk.get("name", ""),
                                    "column_name": col,
                                })
                        if hasattr(insp, "get_unique_constraints"):
                            for uq in insp.get_unique_constraints(tbl):
                                for col in uq.get("column_names", []):
                                    constraints.append({
                                        "constraint_type": "UNIQUE",
                                        "constraint_name": uq.get("name", ""),
                                        "column_name": col,
                                    })
                        result["answers"][f"constraints:{tbl}"] = constraints

                if (re.search(r'\brow\s+count\b|\brow\s+size\b|\btable\s+size\b|\bhow\s+many\s+rows\b', lower)
                        and mentioned_tables):
                    for tbl in mentioned_tables:
                        cnt = conn.execute(text(f'SELECT COUNT(*) FROM "{tbl}"')).scalar()
                        result["answers"][f"row_count:{tbl}"] = int(cnt)

                # PostgreSQL-specific monitoring
                if is_pg and any(k in lower for k in ("open connections", "connections", "active connections")):
                    cnt = conn.execute(text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database();"
                    )).scalar()
                    act = conn.execute(text(
                        "SELECT pid, usename, state, now() - query_start AS duration, query "
                        "FROM pg_stat_activity WHERE datname = current_database() "
                        "ORDER BY now() - query_start DESC LIMIT 10;"
                    )).fetchall()
                    result["answers"]["open_connections"] = int(cnt)
                    result["answers"]["active_queries"] = [dict(r._mapping) for r in act]

                if is_pg and any(k in lower for k in ("slow queries", "slow query", "long running", "long-running")):
                    slow = conn.execute(text(
                        "SELECT pid, usename, state, now() - query_start AS duration, query "
                        "FROM pg_stat_activity WHERE state = 'active' "
                        "AND datname = current_database() "
                        "ORDER BY now() - query_start DESC LIMIT 10;"
                    )).fetchall()
                    result["answers"]["slow_queries"] = [dict(r._mapping) for r in slow]

            return result

        except Exception as e:
            logger.error("Catalog query failed: %s", e, exc_info=True)
            return {"status": "error", "error": str(e)}

    # ── SQL validation ────────────────────────────────────

    def _validate_sql(self, sql: str) -> Optional[str]:
        if not sql:
            return "SQL is empty"
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT"):
            return "Only SELECT queries are allowed"
        for cmd in FORBIDDEN_SQL_COMMANDS:
            if re.search(rf'\b{cmd}\b', sql_upper):
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
                cols_after = stripped.split(":", 1)[1].strip()
                if cols_after:
                    for part in cols_after.split(","):
                        part = part.strip()
                        if part:
                            col_name = part.split("(", 1)[0].strip()
                            if col_name and current_table:
                                table_columns[current_table].append(col_name)
                    in_columns_section = False
            elif in_columns_section and current_table and stripped:
                if stripped.startswith("="):
                    in_columns_section = False
                elif stripped.startswith("Foreign") or stripped.startswith("Join"):
                    in_columns_section = False
                elif ":" in stripped:
                    col_token = stripped.split(":", 1)[0].strip()
                    if col_token and not col_token.startswith("-"):
                        if "." in col_token:
                            _, col_part = col_token.split(".", 1)
                            if current_table:
                                table_columns[current_table].append(col_part)
                        else:
                            table_columns[current_table].append(col_token)

        if not table_columns:
            return None

        def _strip_quotes(name: str) -> str:
            return name.strip('"').strip("`")

        alias_map: Dict[str, str] = {}

        for match in re.finditer(
            r"\bFROM\s+([^\s,]+)(?:\s+(?:AS\s+)?(\w+))?", sql, flags=re.IGNORECASE,
        ):
            table_token = match.group(1)
            alias = match.group(2)
            if table_token.startswith("("):
                continue
            table_name = _strip_quotes(table_token.split(".")[-1])
            if alias:
                alias_map[alias] = table_name

        for match in re.finditer(
            r"\bJOIN\s+([^\s,]+)(?:\s+(?:AS\s+)?(\w+))?", sql, flags=re.IGNORECASE,
        ):
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

    # ── Query execution ───────────────────────────────────

    async def _execute_query(
        self, connection: Connection, sql: str, timeout: int = 30,
    ) -> Dict[str, Any]:
        exec_start = time.time()
        try:
            engine = _get_engine(connection, timeout)
            logger.debug("Executing on %s (conn=%d)", connection.database_type, connection.id)

            with engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = result.fetchmany(MAX_RESULT_ROWS + 1)
                columns = list(result.keys())
                truncated = len(rows) > MAX_RESULT_ROWS
                if truncated:
                    rows = rows[:MAX_RESULT_ROWS]
                rows_as_dicts = [dict(zip(columns, list(row))) for row in rows]

            exec_ms = int((time.time() - exec_start) * 1000)
            logger.debug("Query returned %d rows in %dms%s",
                         len(rows_as_dicts), exec_ms,
                         " (TRUNCATED)" if truncated else "")
            return {
                "status": "success",
                "rows": rows_as_dicts,
                "columns": columns,
                "row_count": len(rows_as_dicts),
                "execution_time_ms": exec_ms,
                "truncated": truncated,
            }
        except ValueError:
            return {
                "status": "error",
                "error": f"Unsupported database type: {connection.database_type}",
            }
        except Exception as e:
            logger.error("Query execution failed (conn=%d): %s",
                         connection.id, e, exc_info=True)
            return {"status": "error", "error": f"Query execution failed: {str(e)}"}

    async def _format_answer(
        self, user_prompt: str, sql: str, rows: List[Dict],
        columns: List[str], row_count: int,
    ) -> str:
        try:
            if row_count == 0:
                return "No results found matching your query."

            try:
                col_names = (
                    columns if isinstance(columns, list)
                    else [c["name"] if isinstance(c, dict) else c for c in columns]
                )
                summary = await self.ollama.summarize_data(
                    user_prompt=user_prompt,
                    columns=col_names,
                    rows=rows[:50],
                    row_count=row_count,
                )
                if summary and len(summary) > 10:
                    return summary
            except Exception as e:
                logger.debug("AI summarization fell back to template: %s", e)

            if row_count == 1:
                values = ", ".join(f"{k}: {v}" for k, v in rows[0].items())
                return f"Found 1 result: {values}"
            if row_count <= 10:
                lines = [f"Found {row_count} results:"]
                for i, row in enumerate(rows, 1):
                    values = ", ".join(f"{k}: {v}" for k, v in row.items())
                    lines.append(f"{i}. {values}")
                return "\n".join(lines)

            first_col = columns[0] if isinstance(columns[0], str) else columns[0].get("name", "?")
            vals = [str(row.get(first_col, "?")) for row in rows[:5]]
            return f"Found {row_count} results. First 5 {first_col}s: {', '.join(vals)}..."

        except Exception as e:
            logger.error("Error formatting answer: %s", e, exc_info=True)
            return f"Query returned {row_count} rows."

    # ── Direct execute (workbench / API) ──────────────────

    async def execute_query(
        self, connection_id: int, sql: str, timeout: int = 30,
    ) -> Dict[str, Any]:
        """Execute a SQL query directly (used by workbench and API endpoints)."""
        start_time = time.time()

        try:
            sql_upper = sql.strip().upper()
            if not sql_upper.startswith("SELECT"):
                return {
                    "success": False,
                    "error": "Only SELECT queries are allowed",
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                }

            connection = self.db.query(Connection).filter(
                Connection.id == connection_id,
                Connection.is_active.is_(True),
            ).first()
            if not connection:
                return {
                    "success": False,
                    "error": f"Connection {connection_id} not found or inactive",
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                }

            try:
                engine = _get_engine(connection, timeout)
            except ValueError:
                return {
                    "success": False,
                    "error": f"Unsupported database type: {connection.database_type}",
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                }

            exec_start = time.time()
            with engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = result.fetchmany(MAX_RESULT_ROWS + 1)
                columns = list(result.keys())
                truncated = len(rows) > MAX_RESULT_ROWS
                if truncated:
                    rows = rows[:MAX_RESULT_ROWS]
                rows_as_dicts = [dict(zip(columns, list(row))) for row in rows]

            exec_ms = int((time.time() - exec_start) * 1000)
            columns_with_type = [{"name": col, "type": "string"} for col in columns]

            logger.debug("Direct query: %d rows in %dms", len(rows_as_dicts), exec_ms)

            return {
                "success": True,
                "columns": columns_with_type,
                "rows": rows_as_dicts,
                "row_count": len(rows_as_dicts),
                "execution_time_ms": exec_ms,
                "truncated": truncated,
            }

        except Exception as e:
            logger.error("Direct query failed: %s", e, exc_info=True)
            return {
                "success": False,
                "error": f"Query execution failed: {str(e)}",
                "execution_time_ms": int((time.time() - start_time) * 1000),
            }

    # ── NoSQL handler ─────────────────────────────────────

    async def _handle_nosql_query(
        self, connection: Connection, user_prompt: str,
    ) -> Dict[str, Any]:
        """Route natural-language queries to NoSQL backends."""
        start_time = time.time()
        dt = connection.database_type.lower()
        try:
            from app.services.nosql_service import get_nosql_handler
            import json

            nosql_map = {
                "mongodb": "mongodb", "mongo": "mongodb", "redis": "redis",
                "elasticsearch": "elasticsearch", "elastic": "elasticsearch",
                "es": "elasticsearch", "neo4j": "neo4j",
            }
            ntype = nosql_map.get(dt, dt)

            uri_templates = {
                "mongodb": (
                    f"mongodb://{connection.username}:{connection.password}"
                    f"@{connection.host}:{connection.port}/{connection.database}"
                ),
                "redis": (
                    f"redis://:{connection.password}@{connection.host}:{connection.port}/0"
                    if connection.password
                    else f"redis://{connection.host}:{connection.port}/0"
                ),
                "elasticsearch": f"http://{connection.host}:{connection.port}",
                "neo4j": f"bolt://{connection.host}:{connection.port}",
            }
            uri = uri_templates.get(ntype, "")
            handler = get_nosql_handler(
                ntype, uri=uri, database=connection.database,
                url=uri, username=connection.username, password=connection.password,
            )

            schema = handler.extract_schema()
            schema_ctx = json.dumps(schema, indent=2, default=str)[:4000]
            query_spec = await self.ollama.generate_nosql_query(user_prompt, ntype, schema_ctx)

            if ntype in ("mongodb", "mongo"):
                coll = query_spec.get("collection", "")
                pipeline = query_spec.get("pipeline")
                exec_result = (
                    handler.execute_pipeline(coll, pipeline) if pipeline
                    else handler.execute_find(
                        coll, query_spec.get("filter", {}),
                        query_spec.get("projection"),
                        query_spec.get("limit", 100),
                    )
                )
                query_str = json.dumps(query_spec, default=str)
            elif ntype == "redis":
                cmd = query_spec.get("command", "")
                exec_result = handler.execute_command(cmd)
                query_str = cmd
            elif ntype in ("elasticsearch", "elastic", "es"):
                idx = query_spec.get("index", "_all")
                body = query_spec.get("body", query_spec)
                exec_result = handler.execute_query(idx, body)
                query_str = json.dumps(query_spec, default=str)
            elif ntype == "neo4j":
                cypher = query_spec.get("cypher", "")
                exec_result = handler.execute_cypher(cypher)
                query_str = cypher
            else:
                return {
                    "status": "error",
                    "error": f"Unsupported NoSQL type: {dt}",
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                }

            if not exec_result.get("success", False):
                return {
                    "status": "error",
                    "error": exec_result.get("error", "Query failed"),
                    "sql": query_str,
                    "execution_time_ms": int((time.time() - start_time) * 1000),
                }

            rows = exec_result.get("rows", [])
            columns = exec_result.get("columns", [])
            row_count = exec_result.get("row_count", len(rows))

            answer = await self._format_answer(user_prompt, query_str, rows, columns, row_count)
            return {
                "status": "success", "answer": answer, "sql": query_str,
                "rows": rows, "columns": columns, "row_count": row_count,
                "execution_time_ms": int((time.time() - start_time) * 1000),
            }
        except Exception as e:
            logger.error("NoSQL query failed: %s", e, exc_info=True)
            return {
                "status": "error",
                "error": f"NoSQL query failed: {str(e)}",
                "execution_time_ms": int((time.time() - start_time) * 1000),
            }

    # ── Utilities ─────────────────────────────────────────

    def _extract_tables_from_sql(self, sql: str) -> list:
        """Extract table names from a SQL query (best effort)."""
        tables = set()
        for match in re.finditer(r'(?:FROM|JOIN)\s+"?(\w+)"?', sql, re.IGNORECASE):
            tables.add(match.group(1))
        return list(tables)

    # ── Lifecycle ─────────────────────────────────────────

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.db:
                self.db.close()
        except Exception:
            pass
        try:
            if self.metadata:
                self.metadata.close()
        except Exception:
            pass

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
