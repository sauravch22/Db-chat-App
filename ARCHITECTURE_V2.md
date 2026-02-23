# DbChat v2 — High Level Design

> **Core Philosophy:** Correctness over speed. Schema-awareness over keyword matching. Graceful degradation over hard failures.
>
> The system must work equally well on an 11-table demo DB and a 2000-table enterprise ERP. Every design decision must hold at both extremes.

---

## Table of Contents

1. [What is DbChat](#1-what-is-dbchat)
2. [Current State — v1](#2-current-state--v1)
   - [Component Map](#21-component-map)
   - [Query Flow](#22-v1-query-flow)
   - [Qdrant Embedding Structure](#23-v1-qdrant-embedding-structure)
3. [Gaps Identified in v1](#3-gaps-identified-in-v1)
4. [v2 Architecture](#4-v2-architecture)
   - [Component Map](#41-component-map)
5. [New and Modified Services](#5-new-and-modified-services)
   - [OllamaService](#51-ollamaservice--extended)
   - [VectorService](#52-vectorservice--repositioned)
   - [MetadataService](#53-metadataservice--new-service)
   - [OnboardingService](#54-onboardingservice--extended)
   - [ChatService](#55-chatservice--revised-orchestration)
6. [v2 Query Pipeline — Full Flow](#6-v2-query-pipeline--full-flow)
7. [v2 Onboarding Pipeline](#7-v2-onboarding-pipeline)
8. [Data Freshness and Refresh](#8-data-freshness-and-refresh)
9. [Admin API — Extended](#9-admin-api--extended)
10. [Gap → Solution Mapping](#10-gap--solution-mapping)
11. [Phased Rollout](#11-phased-rollout)

---

## 1. What is DbChat

DbChat is a natural language to SQL query engine that sits between a user and any relational (or non-relational) database. The user sends a plain English question; the system returns structured data rows and a human-readable answer.

**v1 was built to prove the pipeline works. v2 is built to make it correct at scale.**

---

## 2. Current State — v1

### 2.1 Component Map

```
┌─────────────────────────────────────────────────────────┐
│                        Client                           │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP POST /api/chat
                           ▼
┌─────────────────────────────────────────────────────────┐
│                     FastAPI (serve.py)                  │
│  Routes: /api/chat  /api/admin  /health                 │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                     ChatService                         │
│  - Orchestrates the full query pipeline                 │
│  - Owns all branching logic (catalog vs data)           │
│  - Calls OllamaService, VectorService, MetadataDB       │
│  - Executes SQL on the user's remote DB                 │
└────┬──────────────┬──────────────┬───────────────┬──────┘
     │              │              │               │
     ▼              ▼              ▼               ▼
┌─────────┐  ┌───────────┐  ┌──────────┐  ┌────────────┐
│ Ollama  │  │  Qdrant   │  │Postgres  │  │ Remote DB  │
│ Service │  │  Vector   │  │Metadata  │  │(User's DB) │
│         │  │  Store    │  │   DB     │  │            │
│ LLM:    │  │           │  │          │  │ Neon/PG/   │
│llama3.2 │  │collection:│  │tables:   │  │ MySQL etc  │
│         │  │dbchat_    │  │connectns │  │            │
│ Embed:  │  │embeddings │  │databases │  │            │
│nomic-   │  │           │  │tables    │  │            │
│embed    │  │ ~150 pts  │  │columns   │  │            │
└─────────┘  └───────────┘  └──────────┘  └────────────┘
```

### 2.2 v1 Query Flow

```
User Prompt
    │
    ▼
classify_intent (LLM) ──── catalog ──▶ _handle_catalog_query
    │                                         │
    ▼ data                                    │ (empty answers fallback)
    │◄────────────────────────────────────────┘
    ▼
embed(prompt) → vector_search(Qdrant, top_k*10, filter: connection_id)
    │
    ▼
extract table names (table-type first, column-type fallback)
    │
    ▼
_build_schema_context (fetch columns from PostgreSQL metadata)
    │
    ▼
generate_sql (LLM) → sanitize backticks → fix pluralized names (regex)
    │
    ▼
_validate_sql → execute on Remote DB → format_answer (LLM) → return
```

### 2.3 v1 Qdrant Embedding Structure

Each point in the collection stores:

```json
{
  "payload": {
    "connection_id": 3,
    "type": "table | column",
    "table_name": "genre",
    "column_name": null
  },
  "vector": ["768-dim float array"]
}
```

---

## 3. Gaps Identified in v1

| # | Gap | Symptom Observed | Root Cause |
|---|-----|-----------------|------------|
| G1 | Vector search returns column embeddings preferentially over table embeddings | "No relevant tables found" for short prompts | Column text scores higher cosine similarity than table text for short queries |
| G2 | LLM hallucinates table names from user prompt words | `genres`, `invoice_lines` used instead of `genre`, `invoice_line` | LLM generates names freely; prompt words leak into SQL as table names |
| G3 | Vector search is the sole table discovery mechanism | For multi-join queries (3+ tables), 1–2 relevant tables are missed | top_k limit cuts off lower-scoring but necessary tables |
| G4 | No table summary separated from column schema | At 500+ tables, sending all column schemas blows the LLM context window | Table and column metadata always treated as one unit |
| G5 | No confidence check after SQL generation | Wrong SQL executes silently, returns wrong data or a runtime error | Nothing verifies that generated SQL tables actually match the intent |
| G6 | Data variation invisible to the pipeline | A wide table storing multiple logical entity types is treated as one flat schema | Only structural metadata (columns) is embedded, not data values within |
| G7 | Single retrieval path, no fallback tiers | Any failure in vector search = complete pipeline failure | No graceful degradation design |

---

## 4. v2 Architecture

### 4.1 Component Map

```
┌──────────────────────────────────────────────────────────────────┐
│                            Client                                │
└─────────────────────────────┬────────────────────────────────────┘
                              │ HTTP
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                       FastAPI (serve.py)                         │
│  /api/chat   /api/admin   /api/onboard   /health                 │
└──────┬───────────────┬──────────────────┬────────────────────────┘
       │               │                  │
       ▼               ▼                  ▼
┌────────────┐  ┌─────────────┐  ┌──────────────────┐
│ChatService │  │AdminService │  │ OnboardingService│
│            │  │             │  │                  │
│Query       │  │Connection   │  │Schema extraction │
│orchestrat- │  │management   │  │Summary generation│
│ion v2      │  │Metadata CRUD│  │Data sampling     │
│            │  │Summary edit │  │Embedding pipeline│
└─────┬──────┘  └──────┬──────┘  └────────┬─────────┘
      │                │                  │
      │    ┌───────────┘                  │
      ▼    ▼                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                          Service Layer                           │
│                                                                  │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────────┐  │
│  │OllamaService │  │VectorService  │  │MetadataService       │  │
│  │              │  │               │  │                      │  │
│  │classify_     │  │search()       │  │get_table_summaries() │  │
│  │intent()      │  │  ↳ fallback   │  │get_column_schema()   │  │
│  │              │  │    only       │  │get_all_tables()      │  │
│  │identify_     │  │               │  │upsert_summary()      │  │
│  │tables() [NEW]│  │search_data_   │  │                      │  │
│  │              │  │variations()   │  │                      │  │
│  │generate_sql()│  │[NEW]          │  │                      │  │
│  │              │  │               │  │                      │  │
│  │verify_intent_│  │               │  │                      │  │
│  │similarity()  │  │               │  │                      │  │
│  │[NEW]         │  │               │  │                      │  │
│  │              │  │               │  │                      │  │
│  │embed_text()  │  │               │  │                      │  │
│  └──────┬───────┘  └───────┬───────┘  └──────────┬───────────┘  │
└─────────┼──────────────────┼──────────────────────┼─────────────┘
          │                  │                      │
          ▼                  ▼                      ▼
    ┌──────────┐       ┌──────────┐          ┌──────────────┐
    │  Ollama  │       │  Qdrant  │          │  PostgreSQL  │
    │          │       │          │          │  Metadata DB │
    │llama3.2  │       │collection│          │              │
    │nomic-    │       │dbchat_   │          │ connections  │
    │embed-text│       │embeddings│          │ databases    │
    │          │       │          │          │ tables       │
    │          │       │ type:    │          │ columns      │
    │          │       │  table   │          │ summaries[+] │
    │          │       │  column  │          │              │
    │          │       │  data[+] │          │              │
    └──────────┘       └──────────┘          └──────────────┘
                                                     │
                                              ┌──────┘
                                              ▼
                                       ┌──────────────┐
                                       │  Remote DB   │
                                       │ (User's DB)  │
                                       │              │
                                       │ Postgres     │
                                       │ MySQL        │
                                       │ NoSQL (fut.) │
                                       └──────────────┘
```

---

## 5. New and Modified Services

### 5.1 OllamaService — Extended

**Currently does:** `classify_intent`, `generate_sql`, `embed_text`

---

#### `identify_tables(prompt, table_summary_list) → List[str]` ✦ NEW

- **Purpose:** Primary table discovery — replaces vector search as the first retrieval step
- **Input:** User prompt + list of all `{table_name, summary}` for the connection, fetched from PostgreSQL
- **Output:** A JSON array of exact table names chosen strictly from the provided list
- **Why this matters:** The LLM is selecting from a given list, not generating new names. Hallucination is structurally impossible. It reasons on natural language summaries rather than cosine-matching embeddings, meaning it understands semantic intent across all tables simultaneously.
- **Gaps addressed:** G2, G3

---

#### `verify_intent_similarity(prompt_embedding, table_summaries) → float` ✦ NEW

- **Purpose:** Post-generation confidence gate before SQL execution
- **Input:** Embedding of the original user prompt + summaries of the tables that appear in the generated SQL
- **Output:** Cosine similarity score (0.0 – 1.0)
- **Why this matters:** Catches cases where Layer 1 silently picked the wrong tables. Runs as a cheap embedding comparison — not a full LLM call.
- **Gaps addressed:** G5

---

#### `generate_sql()` — Modified

- Receives a new `data_hints` parameter (filter suggestions from data variation embeddings)
- Exact table names still injected as hard constraint in the system prompt
- Data hints passed as optional WHERE clause suggestions

---

### 5.2 VectorService — Repositioned

**Currently does:** Single search across all embedding types, result used directly for table discovery

---

#### `search()` — Demoted to fallback only

- Invoked only when `identify_tables()` (LLM Layer 1) fails or returns empty/invalid results
- Scoped to `type: "table"` embeddings only in fallback mode
- **Gaps addressed:** G1, G7

---

#### `search_data_variations(prompt_embedding, table_names, connection_id) → List[Dict]` ✦ NEW

- Searches only `type: "data"` embeddings, scoped to already-identified tables
- Not a full collection scan — bounded by the table list from Layer 1
- Returns matching column values with scores, **weighted at 0.6× of schema scores** so data signals never override structural signals
- Used to generate filter hints for the SQL generator (e.g. suggests `WHERE event_type = 'payment_failed'`)
- **Gaps addressed:** G6

---

#### Extended Qdrant Embedding Structure

```json
// Existing — unchanged
{
  "payload": {
    "connection_id": 3,
    "type": "table | column",
    "table_name": "genre",
    "column_name": null
  }
}

// New — data variation point
{
  "payload": {
    "connection_id": 3,
    "type": "data",
    "table_name": "events",
    "column_name": "event_type",
    "value": "payment_failed",
    "sampled_at": "2026-02-24T00:00:00Z"
  }
}
```

---

### 5.3 MetadataService — New Service

**Currently:** Schema queries are written inline inside `ChatService._build_schema_context()`

**v2:** Promoted to a dedicated service responsible for all PostgreSQL metadata reads and writes. Decouples orchestration logic in ChatService from the storage layer.

#### Methods

| Method | Purpose |
|--------|---------|
| `get_table_summaries(connection_id)` | Returns compact `[{name, summary}]` list fed to `identify_tables()` |
| `get_column_schema(connection_id, table_names)` | Returns formatted column schema for shortlisted tables only |
| `get_all_table_names(connection_id)` | Returns all known table names as the allowed-names constraint |
| `upsert_summary(table_id, summary)` | Called during onboarding; also available via admin API for human override |

#### PostgreSQL Schema Addition

```sql
ALTER TABLE tables ADD COLUMN summary TEXT;
ALTER TABLE tables ADD COLUMN summary_generated_at TIMESTAMP;
ALTER TABLE tables ADD COLUMN summary_human_override BOOLEAN DEFAULT FALSE;
```

---

### 5.4 OnboardingService — Extended

**Currently does:** Extract schema → embed tables+columns → store metadata

**New steps added:**

#### Step 3 (new): Generate Table Summaries

For each table, one LLM call generates a one-sentence natural language summary:

```
Input:
  Table: invoice_line
  Columns: invoice_line_id (int), invoice_id (int), track_id (int),
           unit_price (numeric), quantity (int)
  Prompt: "Write one sentence describing what this table stores."

Output:
  "Stores individual line items of customer invoices, each referencing
   a track with its unit price and quantity purchased."
```

- Run async in batches of 10 tables — one-time cost per connection
- Stored in `tables.summary` in PostgreSQL
- Human-editable via admin API; `summary_human_override = TRUE` prevents auto-regeneration on refresh

#### Step 4 (new): Data Variation Sampling and Embedding

For each table, identify high-cardinality categorical columns. Sample up to 50 distinct values per column. Embed each value and store in Qdrant with `type: "data"`.

**Columns targeted:**
- Data type: `VARCHAR`, `TEXT`, `ENUM`
- Cardinality: between 5 and 10,000 (pure IDs excluded, free-text blobs excluded)
- Column name hints: `type`, `status`, `category`, `kind`, `event`, `role`, `state`

---

### 5.5 ChatService — Revised Orchestration

**Currently:** Single linear pipeline with vector search as the sole entry point for table discovery

**v2:** Three-layer retrieval with explicit fallback tiers at each layer

| Layer | Mechanism | Fallback |
|-------|-----------|---------|
| Layer 1 | LLM reasons over table summaries | Vector search on table-type embeddings |
| Layer 2 | Column schema fetch from PostgreSQL | — (deterministic, no fallback needed) |
| Layer 3 | Data variation embedding search (optional) | Skip gracefully if no data embeddings exist yet |

---

## 6. v2 Query Pipeline — Full Flow

```
User Prompt
    │
    ▼
[1] classify_intent (OllamaService)
    ├── catalog → _handle_catalog_query → (empty fallback → data path)
    └── data ──────────────────────────────────────────────────────┐
                                                                   ▼
[2] MetadataService.get_table_summaries(connection_id)
    │  Fetches: [{name: "genre", summary: "Lookup table of..."},...]
    │  Source: PostgreSQL — fast, no vector search required
    │
    ▼
[3] OllamaService.identify_tables(prompt, summary_list)   ← LLM Call 1
    │  Input:  prompt + all table summaries for the connection
    │  Output: ["invoice_line", "track", "genre"]
    │
    ├── SUCCESS → table_names = LLM result (exact names from provided list)
    │
    └── FAILURE (empty / malformed JSON / names not in known list)
              │
              ▼
         [3F] VectorService.search(prompt_embedding,
                   filter: type=table, connection_id)     ← Fallback
              table_names = vector search result
    │
    ▼
[4] MetadataService.get_column_schema(connection_id, table_names)
    │  Fetches full column details ONLY for identified tables
    │  Context window stays small regardless of total table count
    │
    ▼
[5] VectorService.search_data_variations(prompt_embedding,
         table_names, connection_id)                      ← Optional Layer 3
    │  Returns: [{table, column, value, score}]
    │  Scores weighted at 0.6× — never overrides schema signals
    │  Generates filter hints passed to SQL generator
    │
    ▼
[6] OllamaService.generate_sql(prompt, schema, exact_names,
         data_hints)                                      ← LLM Call 2
    │  Exact table names injected as hard constraint
    │  Data hints injected as optional WHERE clause suggestions
    │
    ▼
[7] OllamaService.verify_intent_similarity(
         prompt_embedding, used_table_summaries)          ← Cosine check (cheap)
    │
    ├── score ≥ 0.65 → proceed to execution
    │
    └── score < 0.65 → RETRY CHAIN
              │
              ├── Attempt 2: re-run identify_tables with stricter prompt
              ├── Attempt 3: fall back to full vector search path
              └── Attempt 4: return error with explanation of tables considered
    │
    ▼
[8] _validate_sql → execute on Remote DB → format_answer → return
```

---

## 7. v2 Onboarding Pipeline

```
Connection registered
    │
    ▼
[1] Connect to Remote DB
    │
    ▼
[2] Extract schema — tables + columns + types
    │  → Store in PostgreSQL metadata (unchanged)
    │
    ▼
[3] Generate table summaries (OllamaService, async batches of 10)
    │  → Store in tables.summary (PostgreSQL)
    │
    ▼
[4] Embed table-type vectors (unchanged)
    │  → Upsert to Qdrant (type: "table")
    │
    ▼
[5] Embed column-type vectors (unchanged)
    │  → Upsert to Qdrant (type: "column")
    │
    ▼
[6] Sample data variations per high-cardinality column
    │  → Embed each distinct value
    │  → Upsert to Qdrant (type: "data")
    │
    ▼
Onboarding complete
```

---

## 8. Data Freshness and Refresh

| Data Type | Staleness Risk | Refresh Strategy |
|---|---|---|
| Table schema | Low — DDL changes rarely | Re-run on admin trigger or DDL change detection |
| Table summaries | Low — changes only when schema changes | Re-generate on schema change; skip if `summary_human_override = TRUE` |
| Column embeddings | Low | Re-run on schema change |
| Data variation embeddings | **High** — data changes constantly | Scheduled background job; configurable per connection (hourly / daily / manual) |

A `data_embedding_refresh_log` table tracks per-column last-sampled timestamps and refresh status.

---

## 9. Admin API — Extended

| Endpoint | v1 | v2 |
|---|---|---|
| `POST /api/admin/connections` | ✅ | ✅ |
| `GET /api/admin/connections` | ✅ | ✅ |
| `POST /api/onboard` | ✅ | ✅ extended with steps 3–6 |
| `GET /api/admin/summaries/{connection_id}` | ❌ | ✅ view all table summaries |
| `PUT /api/admin/summaries/{table_id}` | ❌ | ✅ human override of a summary |
| `POST /api/admin/refresh-data-embeddings/{connection_id}` | ❌ | ✅ trigger data re-sampling |

---

## 10. Gap → Solution Mapping

| Gap | v1 Patch Applied | v2 Solution |
|---|---|---|
| G1: Column embeddings score higher than table embeddings | `top_k*10` + priority sort | Vector search demoted to fallback; table discovery by LLM reasoning over summaries |
| G2: LLM hallucinates table names | Regex pluralization fix + exact names in system prompt | LLM selects from a provided list — hallucination structurally impossible |
| G3: Multi-join tables missed by vector search | Increased limit | LLM reasons over all table summaries simultaneously |
| G4: Large DB blows LLM context window | Not addressed | Table-summary-only Layer 1; column schema fetched only for shortlisted tables |
| G5: No confidence check on generated SQL | Not addressed | Post-generation cosine similarity check with three-attempt retry chain |
| G6: Data variation inside tables invisible | Not addressed | Data-type embeddings at 0.6× weight; filter hints passed to SQL generator |
| G7: Single retrieval path, no fallback | Catalog→data fallback only | Three-layer retrieval with explicit fallback at each layer |

---

## 11. Phased Rollout

**Phase 1 — LLM Table Identification (immediate)**
Implement `identify_tables()` + `MetadataService` + table summary generation at onboarding. Test on chinook. This alone eliminates the hallucination problem cleanly and is the highest-value change.

**Phase 2 — Post-Generation Verification**
Add `verify_intent_similarity()` as a confidence gate. Low implementation cost, high correctness gain. Retry chain handles edge cases.

**Phase 3 — Data Variation Embeddings**
Implement data sampling, `search_data_variations()`, and filter hints. Test on a medium-scale DB (hundreds of tables, millions of rows). Validate that 0.6× weighting keeps schema signals dominant.

**Phase 4 — Enterprise Scale**
Async summary refresh, data embedding staleness tracking via `data_embedding_refresh_log`, parallel LLM calls for batch summary generation, per-connection configuration (disable data embeddings for connections where it is not useful).
