# DbChat — Service Layer

All services live in `app/services/`. They encapsulate business logic and are
called by the API route handlers.

---

## Service Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Route Handlers                             │
│    chat.py · admin.py · auth.py · training.py · (30 more...)       │
└────┬────────┬──────────┬──────────┬──────────┬──────────┬──────────┘
     │        │          │          │          │          │
     ▼        ▼          ▼          ▼          ▼          ▼
 ChatService  AuthService  IndexingService  MetadataService  ActivityService
     │            │             │                │
     ├── OllamaService ────────┤                │
     ├── VectorService ────────┤                │
     ├── CacheService          │                │
     ├── MetadataService ──────┘                │
     └── SemanticGraphService                   │
                                                │
 SchemaService (SchemaExtractor) ──── used by IndexingService + ChatService
 NoSQLService ──── used by chat.py, nosql.py, connection_test.py
 LLM Provider layer ──── used by OllamaService
 Metrics ──── used by ChatService
```

---

## 1. AuthService (`auth_service.py` — 149 lines)

Handles user management, password hashing, JWT tokens, and permission CRUD.

### Constants
- `SECRET_KEY` — loaded from `Settings.JWT_SECRET`
- `ALGORITHM` — `HS256`
- `ACCESS_TOKEN_EXPIRE_HOURS` — `5`
- `VALID_PERMISSIONS` — `{db_onboard, db_reindex, prompt_query}`

### Functions

| Function | What It Does |
|----------|-------------|
| `hash_password(plain)` | Bcrypt hash |
| `verify_password(plain, hashed)` | Bcrypt verify |
| `get_user_perms_dict(db, user_id)` | Loads `UserPermission` rows → `{"*": [...], "42": [...]}` map |
| `create_access_token(user_id, username, perms)` | JWT with `sub`, `username`, `perms`, 5-hour expiry |
| `decode_access_token(token)` | Decodes JWT → dict or `None` on error |
| `get_user_by_username(db, username)` | ORM lookup |
| `create_user(db, username, password)` | Creates user with hashed password |
| `set_db_permissions(db, user_id, connection_id, permissions)` | Replace perms for user+scope |
| `grant_all_on_connection(db, user_id, connection_id)` | Grant all 3 permissions |
| `authenticate_user(db, username, password)` | Returns user if active + password matches |

### Flow
```
Login → authenticate_user() → get_user_perms_dict() → create_access_token() → JWT
```

---

## 2. ChatService (`chat_service.py` — 1,431 lines)

The **core engine** — takes a natural language prompt and returns SQL + results.

### Key Constants
- `MAX_RESULT_ROWS = 5000` — fetch limit
- `MAX_REPAIR_ATTEMPTS = 2` — SQL fix retries
- `ENGINE_CACHE_TTL = 3600` — connection engine cache lifetime
- `MAX_PROMPT_LENGTH = 10_000`

### Module Functions

| Function | Purpose |
|----------|---------|
| `_get_engine(connection, timeout)` | Thread-safe cached SQLAlchemy engine creation |
| `evict_engine(connection_id)` | Dispose + remove cached engine |
| `_sanitize_backticks(raw_sql, dialect)` | Backtick → double-quote (except MySQL) |

### ChatService Methods

| Method | Purpose |
|--------|---------|
| `process_query(connection_id, user_prompt, top_k_tables, timeout, thread_history, user_id)` | **Main entry point.** Orchestrates the full NL→SQL pipeline |
| `execute_query(connection_id, sql, timeout, allow_dml)` | Direct SQL execution (workbench, write-back) |
| `_filter_tables_by_access(user_id, connection_id, tables)` | Enforces `TableAccess` allowlist |
| `_select_tables(qid, prompt, embedding, connection_id, top_k)` | Vector retrieval → LLM rerank → FK bridge expansion |
| `_vector_candidate_retrieval(qid, embedding, connection_id, pool_size)` | Qdrant similarity search |
| `_generate_sql(qid, prompt, schema, dialect, thread_history)` | Calls OllamaService for SQL generation |
| `_pre_validate(qid, sql, schema, prompt, samples, dialect)` | Identifier check + safety validation |
| `_repair_loop(qid, sql, error, ...)` | Execute → fail → regenerate loop (up to 2 attempts) |
| `_handle_catalog_query(connection, prompt)` | Inspector-based schema introspection |
| `_handle_nosql_query(connection, prompt)` | NoSQL query generation + execution |
| `_validate_sql(sql)` | SELECT/WITH only; block forbidden commands |
| `_verify_sql_identifiers(sql, schema)` | Cross-check table.column refs against schema |
| `_format_answer(prompt, sql, rows, columns, row_count)` | LLM-generated natural language summary |

### The Full Pipeline (process_query)

```
1.  Validate prompt length
2.  Load Connection from DB
3.  Check permission (prompt_query)
4.  Route NoSQL types to _handle_nosql_query()
5.  Embed prompt via OllamaService.embed_text()
6.  Classify intent: "catalog" → _handle_catalog_query()
7.  Check SQL cache (Redis)
8.  Select tables:
    a. Vector candidate retrieval (Qdrant)
    b. LLM reranking
    c. FK bridge expansion
    d. Table access filtering
9.  Build schema context (MetadataService)
10. Enrich with semantic context:
    - Entity concepts, glossary, column annotations
    - Query corrections (learning from past fixes)
    - Training pairs (few-shot examples)
11. Generate SQL (OllamaService, with optional reasoning mode)
12. Pre-validate SQL (identifier check, forbidden commands)
13. Execute SQL on user's database
14. If error → repair loop (regenerate + re-execute, up to 2x)
15. Format answer (LLM summary)
16. Cache SQL result
17. Return {status, answer, sql, rows, columns, row_count, ...}
```

---

## 3. OllamaService (`ollama_service.py` — 719 lines)

Interface to the LLM for all AI tasks. Uses the LLM Provider abstraction layer.

### Methods

| Method | Role Used | Purpose |
|--------|-----------|---------|
| `generate_sql(prompt, schema, samples, history, dialect)` | `sql_generate` | Prompt engineering → raw SQL |
| `generate_sql_with_reasoning(prompt, schema, samples)` | `reasoning` + `sql_generate` | Two-step: reason first, then generate |
| `explain_sql(sql, prompt, schema, columns, row_count)` | `explain` | Plain-English SQL explanation |
| `summarize_data(prompt, columns, rows, row_count)` | `summarize` | Insight bullets on result data |
| `rerank_tables(prompt, candidates, top_k)` | `classify` | JSON rerank of table candidates |
| `identify_tables(prompt, summaries)` | `classify` | Simple table name list |
| `classify_intent(text)` | `classify` | `"catalog"` or `"data"` |
| `generate_nosql_query(prompt, db_type, schema)` | `nosql` | MongoDB/Redis/ES/Neo4j query spec |
| `embed_text(text)` | — | Ollama `/api/embed` for vector embeddings |
| `generate_welcome(table_summaries)` | `general` | Welcome page summary + suggestions |
| `health_check()` | — | LLM + Ollama endpoint health |

---

## 4. LLM Provider Layer (`llm_provider.py` — 463 lines)

Abstraction over multiple LLM backends with per-task role routing.

### Providers

| Class | Backend | Auth |
|-------|---------|------|
| `OllamaLocalProvider` | Ollama `/api/chat` | None |
| `OpenAICompatProvider` | Any OpenAI-compatible API | Bearer token |
| `AnthropicProvider` | Anthropic Messages API | `x-api-key` |

### Role Routing

The system supports assigning different providers to different tasks:

```python
VALID_ROLES = ("general", "sql_generate", "reasoning", "explain",
               "summarize", "classify", "nosql", "suggest")
```

Configure via environment variables: `LLM_ROLE_sql_generate=openai:gpt-4`
or at runtime via `POST /api/llm/model-routing`.

### Key Functions

| Function | Purpose |
|----------|---------|
| `get_provider()` | Returns the default global LLM provider |
| `get_provider_for_role(role)` | Returns role-specific provider, falling back to default |
| `set_provider(type, **kwargs)` | Change global default at runtime |
| `set_role_provider(role, type, **kwargs)` | Override a specific role |

---

## 5. IndexingService (`indexing_service.py` — 346 lines)

Extracts schema from a user's database and stores it as metadata + embeddings.

### Main Method: `index_schema()`

```
1. Connect to user's DB via SchemaExtractor
2. For each table:
   a. Upsert Table + Column rows in metadata DB
   b. Sample categorical column values
   c. Generate embeddings for:
      - Table name + column list (→ "table" vector)
      - Each column name + type (→ "column" vector)
      - Sample values (→ "value" vector)
   d. Upsert all vectors into Qdrant
3. Extract and store ForeignKey relationships
4. Return {tables_indexed, columns_indexed, duration_ms}
```

### What Gets Embedded

| Vector Type | Content | Used For |
|-------------|---------|----------|
| `table` | `"Table: orders. Columns: id, customer_id, total, created_at"` | Table selection during query |
| `column` | `"Column: orders.customer_id (integer)"` | Fine-grained column matching |
| `value` | `"Table orders, column status: active, pending, cancelled"` | Value-aware schema matching |

---

## 6. SchemaService (`schema_service.py` — 252 lines)

Low-level database introspection via SQLAlchemy Inspector.

### SchemaExtractor (static methods)

| Method | Purpose |
|--------|---------|
| `build_connection_string(type, host, port, user, pass, db)` | URL for postgres/mysql/sqlserver/sqlite/duckdb/snowflake/bigquery/redshift |
| `extract_schema(type, host, port, user, pass, db)` | Full schema: tables, columns, types, PKs, row counts |
| `get_foreign_keys(engine)` | Per-table FK map: column → (ref_table, ref_column, constraint) |

---

## 7. MetadataService (`metadata_service.py` — 381 lines)

Reads indexed metadata from PostgreSQL and builds rich schema context strings
for the LLM.

### Key Methods

| Method | Purpose |
|--------|---------|
| `get_column_schema(connection_id, table_names)` | Builds per-table text: columns, types, PKs, FKs, join paths, ambiguous column notes |
| `get_fk_bridge_tables(connection_id, selected_tables)` | Finds intermediate FK-linked tables between selected tables |
| `_find_join_path(db_id, fk_graph, from, to, max_hops=4)` | BFS shortest path on FK graph |
| `_path_to_join_conditions(fk_graph, path)` | Generates `ON` clause text for each edge |

### Schema Context Example (what the LLM sees)
```
Table: orders
  Columns: id (INTEGER, PK), customer_id (INTEGER), total (NUMERIC), ...
  Foreign Keys:
    customer_id → customers.id
  Join Path to customers:
    orders.customer_id = customers.id
  Ambiguous columns:
    "id" also appears in: customers, products
```

---

## 8. VectorService (`vector_service.py` — 133 lines)

Thin wrapper around Qdrant vector database.

| Method | Purpose |
|--------|---------|
| `upsert_vector(id, embedding, metadata, table, db)` | MD5→UUID point ID; upsert to Qdrant |
| `search(embedding, top_k, filters)` | Similarity search with optional payload filters |
| `health_check()` | Verifies Qdrant connectivity |

Collection: `dbchat_schema`, 768 dimensions, cosine distance.

---

## 9. CacheService (`cache_service.py` — 81 lines)

Redis-backed JSON cache.

| Method | Purpose |
|--------|---------|
| `get(key)` | JSON-decoded value or `None` |
| `set(key, value, ttl=3600)` | `SETEX` with JSON encoding |
| `delete(key)` | Remove key |
| `clear_pattern(pattern)` | `SCAN` + batch delete by glob |

Used primarily for SQL cache (`sql:{connection_id}:{prompt_hash}`).

---

## 10. NoSQLService (`nosql_service.py` — 407 lines)

Handlers for non-relational databases.

| Handler | DB Type | Operations |
|---------|---------|------------|
| `MongoHandler` | MongoDB | `extract_schema`, `execute_pipeline`, `execute_find` |
| `RedisHandler` | Redis | `extract_schema`, `execute_command` (blocks destructive ops) |
| `ElasticsearchHandler` | Elasticsearch | `extract_schema`, `execute_query` (search + aggregation) |
| `Neo4jHandler` | Neo4j | `extract_schema`, `execute_cypher` (blocks writes) |

Factory: `get_nosql_handler(db_type, **kwargs)` returns the appropriate handler.

---

## 11. SemanticGraphService (`semantic_graph_service.py` — 444 lines)

Semantic intelligence layer that enriches LLM context.

| Method | Purpose |
|--------|---------|
| `fingerprint_connection(connection, sample_limit)` | Compute column statistics + pattern classification |
| `discover_entity_matches(min_confidence)` | Find matching columns across databases by hash/name overlap |
| `build_entity_context(connection_id)` | Text block of entity concept mappings for LLM |
| `build_glossary_context(connection_id)` | Business glossary text for LLM |
| `build_corrections_context(connection_id, prompt)` | Past query corrections relevant to current prompt |

### Pattern Classification
Columns are classified by their values into patterns like: `email`, `phone`,
`uuid`, `url`, `date`, `currency`, `percentage`, `ip_address`, `boolean`, etc.

---

## 12. ActivityService (`activity_service.py` — 158 lines)

Audit logging for all significant user actions.

| Component | Purpose |
|-----------|---------|
| `Actions` class | String constants for action types (LOGIN, CHAT_QUERY, REGISTER_DB, etc.) |
| `log_activity(...)` | Inserts `ActivityLog` row with IP, user agent, duration, detail JSON |

---

## 13. Metrics (`metrics.py` — 93 lines)

Prometheus metrics (gracefully degrades if `prometheus_client` not installed).

| Metric | Type | Labels |
|--------|------|--------|
| `CHAT_QUERIES` | Counter | status, intent |
| `CHAT_LLM_DURATION` | Histogram | role |
| `CHAT_TABLE_SELECTION` | Counter | method |
| `CHAT_REPAIR_ATTEMPTS` | Histogram | — |
| `CHAT_REPAIR_SUCCESS` | Counter | — |
| `CHAT_CACHE_OPS` | Counter | op |
| `CHAT_QUERY_EXEC_DURATION` | Histogram | — |

Exposed at `GET /metrics` in `serve.py`.
