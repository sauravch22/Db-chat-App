# DbChat — Natural Language Database Query Engine

**Executive Summary, Component Architecture, Use Cases & Sample Requests**

---

## Page 1: Executive Summary & Use Cases

### What is DbChat?

DbChat is a natural language to SQL query engine that translates plain English questions into database queries. Users ask questions like *"How many artists are in the database?"* or *"Show me total revenue per genre,"* and DbChat returns structured results with both the executed SQL and formatted answer text.

**Key Differentiators:**
- **Intent-aware routing**: Distinguishes between structural questions (schema/metadata) and data questions
- **Schema-aware LLM generation**: Injects exact table and column names into prompts to prevent hallucination
- **Connection multiplexing**: Supports multiple databases via a single API endpoint
- **Catalog introspection**: Answers schema, index, constraint, and connection pool questions without executing on the target DB
- **Vector-based table discovery**: Finds relevant tables via semantic embedding, not keyword matching

---

### Use Cases

#### 1. **BI/Analytics Self-Service**
**Scenario:** Business analysts need ad-hoc queries without contacting the data team.
- *Question:* "What's the top 10 genres by revenue?"
- *Result:* Instant SQL execution, no manual query writing
- **Component:** ChatService + OllamaService (data path)

#### 2. **Database Exploration & Onboarding**
**Scenario:** New team member needs to understand a 500-table enterprise database.
- *Question:* "List all tables in the database"
- *Result:* Catalog handler returns schema names instantly
- *Question:* "What's the schema of the invoice_line table?"
- *Result:* Column names, types, constraints, indexes listed
- **Component:** ChatService + CatalogHandler

#### 3. **Data Governance & Compliance Checks**
**Scenario:** DBA or security team needs to audit database structure.
- *Question:* "What foreign keys reference the customer table?"
- *Result:* All inbound FK relationships listed
- *Question:* "How many active connections are there?"
- *Result:* Connection count + active query list from `pg_stat_activity`
- **Component:** ChatService + CatalogHandler + system views

#### 4. **Development & Testing**
**Scenario:** Developer validating row counts and structure after migrations.
- *Question:* "How many rows are in the track table?"
- *Result:* Exact count (e.g., "3,503") via catalog query
- *Question:* "Describe the track table"
- *Result:* Full schema with nullable flags and defaults
- **Component:** ChatService + CatalogHandler + information_schema

#### 5. **Multi-Database Environment**
**Scenario:** Organization with Neon, MySQL, and PostgreSQL databases.
- Single API endpoint handles all databases via `connection_id` parameter
- Each request specifies which database to query
- Metadata stored in central PostgreSQL, embeddings in shared Qdrant
- **Component:** Connection manager + dynamic engine creation

---

## Page 2: Component Architecture & Design

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                               CLIENT APPLICATION                             │
│                         (Web UI / API Client)                                │
└────────────────────────────────────────┬────────────────────────────────────┘
                                         │
                              POST /api/chat
                                         │
                                         ▼
        ┌────────────────────────────────────────────────────────────┐
        │                  FastAPI Server (serve.py)                 │
        │              (Routes: /api/chat, /api/admin, /health)      │
        └────────────────────────────┬───────────────────────────────┘
                                     │
                                     ▼
        ┌────────────────────────────────────────────────────────────┐
        │                  CHAT SERVICE (Orchestrator)               │
        │  ┌──────────────────────────────────────────────────────┐  │
        │  │ 1. INTENT CLASSIFICATION                             │  │
        │  │    - Pre-check: Structural keywords → catalog path   │  │
        │  │    - LLM classify: data vs catalog                   │  │
        │  └──────────────────────────────────────────────────────┘  │
        │                           │                                 │
        │       ┌───────────────────┼───────────────────┐             │
        │       ▼                   ▼                   ▼             │
        │   [CATALOG]           [DATA PATH]         [FALLBACK]       │
        │   ┌────────────┐   ┌──────────────┐                       │
        │   │ Catalog    │   │ Embedding +  │                       │
        │   │ Handler    │   │ Vector Search                        │
        │   │            │   │              │                       │
        │   │ - schema   │   │ Find tables  │                       │
        │   │ - indexes  │   │ from Qdrant  │                       │
        │   │ - FK/PK    │   │              │                       │
        │   │ - row_cnt  │   │ Build schema │                       │
        │   │ - conns    │   │ context      │                       │
        │   └────────────┘   │              │                       │
        │                    │ LLM SQL gen  │                       │
        │                    └──────────────┘                        │
        └────────────────────────────────────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
        ┌─────────────────┐  ┌──────────────────┐  ┌──────────────┐
        │ OLLAMA SERVICE  │  │ VECTOR SERVICE   │  │ METADATA DB  │
        │                 │  │   (Qdrant)       │  │ (PostgreSQL) │
        │ ┌─────────────┐ │  │                  │  │              │
        │ │ LLM: llama  │ │  │ Collection:      │  │ Stores:      │
        │ │  (0.0 temp) │ │  │ dbchat_         │  │ - connections│
        │ └─────────────┘ │  │ embeddings       │  │ - databases  │
        │                 │  │ (768-dim)        │  │ - tables     │
        │ ┌─────────────┐ │  │                  │  │ - columns    │
        │ │ Embed:      │ │  │ ~150 points      │  │              │
        │ │ nomic-embed │ │  │ (connection_id   │  │ Primary Key: │
        │ │ (768-dim)   │ │  │  + table/col     │  │ connection_id│
        │ └─────────────┘ │  │  type)           │  │              │
        │                 │  │                  │  │              │
        └─────────────────┘  └──────────────────┘  └──────────────┘
                    │                ▼
                    │        ┌──────────────────────┐
                    │        │  REMOTE USER DB      │
                    │        │  (Neon/MySQL/PG)     │
                    │        │                      │
                    └───────▶│  - Execute SQL       │
                             │  - Fetch results     │
                             │  - Return rows       │
                             └──────────────────────┘
```

### Component Responsibilities

| Component | Role | Key Methods |
|-----------|------|------------|
| **ChatService** | Main orchestrator; routes requests to catalog or data path | `process_query()`, `_handle_catalog_query()`, `_build_schema_context()` |
| **OllamaService** | LLM interface; classifies intent and generates SQL | `classify_intent()`, `generate_sql()`, `embed_text()` |
| **VectorService** | Qdrant interface; finds relevant tables via semantic search | `search()` |
| **Catalog Handler** | Queries information_schema & pg_catalog on target DB | Pattern-based regex matching for schema, indexes, FK, PK, constraints |
| **MetadataDB** | Central PostgreSQL; stores schema snapshot of all registered DBs | `databases`, `tables`, `columns`, `connections` |
| **Remote User DB** | Target database (Neon, MySQL, PostgreSQL, etc.) | SQL execution endpoint |

### Data Flow: Two Query Paths

#### Path A: **Catalog Queries** (Structural/Metadata)
```
User: "Describe the track table"
       │
       ▼ (contains "describe" keyword)
Pre-check hits → route to catalog
       │
       ▼
Regex match: describe (the) X (table)
       │
       ▼
Query: SELECT * FROM information_schema.columns WHERE table_name='track'
       │
       ▼
Format & return: {columns: [{name: track_id, type: integer}, ...]}
```

#### Path B: **Data Queries** (Analytics/Reporting)
```
User: "Show total revenue per genre"
       │
       ▼ (no structural keyword)
LLM classify_intent → "data"
       │
       ▼
embed(prompt) → vector_search(Qdrant)
       │
       ▼
Find tables: [invoice_line, track, genre]
       │
       ▼
_build_schema_context → fetch columns from MetadataDB
       │
       ▼
LLM generate_sql → "SELECT g.name, SUM(...) FROM genre g ..."
       │
       ▼
Execute on Remote DB
       │
       ▼
Format & return: {answer: "...", sql: "...", rows: [...]}
```

---

## Page 3: Sample Requests & Tested Scenarios

### Successfully Tested Queries

All queries tested against **Neon Postgres Chinook database** (connection_id=3, 11 tables).

#### Structural/Catalog Queries

```bash
# 1. List all tables
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "List all tables in the database",
    "top_k_tables": 3
  }'

# Response:
{
  "status": "success",
  "answer": "Tables in database:\n  - album\n  - artist\n  - customer\n  - employee\n  - genre\n  - invoice\n  - invoice_line\n  - media_type\n  - playlist\n  - playlist_track\n  - track"
}
```

```bash
# 2. Describe table schema
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "Describe the track table",
    "top_k_tables": 3
  }'

# Response:
{
  "status": "success",
  "answer": "Schema of 'track':\n  track_id — integer\n  name — character varying\n  album_id — integer (nullable)\n  media_type_id — integer\n  genre_id — integer (nullable)\n  composer — character varying (nullable)\n  milliseconds — integer\n  bytes — integer (nullable)\n  unit_price — numeric"
}
```

```bash
# 3. Show indexes
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "What indexes exist on invoice table",
    "top_k_tables": 3
  }'

# Response:
{
  "status": "success",
  "answer": "Indexes on 'invoice':\n  invoice_customer_id_idx: (customer_id)\n  invoice_pkey: (invoice_id)"
}
```

```bash
# 4. Primary key
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "What is the primary key of artist table",
    "top_k_tables": 3
  }'

# Response:
{
  "status": "success",
  "answer": "Primary key of 'artist': artist_id"
}
```

```bash
# 5. Foreign keys
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "Show foreign keys on album table",
    "top_k_tables": 3
  }'

# Response:
{
  "status": "success",
  "answer": "Foreign keys of 'album':\n  artist_id → artist.artist_id"
}
```

```bash
# 6. Constraints
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "Show constraints on track table",
    "top_k_tables": 3
  }'

# Response:
{
  "status": "success",
  "answer": "Constraints on 'track':\n  [PRIMARY KEY] track_pkey: track_id\n  [FOREIGN KEY] track_album_id_fkey: album_id\n  [FOREIGN KEY] track_genre_id_fkey: genre_id\n  [FOREIGN KEY] track_media_type_id_fkey: media_type_id"
}
```

```bash
# 7. Row count
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "How many rows are in the track table",
    "top_k_tables": 3
  }'

# Response:
{
  "status": "success",
  "answer": "Row count of 'track': 3,503"
}
```

```bash
# 8. Active connections
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "How many active connections are there",
    "top_k_tables": 3
  }'

# Response:
{
  "status": "success",
  "answer": "Open connections: 1\n\nActive queries:\n  pid=571 state=active duration=-1 day, 23:59:59.863273"
}
```

#### Analytical/Data Queries

```bash
# 9. Simple count
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "How many artists are in the database?",
    "top_k_tables": 3
  }'

# Response:
{
  "status": "success",
  "answer": "Found 275 artists in the database.",
  "sql": "SELECT COUNT(*) FROM artist;",
  "rows": [[275]],
  "columns": ["count"],
  "row_count": 1,
  "execution_time_ms": 245,
  "query_time_ms": 12
}
```

```bash
# 10. Multi-table join
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "Show total revenue per genre by joining invoice lines, tracks and genres",
    "top_k_tables": 5
  }'

# Response:
{
  "status": "success",
  "answer": "Revenue breakdown by genre (24 genres):\n  Rock: $1,345.23\n  Jazz: $823.45\n  Classical: ...",
  "sql": "SELECT g.name, SUM(il.quantity * il.unit_price) as total FROM genre g JOIN track t ON g.genre_id = t.genre_id JOIN invoice_line il ON t.track_id = il.track_id GROUP BY g.name ORDER BY total DESC;",
  "rows": [[24 rows of data]],
  "columns": ["name", "total"],
  "row_count": 24,
  "execution_time_ms": 523,
  "query_time_ms": 18
}
```

```bash
# 11. All records retrieval
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "Give all artists with their album count",
    "top_k_tables": 3
  }'

# Response:
{
  "status": "success",
  "answer": "Retrieved 275 artists with their album counts.",
  "sql": "SELECT a.artist_id, a.name, COUNT(al.album_id) as album_count FROM artist a LEFT JOIN album al ON a.artist_id = al.artist_id GROUP BY a.artist_id, a.name ORDER BY a.name;",
  "rows": [[275 rows of data]],
  "columns": ["artist_id", "name", "album_count"],
  "row_count": 275,
  "execution_time_ms": 612,
  "query_time_ms": 25
}
```

### Request/Response Schema

```json
{
  "request": {
    "connection_id": 3,
    "prompt": "string (natural language question)",
    "top_k_tables": 5
  },
  "response_success": {
    "status": "success",
    "answer": "string (formatted answer)",
    "sql": "string (executed SQL or null for catalog)",
    "rows": "list of tuples (data rows)",
    "columns": "list of strings (column names)",
    "row_count": "integer",
    "execution_time_ms": "integer (total request time)",
    "query_time_ms": "integer (SQL execution time, null for catalog)"
  },
  "response_error": {
    "status": "error",
    "error": "string (error message)",
    "execution_time_ms": "integer"
  }
}
```

---

**Document Version:** 1.0 | **Date:** February 2026 | **Branch:** fix/catalog-query-routing
