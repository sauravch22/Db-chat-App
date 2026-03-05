<p align="center">
  <img src="https://img.shields.io/badge/DbChat-v14.0-7c6eff?style=for-the-badge&logo=postgresql&logoColor=white" alt="DbChat v14.0"/>
  <img src="https://img.shields.io/badge/Python-3.11+-3776ab?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/LLM--Powered-Qwen3--Coder-ff6f00?style=for-the-badge&logo=openai&logoColor=white" alt="LLM Powered"/>
</p>

<h1 align="center">🗃️ DbChat</h1>
<h3 align="center">Enterprise-Grade Natural Language SQL Assistant</h3>
<p align="center"><em>Talk to any database in plain English. Get tables, charts, dashboards — zero SQL knowledge required.</em></p>

---

# PAGE 1 — USE CASES & WHAT IS DbChat

## Who Is This For?

### 🏢 Business Analyst Self-Service
Marketing, finance, and ops teams need answers **now** — not after a JIRA ticket, a sprint cycle, and an analyst's calendar opens up. Connect a database, grant access, and anyone types *"Show me email campaign performance this quarter"* to get instant results with auto-generated charts.

### 📊 Executive Dashboard
A CTO or VP pins queries like *"Daily active users this month"*, *"Revenue by product line"*, and *"Top 5 churned accounts"* to a personal dashboard. One click refreshes every pin against **live production data** — no analyst needed, no stale CSVs.

### 🔍 Data Exploration & Discovery
A new data engineer joins a team with a 200-table database and no documentation. They ask: *"What tables exist?"*, *"Describe the customers table"*, *"Show me foreign keys for the orders table"* — and get structured, accurate answers from indexed metadata without writing a single query.

### 🛡️ Compliance & Auditing
SOC2 and GDPR audits demand proof of who accessed what data and when. DbChat's activity logs capture every login, every query, every permission change — with timestamps, IP addresses, user agents, durations, and success/failure status. Admins filter by user, database, action type, and time window.

### 🏗️ Multi-Database Organizations
Companies with separate databases for billing, analytics, and CRM register all of them in DbChat. Finance sees only billing, sales sees only CRM, and engineering sees everything. **Per-user, per-database permissions** ensure data isolation without deploying separate tools.

### 🔒 Air-Gapped / On-Premise Deployment
Healthcare, defense, and government organizations that **cannot** send data to cloud APIs deploy DbChat entirely on-premise. Local LLM via Ollama, local vector DB, local metadata store — every byte stays inside the network perimeter.

---

## The Problem

Business teams drown in data they **can't access**. Every "quick question" — *What were last month's sales? Who are our top customers? Is revenue trending up?* — requires filing a ticket, waiting for an analyst, or learning SQL. Existing BI tools demand configuration, custom dashboards, and training.

## The Solution

**DbChat** is a self-hosted, LLM-powered natural language SQL assistant that lets **anyone** query databases by typing plain English questions. It doesn't just return raw tables — it provides **smart chart recommendations**, **pinnable dashboards**, **persistent chat history**, and **enterprise-grade access control** — all through a sleek dark-themed web interface.

---

## Capabilities

| | Feature | Description |
|---|---|---|
| 💬 | **Natural Language Chat** | Ask questions in plain English. DbChat classifies intent, selects relevant tables, generates SQL, executes it, and returns formatted results — all in one round-trip. |
| 📊 | **Smart Chart Recommendations** | Every query result is automatically analyzed by the Viz Service. It suggests bar, line, pie, scatter, or area charts with one-click rendering via Chart.js. |
| 📌 | **Pin to Dashboard** | Pin any query result — chart or raw table — to a personal dashboard. Dashboards support **live refresh**, re-executing all pinned SQL against the latest data. |
| 🔐 | **JWT Auth + Per-DB RBAC** | Users sign up, log in with JWT tokens, and receive fine-grained permissions per database: **Admin** (onboard DBs), **Reindex** (refresh schema), **Query** (run prompts). |
| 📋 | **Full Activity Audit Log** | Every action is tracked — logins, queries, permission changes, reindexes — with timestamps, duration, IP, user agent, and status. Admins see global; users see their own. |
| 💾 | **Persistent Chat History** | Chat conversations persist across sessions, scoped per user and per database connection. Log back in and your previous queries are exactly where you left them. |
| 🔍 | **Data Explorer** | Click "Explore" on any result to open a modal with regex search, column filtering, and row highlighting — in both chat results and dashboard pins. |
| 🧠 | **Explain Query** | From any result with SQL, click **🧠 Explain** to get a step-by-step natural language breakdown of what the query does: tables used, joins, filters, aggregations, and how each column in the result is computed. |
| 🧠 | **Two-Step Reasoning Mode** | The LLM first reasons about which tables and joins are needed, then generates SQL — dramatically improving accuracy on complex multi-table queries. |
| 🗂️ | **Catalog Queries** | Ask structural questions like *"What tables exist?"*, *"Describe the orders table"* — handled directly from indexed metadata without SQL generation. |
| 🔗 | **Foreign Key Auto-Detection** | FKs are extracted during indexing and injected into every SQL prompt — the LLM generates correct JOINs without guessing. |
| 🧵 | **Thread-Based Conversations** | Messages are organized into threads with auto-generated titles. Start new threads, switch between conversations, and continue context from previous messages — just like a chat app. |
| 👋 | **Smart Onboarding** | When you connect to a database, the LLM analyzes every table and generates a plain-English summary of the database plus 7 diverse starter queries — so new users instantly know what to ask. |
| 🗄️ | **Multi-DB Support** | Connect PostgreSQL, MySQL, or SQL Server databases. Register as many as needed; each has its own schema index and permission scope. |

---

# PAGE 2 — ARCHITECTURE (Deep Dive)

## Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              METADATA STORE (PostgreSQL)                              │
│                                                                                      │
│  ┌──────────────┐       ┌──────────────┐       ┌──────────────┐                     │
│  │  connections  │──┐    │    users     │──┐    │  dashboards  │                     │
│  │──────────────│  │    │──────────────│  │    │──────────────│                     │
│  │ id (PK)      │  │    │ id (PK)      │  │    │ id (PK)      │                     │
│  │ name         │  │    │ username     │  │    │ name         │                     │
│  │ db_type      │  │    │ password_hash│  │    │ description  │                     │
│  │ host         │  │    │ is_admin     │  │    │ user_id (FK) │─────────────┐       │
│  │ port         │  │    │ is_active    │  │    │ created_at   │             │       │
│  │ username     │  │    │ created_at   │  │    └──────┬───────┘             │       │
│  │ password     │  │    └──────┬───────┘  │           │                     │       │
│  │ database     │  │           │          │           │ 1:N                 │       │
│  └──────┬───────┘  │           │          │           ▼                     │       │
│         │          │           │          │    ┌──────────────┐             │       │
│         │ 1:N      │           │ N:M      │    │dashboard_pins│             │       │
│         ▼          │           ▼          │    │──────────────│             │       │
│  ┌──────────────┐  │    ┌──────────────┐  │    │ id (PK)      │             │       │
│  │  databases   │  │    │  user_       │  │    │ dashboard_id │             │       │
│  │──────────────│  │    │  permissions │  │    │   (FK)       │             │       │
│  │ id (PK)      │  │    │──────────────│  │    │ title        │             │       │
│  │ connection_id│  │    │ id (PK)      │  │    │ pin_type     │             │       │
│  │   (FK)       │  │    │ user_id (FK) │  │    │ sql_query    │             │       │
│  │ name         │  │    │ connection_id│  │    │ chart_type   │             │       │
│  │ schema_hash  │  │    │   (FK)       │  │    │ chart_config │             │       │
│  │ indexed_at   │  │    │ permission   │  │    │ connection_id│             │       │
│  └──────┬───────┘  │    │  _type       │  │    │   (FK)       │             │       │
│         │          │    └──────────────┘  │    │ position     │             │       │
│         │ 1:N      │                      │    └──────────────┘             │       │
│         ▼          │                      │                                 │       │
│  ┌──────────────┐  │    ┌──────────────┐  │    ┌──────────────┐             │       │
│  │   tables     │  │    │ activity_logs│  │    │ chat_history  │             │       │
│  │──────────────│  │    │──────────────│  │    │──────────────│             │       │
│  │ id (PK)      │  │    │ id (PK)      │  │    │ id (PK)      │             │       │
│  │ database_id  │  │    │ user_id (FK) │  │    │ user_id (FK) │─────────────┘       │
│  │   (FK)       │  │    │ action       │  │    │ connection_id│                     │
│  │ name         │  │    │ detail       │  │    │   (FK)       │                     │
│  │ summary      │  │    │ connection_id│  │    │ thread_id    │                     │
│  │ embedding_id │  │    │ ip_address   │  │    │ thread_title │                     │
│  │ row_count    │  │    │ user_agent   │  │    │ prompt       │                     │
│  │ indexed      │  │    │ duration_ms  │  │    │ answer       │                     │
│  └──────┬───────┘  │    │ status       │  │    │ sql_generated│                     │
│         │          │    │ created_at   │  │    │ columns_json │                     │
│         │ 1:N      │    └──────────────┘  │    │ rows_json    │                     │
│         ▼          │                      │    │ execution_ms │                     │
│  ┌──────────────┐  │                      │    │ status       │                     │
│  │   columns    │  │                      │    │ created_at   │                     │
│  │──────────────│  │                      │    └──────────────┘                     │
│  │   columns    │  │    ┌──────────────┐  │                                         │
│  │──────────────│  │    │   queries    │  │    ┌──────────────────────┐              │
│  │ id (PK)      │  │    │──────────────│  │    │data_embedding_       │              │
│  │ table_id(FK) │  │    │ id (PK)      │  │    │  refresh_log         │              │
│  │ name         │  │    │ connection_id│  │    │──────────────────────│              │
│  │ data_type    │  │    │   (FK)       │  │    │ id (PK)              │              │
│  │ nullable     │  │    │ prompt       │  │    │ connection_id (FK)   │              │
│  │ is_primary   │  │    │ generated_sql│  │    │ table_name           │              │
│  │ sample_values│  │    │ status       │  │    │ column_name          │              │
│  └──────┬───────┘  │    │ execution_ms │  │    │ last_embedded_at     │              │
│         │          │    │ error        │  │    │ row_count_at_embed   │              │
│         │ 1:N      │    │ created_at   │  │    └──────────────────────┘              │
│         ▼          │    └──────────────┘  │                                         │
│  ┌──────────────┐  │                      │                                         │
│  │   samples    │  │    ┌──────────────┐  │                                         │
│  │──────────────│  │    │ foreign_keys │  │                                         │
│  │ id (PK)      │  │    │──────────────│  │                                         │
│  │ table_id(FK) │  │    │ id (PK)      │  │                                         │
│  │ data (JSON)  │  │    │ connection_id│──┘                                         │
│  └──────────────┘  │    │   (FK)       │                                            │
│                    │    │ src_table    │                                            │
│                    │    │ src_column   │                                            │
│                    └───→│ ref_table    │                                            │
│                         │ ref_column   │                                            │
│                         └──────────────┘                                            │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Relationship Summary:**
- `connections` → `databases` → `tables` → `columns` → `samples` (hierarchical schema chain)
- `connections` → `foreign_keys` (FK map per connection)
- `users` ↔ `connections` via `user_permissions` (N:M permission matrix)
- `users` → `dashboards` → `dashboard_pins` (personal dashboard ownership)
- `users` → `chat_history` (per-user, per-connection conversation persistence, organized by `thread_id`)
- `users` → `activity_logs` (audit trail per user)
- `connections` → `queries` (every generated SQL is logged)
- `connections` → `data_embedding_refresh_log` (tracks when each column's data samples were last embedded)

---

## System Architecture — How the Pieces Fit

```
                          ┌─────────────────────┐
                          │      Frontend        │
                          │  (Static SPA)        │
                          │                      │
                          │  Chat │ Dashboard    │
                          │  Admin│ Activity     │
                          └──────────┬───────────┘
                                     │ HTTP + JWT
                                     ▼
                          ┌─────────────────────┐
                          │    FastAPI Backend   │
                          │   (API Gateway)      │
                          │                      │
                          │  ChatService         │
                          │  IndexingService     │
                          │  SchemaService       │
                          │  AuthService         │
                          └──┬───┬───┬───┬───┬───┘
                             │   │   │   │   │
                ┌────────────┘   │   │   │   └────────────┐
                │                │   │   │                │
                ▼                ▼   │   ▼                ▼
      ┌──────────────┐  ┌──────────┐│┌──────────┐  ┌──────────────┐
      │  PostgreSQL   │  │  Redis   │││  Qdrant  │  │   Ollama     │
      │  (Metadata)   │  │ (Cache)  │││(Vectors) │  │ (Embeddings) │
      └──────────────┘  └──────────┘│└──────────┘  └──────────────┘
                                    │
                          ┌─────────┴─────────┐
                          │                   │
                          ▼                   ▼
                 ┌──────────────┐    ┌──────────────────┐
                 │  Remote LLM  │    │   Viz Service     │
                 │  (Qwen3-     │    │  (Lux + Pandas)   │
                 │  Coder-Next) │    │  Chart Recommend.  │
                 └──────────────┘    └──────────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  User's Target   │
                 │  Database        │
                 │  (PG/MySQL/MSSQL)│
                 └──────────────────┘
```

---

## Component Deep Dive

### PostgreSQL — The Metadata Store

PostgreSQL is the **single source of truth** for everything DbChat knows. It stores 14 tables across four domains:

**Schema Domain** — `connections`, `databases`, `tables`, `columns`, `samples`, `foreign_keys`, `data_embedding_refresh_log`

When an admin onboards a database, DbChat uses SQLAlchemy's `inspect()` to introspect the target database and stores a complete copy of its schema in PostgreSQL. This includes:
- Every table name with an LLM-generated natural language summary (e.g., *"The invoices table stores billing records linked to customers, with date and total amount"*)
- Every column with its data type, nullability, primary key status, and sample values
- Every foreign key relationship (source table/column → referenced table/column)
- Sample rows per table (JSON blobs) so the LLM can understand data patterns like date formats and enum values
- A `schema_hash` to detect drift — when the hash changes, DbChat knows the schema was altered and suggests re-indexing

The table summaries are critical: during query processing, the LLM reads these summaries to decide which tables are relevant to a user's question. This is far more effective than sending raw DDL — the summaries are written in the LLM's "language."

**Auth Domain** — `users`, `user_permissions`

Users are stored with bcrypt-hashed passwords. Permissions use an **N:M matrix**: each `user_permissions` row links a user to a specific connection with a specific permission type (`db_onboard`, `db_reindex`, `prompt_query`). This means User A can query Database X but not Database Y, while User B can reindex Database Y but cannot onboard new databases. The admin user (auto-seeded at first startup) receives all permissions on all connections.

**Activity Domain** — `activity_logs`, `queries`, `chat_history`

Every significant action flows through the activity logging pipeline. When a user logs in, it's logged. When a query is generated, both the `queries` table (for SQL analytics) and `activity_logs` (for audit trail) receive records. Chat history stores the first 50 rows of every result set, allowing users to scroll back through previous conversations without re-executing SQL. Messages are organized into **threads** — each thread has a UUID `thread_id` and an auto-generated `thread_title` (produced by the LLM from the first message). Users can switch between threads, rename them, or delete them.

**Dashboard Domain** — `dashboards`, `dashboard_pins`

Each user can create multiple dashboards. Pins store the **raw SQL** and **chart configuration** (Chart.js config JSON). When a dashboard is refreshed, the backend re-executes every pin's SQL against the live target database, checks that the user still has `prompt_query` permission on the pin's connection, and returns fresh results. This means dashboards are always live — never stale snapshots.

---

### Redis — The Cache Layer

Redis eliminates redundant computation at two critical points:

**Schema Context Caching** — When ChatService builds the DDL context string for SQL generation (the `CREATE TABLE ...` block with column definitions and FK annotations), the result is cached by connection ID and table set hash. If the same combination of tables is needed again within the TTL window, the pre-built context string is returned instantly instead of re-querying PostgreSQL and re-formatting.

**Catalog Query Caching** — When a user asks a catalog question like *"What tables exist?"* or *"Describe the orders table"*, the formatted response is cached by connection ID and prompt hash. Repeated catalog questions return in under 1ms.

Redis uses TTL-based expiry — schema context caches for 1 hour, catalog results for 30 minutes. When a reindex occurs, all cache keys for that connection are pattern-cleared (`KEYS schema:{connection_id}:*`), ensuring stale schema never leaks into prompts.

---

### Qdrant — The Vector Intelligence Layer

Qdrant is the **semantic backbone** of DbChat's table selection. It stores three types of 768-dimensional vectors (generated by `nomic-embed-text`), all using cosine similarity:

**Table Vectors** — Each table's context (name + column list + summary) is embedded and stored with payload metadata (`table_name`, `database_name`, `connection_id`, `type=table`). When a user asks *"Show me revenue trends"*, the prompt is embedded and Qdrant finds the most semantically similar table vectors — surfacing `invoices` and `customers` even though the word "revenue" doesn't appear in any column name.

**Column Vectors** — Individual column context strings are embedded for finer-grained matching. If a user asks about "email addresses," the vector search can surface the `customers.email` column specifically, even across hundreds of tables.

**Data Sample Vectors** — During indexing, categorical columns (low-cardinality text columns) have their distinct values sampled and embedded. If a user asks *"Show me orders from Germany"*, the data vector for `customers.Country` containing the value "Germany" boosts the relevance of the `customers` table.

**Hybrid Table Selection** — DbChat doesn't rely on vector search alone. It uses a two-phase approach:
1. **LLM-based selection**: The LLM reads all table summaries from PostgreSQL and picks which tables match the question
2. **Vector similarity verification**: Each LLM-selected table is cross-checked — its summary is embedded and compared against the user prompt with a cosine threshold of 0.35
3. **Vector fallback**: If the LLM's selections all fail verification, Qdrant's top-K search results are used instead

This hybrid approach combines the LLM's reasoning ability with vector search's semantic matching, catching cases where either approach alone would fail.

---

### Ollama — Local Embedding Engine

Ollama runs the `nomic-embed-text` model locally, generating 768-dimensional vectors. It is used **exclusively for embeddings** — not for SQL generation or natural language understanding.

**Why local?** Privacy. During indexing, every table name, column name, and data sample is sent through the embedding model. For organizations with sensitive schema metadata (table names like `patient_records`, `salary_bands`, `classified_projects`), sending these to a cloud API would violate data governance policies. Local Ollama ensures this metadata never leaves the network.

**When is it called?**
- **Indexing time**: Every table context, column context, and categorical data sample is embedded and stored in Qdrant
- **Query time**: The user's natural language prompt is embedded to enable vector search in Qdrant
- **Verification time**: Table summaries selected by the LLM are embedded and compared against the prompt embedding to verify relevance

---

### Remote LLM — Qwen3-Coder-Next

The remote LLM handles all **reasoning and code generation** tasks. It's accessed via an OpenAI-compatible API endpoint, allowing easy swapping to any model (GPT-4, Claude, Llama, Mistral) without code changes.

**Intent Classification** (Temperature: 0.0) — Given a user prompt, the LLM returns either `"data"` (needs SQL) or `"catalog"` (schema question). This is preceded by a keyword pre-check: prompts containing words like "describe," "schema," "structure," or "what tables" are fast-tracked to catalog without an LLM call.

**Table Identification** (Temperature: 0.0) — The LLM receives the user prompt plus all table summaries from PostgreSQL and returns a JSON list of relevant table names. This is the "which tables should I query?" step.

**SQL Generation with Reasoning** (Temperature: 0.0) — The most complex LLM task. In two-step reasoning mode:
- **Step A (Reasoning)**: The LLM receives the prompt + schema context and outputs a reasoning chain: *"The user wants revenue by country. I need customers (for Country) and invoices (for Total). They're linked by CustomerId. I should GROUP BY Country and SUM Total."*
- **Step B (SQL)**: The LLM receives the prompt + schema + Step A's reasoning and outputs pure SQL

The schema context injected includes `CREATE TABLE` DDL with column types, `FOREIGN KEY` annotations, sample data values, and explicit instructions to use only the provided tables/columns. Temperature 0.0 ensures deterministic, reproducible SQL.

**Answer Formatting** (Temperature: 0.3) — After SQL executes, the LLM formats the raw result rows into a natural language answer: *"The top customer is Helena Holý from Czech Republic with $49.62 in total spending."*

---

### Viz Service — Automatic Chart Intelligence

The Viz Service is a standalone microservice built on **Lux** (a Python library for automated data visualization) and **Pandas**. It analyzes query results and recommends the best chart type without any user configuration.

**How it works:**
1. The frontend sends query results (columns + rows) to the Viz Service's `/analyze` endpoint
2. Lux + Pandas detect each column's semantic type: **categorical** (country, genre), **temporal** (dates, timestamps), **quantitative** (amounts, counts)
3. Based on column type combinations, it selects chart types:
   - Categorical × Quantitative → **Bar chart**
   - Temporal × Quantitative → **Line chart**
   - Single categorical with proportions → **Pie chart**
   - Quantitative × Quantitative → **Scatter plot**
   - Multiple temporal series → **Area chart**
4. Returns up to 3 ranked `ChartRecommendation` objects, each containing a complete Chart.js configuration (labels, datasets, colors, axis titles) ready for frontend rendering

---

# PAGE 3 — FLOWS (Summarized)

## Flow 1: Authentication

A user submits credentials → the backend verifies the bcrypt hash → generates a JWT containing user ID and admin status → returns the token along with the user's per-database permission map. Every subsequent API call includes this JWT in the `Authorization` header. The backend decodes it on every request to enforce per-route and per-database access control. On first startup, the system auto-seeds an admin user with full permissions across all registered connections.

## Flow 2: Database Onboarding & Indexing

An admin submits connection details (host, credentials, database type) → the backend uses SQLAlchemy's `inspect()` to extract the full schema from the target database: table names, column definitions, data types, primary keys, and foreign key relationships. All metadata is stored in PostgreSQL. Then, for every table:

1. A **natural language summary** is generated by the LLM (*"The invoices table stores billing records with date, total, and customer reference"*)
2. The summary + column list is **embedded** via Ollama's `nomic-embed-text` into a 768-dimensional vector
3. The vector is **upserted into Qdrant** with metadata payload (table name, connection ID, type)
4. **Categorical columns** (low-cardinality text fields) have their distinct values sampled (`SELECT DISTINCT ... LIMIT 50`), embedded, and stored as data vectors in Qdrant

This indexing process is what makes DbChat "schema-aware" — every future query leverages this embedded knowledge to find the right tables.

## Flow 3: Natural Language Query (Core Flow)

This is the heart of DbChat, executing in five stages:

**Stage 1 — Intent Classification**: The user's prompt is checked against a keyword list for catalog patterns (`"what tables"`, `"describe"`, `"schema"`). If no keyword match, the LLM classifies the intent as either `data` (needs SQL) or `catalog` (schema question). Catalog questions are answered directly from PostgreSQL metadata — no SQL generation needed.

**Stage 2 — Table Selection**: The LLM reads all stored table summaries and returns which tables are relevant. Each selected table is then **verified** by embedding its summary and comparing cosine similarity to the embedded user prompt (threshold ≥ 0.35). Tables that fail verification are dropped. If all tables fail, the system falls back to Qdrant's top-K vector search results.

**Stage 3 — Schema Context Assembly**: For the verified tables, the backend fetches columns, data types, foreign keys, and sample values from PostgreSQL. It builds a `CREATE TABLE` DDL string annotated with FK relationships and sample data, then caches this in Redis for subsequent queries using the same tables.

**Stage 4 — SQL Generation**: In reasoning mode, the LLM first produces a reasoning chain (*"I need to JOIN customers and invoices via CustomerId, then GROUP BY Country"*), then generates the actual SQL using the schema context + reasoning as input. The SQL is validated to be a read-only `SELECT` statement — no mutations allowed.

**Stage 5 — Execution & Response**: The generated SQL is executed against the **user's target database** (not the metadata store). Results (columns + rows) are returned to the frontend, saved to `chat_history` for persistence, and logged in `activity_logs` for auditing. The frontend independently sends results to the Viz Service for chart recommendations.

### Explain Query Flow

From any chat response (or replayed history item) that includes SQL, the frontend exposes an **🧠 Explain** chip. Clicking it sends the original prompt, generated SQL, and optional schema/column metadata to the `/api/chat/explain` endpoint. The LLM returns a structured explanation covering:
- Which tables are used and why
- How joins are constructed (which foreign keys / columns)
- What filters, GROUP BY, HAVING, ORDER BY, and LIMIT clauses do
- How each key output column is computed

The explanation is rendered in a modal so users can quickly validate query intent, making it safe for non-SQL users to understand and discuss generated SQL with data teams.

### Thread-Based Conversations

Every message in DbChat belongs to a **thread**. Threads provide conversational context — when a user follows up with *"Now break that down by month"*, the LLM receives the last 10 messages from the current thread as context, so it knows what "that" refers to.

**Thread lifecycle:**
1. **Auto-creation**: The first message in a new conversation generates a UUID `thread_id`. The LLM simultaneously generates a short, descriptive title from the prompt (e.g., *"Top customers by spending"*) and stores it in `thread_title`.
2. **Sidebar navigation**: The frontend displays all threads in a collapsible sidebar, sorted by most recent. Clicking a thread loads its full message history.
3. **Title management**: Users can rename thread titles or let the auto-generated title stand.
4. **Thread deletion**: Deleting a thread removes all associated `chat_history` rows for that user/connection.
5. **Context injection**: When generating SQL, the last 10 messages from the active thread are injected into the LLM prompt as conversation history, enabling multi-turn reasoning.

**API endpoints**: `GET /api/chat/threads?connection_id=X` (list), `PUT /api/chat/threads/{thread_id}/title` (rename), `DELETE /api/chat/threads/{thread_id}` (delete).

### Smart Onboarding (Dynamic Welcome)

When a user selects a database connection, DbChat generates a **personalized welcome** instead of showing generic placeholder text.

**How it works:**
1. The frontend calls `GET /api/chat/welcome?connection_id=X`
2. The backend fetches all table summaries from PostgreSQL for that connection
3. The table summaries are sent to the LLM with a prompt requesting: a 2–3 sentence database overview and 7 diverse starter queries covering different tables, aggregation types, and complexity levels
4. The LLM returns a JSON response with `summary` (plain-English database description) and `suggestions` (array of 7 query strings)
5. The frontend renders the summary as a welcome message and the suggestions as clickable chips — clicking one auto-fills the chat input

**Why it matters:** New users connecting to an unfamiliar database no longer see a blank chat. They immediately understand what the database contains and have ready-made queries to explore.

## Flow 4: Dashboard Pin & Refresh

When a user pins a result, the **raw SQL**, chart type, and Chart.js config JSON are stored in `dashboard_pins`. Opening a dashboard triggers a **refresh**: the backend iterates over every pin, verifies the user still has `prompt_query` permission on the pin's connection, re-executes the stored SQL against the live target database, and returns fresh rows. This means dashboard data is always current — there are no stale snapshots, only live queries.

## Flow 5: Permission Management

Admins see a matrix of users × databases. Toggling a permission checkbox triggers an upsert to `user_permissions`, linking that user to that connection with the specified permission type. Three permission types exist:
- **`db_onboard`** — Can register new databases
- **`db_reindex`** — Can trigger schema re-indexing
- **`prompt_query`** — Can ask natural language questions

Every permission change is recorded in `activity_logs` with the admin's user ID, the target user, the connection, and the old/new permission state.

---

# PAGE 4 — COMPLEX QUERIES DbChat CAN SOLVE

Below are real-world complex queries that DbChat's two-step reasoning + FK-aware schema context can handle:

---

### 🔗 Multi-Table JOINs with Aggregation

**Prompt:** *"Show me the top 10 customers by total spending, including their country"*

```sql
SELECT c."FirstName" || ' ' || c."LastName" AS customer_name,
       c."Country",
       SUM(i."Total") AS total_spending
FROM customers c
JOIN invoices i ON i."CustomerId" = c."CustomerId"
GROUP BY c."CustomerId", c."FirstName", c."LastName", c."Country"
ORDER BY total_spending DESC
LIMIT 10;
```
**Why it's hard:** Requires JOIN inference across `customers` → `invoices` via FK, aggregation with GROUP BY, and aliasing.

---

### 📅 Time-Series Trends

**Prompt:** *"Monthly revenue trend for the last 2 years"*

```sql
SELECT DATE_TRUNC('month', i."InvoiceDate") AS month,
       SUM(i."Total") AS monthly_revenue
FROM invoices i
WHERE i."InvoiceDate" >= NOW() - INTERVAL '2 years'
GROUP BY DATE_TRUNC('month', i."InvoiceDate")
ORDER BY month;
```
**Why it's hard:** Requires `DATE_TRUNC`, relative date filtering with `INTERVAL`, and time-series ordering.

---

### 🧮 Subquery Comparisons (Above Average)

**Prompt:** *"Which customers spent more than the average customer?"*

```sql
SELECT c."FirstName" || ' ' || c."LastName" AS customer_name,
       SUM(i."Total") AS total_spent
FROM customers c
JOIN invoices i ON i."CustomerId" = c."CustomerId"
GROUP BY c."CustomerId", c."FirstName", c."LastName"
HAVING SUM(i."Total") > (
    SELECT AVG(customer_total) FROM (
        SELECT SUM(i2."Total") AS customer_total
        FROM invoices i2
        GROUP BY i2."CustomerId"
    ) sub
)
ORDER BY total_spent DESC;
```
**Why it's hard:** Requires a nested subquery to compute per-customer average, then compare each customer's total against it. The reasoning step explicitly plans: *"I need a subquery for the average of per-customer totals."*

---

### 🔀 Three-Way JOINs Across a Bridge Table

**Prompt:** *"Which genres have the most tracks sold?"*

```sql
SELECT g."Name" AS genre,
       COUNT(il."InvoiceLineId") AS tracks_sold
FROM genres g
JOIN tracks t ON t."GenreId" = g."GenreId"
JOIN invoice_items il ON il."TrackId" = t."TrackId"
GROUP BY g."GenreId", g."Name"
ORDER BY tracks_sold DESC
LIMIT 10;
```
**Why it's hard:** Three-table JOIN chain (`genres → tracks → invoice_items`) resolved automatically via FK metadata.

---

### 📊 Percentage / Proportion Calculations

**Prompt:** *"What percentage of total revenue comes from each country?"*

```sql
SELECT c."Country",
       SUM(i."Total") AS country_revenue,
       ROUND(SUM(i."Total") * 100.0 / (SELECT SUM("Total") FROM invoices), 2) AS pct
FROM customers c
JOIN invoices i ON i."CustomerId" = c."CustomerId"
GROUP BY c."Country"
ORDER BY pct DESC;
```
**Why it's hard:** Requires a scalar subquery for the denominator and floating-point arithmetic for percentage calculation.

---

### 🗓️ Comparative Time Periods

**Prompt:** *"Compare this month's revenue to last month"*

```sql
SELECT
    CASE WHEN DATE_TRUNC('month', i."InvoiceDate") = DATE_TRUNC('month', CURRENT_DATE)
         THEN 'This Month'
         ELSE 'Last Month' END AS period,
    SUM(i."Total") AS revenue
FROM invoices i
WHERE i."InvoiceDate" >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '1 month'
GROUP BY period
ORDER BY period DESC;
```
**Why it's hard:** Requires CASE expressions with relative date logic, grouping by computed columns.

---

### 🔍 Catalog / Schema Introspection

**Prompt:** *"What tables exist and how many rows does each have?"*

```
Handled without SQL — directly from indexed metadata:
┌─────────────────────┬───────────┐
│ Table               │ Row Count │
├─────────────────────┼───────────┤
│ albums              │       347 │
│ artists             │       275 │
│ customers           │        59 │
│ employees           │         8 │
│ genres              │        25 │
│ invoice_items       │     2,240 │
│ invoices            │       412 │
│ media_types         │         5 │
│ playlist_track      │     8,715 │
│ playlists           │        18 │
│ tracks              │     3,503 │
└─────────────────────┴───────────┘
```
**Why it's different:** The intent classifier detects "catalog" intent — metadata is read directly from PostgreSQL without any LLM or SQL generation.

---

### 🧩 FK-Aware Complex Path Resolution

**Prompt:** *"Show me all playlist names that contain tracks by the artist 'Iron Maiden'"*

```sql
SELECT DISTINCT p."Name" AS playlist_name
FROM playlists p
JOIN playlist_track pt ON pt."PlaylistId" = p."PlaylistId"
JOIN tracks t ON t."TrackId" = pt."TrackId"
JOIN albums al ON al."AlbumId" = t."AlbumId"
JOIN artists ar ON ar."ArtistId" = al."ArtistId"
WHERE ar."Name" = 'Iron Maiden';
```
**Why it's hard:** Five-table JOIN chain: `playlists → playlist_track → tracks → albums → artists`. The system's FK metadata provides the full join path. The reasoning step traces: *"playlists connects to tracks through the bridge table playlist_track, tracks connect to albums via AlbumId, albums connect to artists via ArtistId."*

---

<p align="center"><sub>Built with ❤️ — FastAPI · PostgreSQL · Qdrant · Redis · Ollama · Chart.js · Lux</sub></p>
