# DbChat — End-to-End Flows

Step-by-step walkthroughs of the critical user journeys showing exactly which
files and functions are involved at each stage.

---

## Flow 1: User Login

```
Browser                          Frontend Proxy               Backend
───────                          ──────────────               ───────
doLogin()
  POST /api/auth/login ────────▶ proxy to :8000 ────────────▶ auth.py → login()
  {username, password}                                          │
                                                                ▼
                                                        authenticate_user()
                                                        (auth_service.py)
                                                          verify_password()
                                                          get_user_perms_dict()
                                                          create_access_token()
                                                                │
  ◀──────────── {access_token, username, perms} ◀───────────────┘
  │
  Store token in localStorage
  currentUser = {username, perms}
  showApp()
    loadDatabases()
      GET /api/admin/databases → admin.py → list_databases()
      Populate #dbSelector
    loadWelcome()
      GET /api/chat/welcome → chat.py → welcome()
      OllamaService.generate_welcome()
    loadThreads()
      GET /api/chat/threads → chat.py → list_threads()
```

---

## Flow 2: Register a New Database

```
Admin fills form → submitRegisterDb()
  POST /api/admin/register-db ──────────────────▶ admin.py → register_database()
  {name, host, port, username, password,              │
   database, database_type}                           ▼
                                                1. Insert Connection row
                                                2. grant_all_on_connection(admin)
                                                3. BackgroundTasks.add_task(_extract_and_index_database)
                                                4. Return {id, name, ...}
  ◀──────── Success response
  │
  loadDatabases() (refresh selector)

                         BACKGROUND TASK
                         ───────────────
                    _extract_and_index_database()
                           │
                           ▼
                    SchemaExtractor.extract_schema()
                      → Connect to user's DB
                      → Inspector: tables, columns, PKs, row counts
                      → SchemaExtractor.get_foreign_keys()
                           │
                           ▼
                    IndexingService.index_schema()
                      → For each table:
                        1. Upsert Table + Column rows (metadata DB)
                        2. Sample categorical values
                        3. OllamaService.embed_text() for:
                           - Table vector
                           - Column vectors
                           - Value vectors
                        4. VectorService.upsert_vector() → Qdrant
                      → Store ForeignKey rows
```

---

## Flow 3: Ask a Question (NL → SQL)

```
User types "What are the top 10 customers by revenue?"
  │
  sendMessage()
    │
    _sendViaSSE()
      POST /api/chat/stream ─────────────────▶ chat.py → chat_stream()
      {prompt, connection_id, thread_id}            │
                                                    ▼
                                              ChatService.process_query()
                                                    │
      ┌─────────────────────────────────────────────┘
      │
      ▼  STEP 1: Validate
      Check prompt length ≤ 10,000
      Load Connection from DB
      Check has_db_permission(prompt_query)
      │
      ▼  STEP 2: Route
      If NoSQL type → _handle_nosql_query() (separate flow)
      │
      ▼  STEP 3: Embed + Classify
      OllamaService.embed_text(prompt)          → 768-dim vector
      OllamaService.classify_intent(prompt)     → "catalog" or "data"
      If "catalog" → _handle_catalog_query()    → return schema info
      │
      ▼  STEP 4: Cache Check
      CacheService.get("sql:{conn_id}:{hash}")
      If hit → skip to STEP 8
      │
      ▼  STEP 5: Table Selection
      _vector_candidate_retrieval()
        VectorService.search(embedding, top_k=50)  → Qdrant
        Score and deduplicate table candidates
      OllamaService.rerank_tables(prompt, candidates, top_k=5)
        LLM picks most relevant tables
      MetadataService.get_fk_bridge_tables()
        BFS on FK graph to find intermediate join tables
      _filter_tables_by_access(user_id)
        Intersect with TableAccess allowlist
      │
      ▼  STEP 6: Schema Context
      MetadataService.get_column_schema(conn_id, tables)
        → "Table: orders\n  Columns: id (INTEGER, PK), ...\n  Foreign Keys: ..."
      SemanticGraphService.build_entity_context()
      SemanticGraphService.build_glossary_context()
      SemanticGraphService.build_corrections_context(prompt)
      _get_training_context(conn_id, prompt)
        → few-shot examples from TrainingPair rows
      │
      ▼  STEP 7: SQL Generation
      If reasoning mode:
        OllamaService.generate_sql_with_reasoning(prompt, schema, samples)
        → (reasoning_text, sql)
      Else:
        OllamaService.generate_sql(prompt, schema, samples, thread_history)
        → sql
      │
      ▼  STEP 8: Validation
      _validate_sql(sql)                    → SELECT/WITH only, no forbidden commands
      _verify_sql_identifiers(sql, schema)  → check table.column refs exist
      _pre_validate(sql, schema, prompt)    → LLM safety check + one repair pass
      │
      ▼  STEP 9: Execute
      _execute_query(connection, sql, timeout=30)
        _get_engine(connection)             → cached SQLAlchemy engine
        engine.connect().execute(text(sql))
        Fetch up to 5,000 rows
      If error → _repair_loop() (up to 2 regenerate+execute cycles)
      │
      ▼  STEP 10: Format Answer
      OllamaService.summarize_data(prompt, columns, rows, row_count)
        → "Found 10 results. The top customer is..."
      │
      ▼  STEP 11: Cache + Return
      CacheService.set("sql:{conn_id}:{hash}", sql)
      Return {status, answer, sql, rows, columns, row_count, tables_used, ...}
      │
      └─────────────────────────────────────────────────┐
                                                        │
      ◀──────── SSE events: ──────────────────────────  ┘
        event: status   → "Selecting tables..."
        event: sql      → "SELECT c.name, SUM(o.total)..."
        event: data     → {columns: [...], rows: [...], row_count: 10}
        event: answer   → "The top 10 customers by revenue are..."
        event: summary  → "Revenue is concentrated among..."
        event: done     → {thread_id: "uuid"}

  _handleSSEEvent()
    Accumulates collected = {sql, answer, rows, columns, ...}

  addBotReply(query, collected)
    buildTable(columns, rows)        → paginated HTML table
    fetchChartChips(columns, rows)   → viz-service recommendations → chip buttons
    "View SQL" toggle
    "Explore" button → openDetailModal()
    "Export CSV/JSON" buttons
    "Save" button → openSaveQueryModal()
    "Explain" button → POST /api/chat/explain

  _save_chat_history()               → ChatHistory row in metadata DB
```

---

## Flow 4: Dashboard Pin & Refresh

```
User sees chart recommendation chip → clicks it
  openChartModal(chartType, config, columns, rows)
    Chart.js render on canvas
    │
    clicks "📌 Pin" → openPinModal(query, sql, pinType, chartConfig, name)
      Select existing dashboard or create new
      submitPin()
        POST /api/dashboards/{id}/pins
        {name, pin_type, chart_type, sql, connection_id, chart_config}
        │
        ▼
        dashboard.py → add_pin()
          Insert DashboardPin row
          │
        ◀──── Success

LATER: User opens dashboard
  openDashboard(id)
    GET /api/dashboards/{id} → dashboard.py → get_dashboard()
    Returns pins with metadata (no live data yet)
    │
    refreshCurrentDashboard()
      POST /api/dashboards/{id}/refresh → dashboard.py → refresh_dashboard()
        For each pin:
          _run_pin(pin)
            ChatService.execute_query(pin.connection_id, pin.sql)
            Return {columns, rows, ...}
        │
      ◀──── [{pin_id, columns, rows, ...}, ...]
      │
      For each pin:
        If chart → Chart.js render
        If table → buildTable()
```

---

## Flow 5: Write-Back Approval Workflow

```
User composes DML → openWritebackModal()
  submitWriteback()
    POST /api/writeback
    {connection_id, sql, description}
      │
      writeback.py → create_writeback()
        Insert WriteBackRequest (status="pending")
      │
    ◀──── Created

Admin reviews pending list
  loadWritebacks()
    GET /api/writeback?status=pending

  approveWriteback(id)
    POST /api/writeback/{id}/approve
      writeback.py → approve_writeback()
        Check is_db_admin or db_reindex permission
        Set status="approved", approved_by=user

  executeWriteback(id)
    POST /api/writeback/{id}/execute
      writeback.py → execute_writeback()
        ChatService.execute_query(sql, allow_dml=True)
          engine.connect().execute(text(sql))
          conn.commit()
        Set status="executed"
```

---

## Flow 6: Schema Indexing & Vector Embeddings

```
register-db or reindex trigger
  │
  IndexingService.index_schema(connection_id, database_name, schema_data)
    │
    For each table in schema_data:
      │
      ├── Upsert Database row (metadata DB)
      ├── Upsert Table row (name, row_count)
      ├── Upsert Column rows (name, type, is_pk, is_nullable)
      │
      ├── Sample categorical values:
      │     SELECT DISTINCT col FROM table LIMIT 50
      │     Store in Column.sample_values + Table.sample_values
      │
      ├── Generate embeddings:
      │     OllamaService.embed_text("Table: orders. Columns: id, customer_id, total")
      │       → [0.12, -0.45, ...] (768 dims)
      │     VectorService.upsert_vector(id="table:orders", embedding, metadata)
      │       → Qdrant point (MD5→UUID)
      │
      │     For each column:
      │       OllamaService.embed_text("Column: orders.customer_id (integer)")
      │       VectorService.upsert_vector(id="column:orders.customer_id", ...)
      │
      │     For categorical columns with samples:
      │       OllamaService.embed_text("Table orders, column status: active, pending, cancelled")
      │       VectorService.upsert_vector(id="value:orders.status", ...)
      │
      └── Extract and store ForeignKey rows:
            SchemaExtractor.get_foreign_keys(engine)
            Insert ForeignKeyModel rows
```

---

## Flow 7: Semantic Intelligence (Knowledge Graph)

```
Admin fingerprints a database:
  fingerprintConnection(conn_id)
    POST /api/knowledge/fingerprint/{conn_id}
      SemanticGraphService.fingerprint_connection(connection)
        Connect to user's DB
        For each table.column:
          Sample values → classify pattern (email, phone, uuid, etc.)
          Compute stats: distinct_count, null_ratio, avg_length
          Hash: SHA256(data_type + cardinality + null_ratio + pattern + avg_length)
          Upsert ColumnFingerprint row

Admin discovers matches:
  discoverMatches()
    GET /api/knowledge/discover?min_confidence=70
      SemanticGraphService.discover_entity_matches()
        Group ColumnFingerprints by fingerprint_hash
        Score by name similarity + pattern match
        Return cross-connection column matches

Admin creates concept:
  createConcept("Customer ID", "Unique customer identifier")
    POST /api/knowledge/concepts

Admin maps columns to concept:
  createMapping(concept_id, conn_id, table, column)
    POST /api/knowledge/mappings

DURING QUERY:
  ChatService.process_query() calls:
    SemanticGraphService.build_entity_context(connection_id)
      → "Entity: Customer ID\n  Mapped to: db1.customers.id, db2.orders.customer_id"
    This text is injected into the LLM system prompt alongside schema context.
```

---

## Flow 8: LLM Provider Routing

```
Default: all tasks use one provider (e.g., Ollama with Mistral)

Admin sets per-role overrides:
  POST /api/llm/model-routing
  {role: "sql_generate", provider_type: "openai", model: "gpt-4", api_key: "..."}
    │
    llm_settings.py → set_model_routing()
      set_role_provider("sql_generate", "openai", model="gpt-4", ...)
        _build_provider("openai", ...) → OpenAICompatProvider instance
        Store in _role_configs["sql_generate"]

DURING QUERY:
  OllamaService._call_chat_completions(system, user, role="sql_generate")
    get_provider_for_role("sql_generate")
      → returns OpenAICompatProvider (overridden)
    provider.chat(messages) → GPT-4 generates SQL

  OllamaService.summarize_data(...) uses role="summarize"
    get_provider_for_role("summarize")
      → no override → falls back to default (Ollama)
```

---

## Flow 9: Embed Widget

```
Admin creates embed token:
  POST /api/embed/create {connection_id, allowed_tables}
    embed.py → create_embed()
      Generate random token
      Store in _embed_tokens dict
      Return {token, html_snippet}

External website includes snippet:
  <script src="https://app.example.com/api/embed/widget.js"
          data-token="abc123"></script>
    │
    widget.js creates iframe: /api/embed/frame?token=abc123
      embed.py → widget_frame()
        Returns self-contained HTML with chat UI
        │
        User types question in iframe
          fetch('/api/embed/query?token=abc123&prompt=...')
            embed.py → embed_query()
              Validate token from _embed_tokens
              ChatService.process_query(connection_id, prompt, user_id)
              Return {answer, sql, rows, ...}
```

---

## Flow 10: File Upload & Query

```
User uploads CSV:
  POST /api/files/upload (multipart)
    file_upload.py → upload_file()
      Per-user DuckDB file: /tmp/dbchat_files_{user_id}.duckdb
      Read file:
        .csv → pandas.read_csv()
        .xlsx → pandas.read_excel()
        .parquet → pandas.read_parquet()
        .json → pandas.read_json()
      df.to_sql(table_name, duckdb_engine)

User queries uploaded data:
  POST /api/files/query?sql=SELECT * FROM sales
    file_upload.py → query_uploaded()
      DuckDB engine.execute(sql)
      Return {columns, rows}
```
