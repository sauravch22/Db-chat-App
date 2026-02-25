# v2 Architecture: Visual Flows & Diagrams

## 1. Onboarding Flow (Complete Data Collection)

```
┌─────────────────────────────────────────────────────────────────┐
│ USER: POST /api/admin/register-db                              │
│ {name, host, port, username, password, database, db_type}      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
                 ┌─────────────────────┐
                 │ Create Connection   │
                 │ + Database records  │
                 │ (PostgreSQL)        │
                 └─────────────┬───────┘
                               │
                  ┌────────────▼────────────┐
                  │ Schedule Background Job │
                  │ (Returns 202 Accepted)  │
                  └────────────┬────────────┘
                               │
      ┌────────────────────────┴────────────────────────────┐
      │   Background Task: _extract_and_index_database()    │
      └────────────────────────┬────────────────────────────┘
      
      PHASE 1: Schema Extraction
      ┌─────────────────────────────────────┐
      │ Connect to User's Database          │
      │ Extract: Tables, Columns, Types     │
      │ Time: 1-5 seconds                   │
      └────────────────┬────────────────────┘
                       │
                       ▼
      PHASE 2: Table Summary Generation
      ┌─────────────────────────────────────┐
      │ For each table:                     │
      │  - Read column names + types        │
      │  - Generate summary text            │
      │  - Store in Table.context           │
      │ Time: 1-2 seconds                   │
      └────────────────┬────────────────────┘
                       │
                       ▼
      PHASE 3: Data-Variation Sampling ← NEW in v2
      ┌─────────────────────────────────────┐
      │ For each categorical column:        │
      │  - Execute: SELECT DISTINCT         │
      │  - Get up to 50 distinct values     │
      │  - Store in Column.sample_values    │
      │    (first 20, as JSON)              │
      │ Time: 5-10 seconds                  │
      └────────────────┬────────────────────┘
                       │
                       ▼
      PHASE 4: Vector Embedding
      ┌─────────────────────────────────────┐
      │ For each table:                     │
      │  - Embed summary → Qdrant           │
      │    (type="table")                   │
      │ For each column:                    │
      │  - Embed column info → Qdrant       │
      │    (type="column")                  │
      │ For each data value:                │
      │  - Embed value → Qdrant             │
      │    (type="data")                    │
      │ Time: 10-20 seconds                 │
      │ Total embeddings: 100+              │
      └────────────────┬────────────────────┘
                       │
                       ▼
      PHASE 5: Mark Complete
      ┌─────────────────────────────────────┐
      │ Database.last_indexed_at = now()    │
      │ Table.is_indexed = True             │
      │ Ready for queries!                  │
      └─────────────────────────────────────┘

      TOTAL TIME: 30-60 seconds
      TOTAL STORAGE: 
        - PostgreSQL: ~2 MB (schema + summaries)
        - Qdrant: ~50 MB (vector embeddings)
```

---

## 2. Query Processing Flow (With v2 Data)

```
┌──────────────────────────────────────────┐
│ USER: POST /api/chat                     │
│ {connection_id: 5, prompt: "..."}        │
└──────────────┬──────────────────────────┘
               │
               ▼
    ┌────────────────────────────────┐
    │ ChatService.process_query()    │
    └────────────┬───────────────────┘
                 │
    ┌────────────▼───────────────────┐
    │ STEP 1: Get Table Summaries    │
    │ MetadataService.               │
    │   get_table_summaries()        │
    │                                │
    │ Source: Table.context (DB)     │
    │ Returns: [{                    │
    │   "name": "genre",             │
    │   "summary": "Table: genre..." │
    │ }, ...]                        │
    └────────────┬───────────────────┘
                 │
    ┌────────────▼───────────────────┐
    │ STEP 2: LLM Table Selection    │
    │ OllamaService.                 │
    │   identify_tables()            │
    │                                │
    │ Input: prompt + summaries      │
    │ LLM call (5-10 seconds)        │
    │ Output: ["genre", "album"]     │
    └────────────┬───────────────────┘
                 │
    ┌────────────▼───────────────────────────┐
    │ STEP 3: Intent Confidence Gate         │
    │ OllamaService.                         │
    │   verify_intent_similarity()           │
    │                                        │
    │ Compute: cosine_similarity(            │
    │   prompt_embedding,                    │
    │   selected_summary_text                │
    │ )                                      │
    │                                        │
    │ Gate: similarity >= 0.35?              │
    │ YES → Continue                         │
    │ NO  → Fallback to vector search        │
    └────────────┬───────────────────────────┘
                 │
       ┌─────────┴──────────┐
       │ (gate passed)      │ (gate failed)
       │                    │
       ▼                    ▼
    ┌──────────┐    ┌──────────────────┐
    │ Use LLM  │    │ Vector Fallback  │
    │selection │    │ (Layer 2)        │
    └────┬─────┘    └────┬─────────────┘
         │               │
         └───────┬───────┘
                 │
    ┌────────────▼───────────────────┐
    │ STEP 4: Get Full Schema        │
    │ MetadataService.               │
    │   get_column_schema()          │
    │                                │
    │ For selected tables:           │
    │  - Column names               │
    │  - Data types                 │
    │  - sample_values (JSON) ←NEW  │
    │                                │
    │ Returns: "Table: genre\n       │
    │ Columns: genre_id (int),       │
    │ name (varchar). Samples:       │
    │ [Rock, Jazz, Classical, ...]"  │
    └────────────┬───────────────────┘
                 │
    ┌────────────▼───────────────────┐
    │ STEP 5: LLM SQL Generation     │
    │ OllamaService.                 │
    │   generate_sql()               │
    │                                │
    │ Input:                         │
    │  - Original prompt            │
    │  - Schema (with samples!) ←NEW│
    │  - Sample data info            │
    │ LLM call (5-15 seconds)        │
    │ Output: "SELECT ... WHERE      │
    │ genre.name = 'Rock'"           │
    │                                │
    │ Key: LLM sees valid values     │
    │ from Column.sample_values!     │
    └────────────┬───────────────────┘
                 │
    ┌────────────▼───────────────────┐
    │ STEP 6: SQL Validation         │
    │ ChatService.                   │
    │   _verify_sql_identifiers()    │
    │                                │
    │ Check: Do all columns exist?   │
    │ Parse: Table aliases from SQL  │
    │ Validate: All refs valid?      │
    │                                │
    │ Status:                        │
    │ ✅ Valid → Continue           │
    │ ❌ Invalid → Return error      │
    └────────────┬───────────────────┘
                 │
    ┌────────────▼───────────────────┐
    │ STEP 7: Syntax Validation      │
    │ ChatService._validate_sql()    │
    │                                │
    │ Check: Basic SQL syntax        │
    │ Fix: Backtick → quote          │
    │                                │
    │ Status:                        │
    │ ✅ Valid → Continue           │
    │ ❌ Invalid → Return error      │
    └────────────┬───────────────────┘
                 │
    ┌────────────▼───────────────────┐
    │ STEP 8: Execute Query          │
    │ ChatService._execute_query()   │
    │                                │
    │ Execute SQL on user's DB       │
    │ Timeout: 30 seconds            │
    │ Return: rows, columns, status  │
    │                                │
    │ Status:                        │
    │ ✅ Success → Format + return  │
    │ ❌ Error → Attempt repair     │
    └────────────┬───────────────────┘
                 │
    ┌────────────▼───────────────────┐
    │ STEP 9 (if error): Repair      │
    │ Ask LLM to fix error           │
    │                                │
    │ Input:                         │
    │  - Original prompt            │
    │  - Failed SQL                  │
    │  - Error message               │
    │  - Schema (with samples)       │
    │                                │
    │ LLM generates fixed SQL        │
    │ Validate + Execute again       │
    │                                │
    │ Status:                        │
    │ ✅ Success → Format + return  │
    │ ❌ Still fails → Return error  │
    └────────────┬───────────────────┘
                 │
    ┌────────────▼───────────────────┐
    │ STEP 10: Format Answer         │
    │ ChatService._format_answer()   │
    │                                │
    │ Use LLM to explain results     │
    │ in natural language            │
    └────────────┬───────────────────┘
                 │
                 ▼
    ┌────────────────────────────────┐
    │ Return Response:               │
    │ {                              │
    │   "status": "success",         │
    │   "answer": "...",             │
    │   "sql": "SELECT ...",         │
    │   "rows": [...],               │
    │   "columns": [...],            │
    │   "execution_time_ms": 1234    │
    │ }                              │
    └────────────────────────────────┘

    TOTAL TIME: 12-60 seconds
    (Dominated by LLM inference)
```

---

## 3. Data Storage Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ PERSISTENT STORAGE (PostgreSQL)                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  connections table                                           │
│  ├─ id, name, host, port, username, password              │
│  │                                                          │
│  ├─ databases table (1-to-many)                            │
│  │  ├─ id, connection_id, name                             │
│  │  ├─ last_indexed_at ← When indexing completed           │
│  │  │                                                       │
│  │  └─ tables table (1-to-many)                            │
│  │     ├─ id, database_id, name                            │
│  │     ├─ context ← "Table: genre. Columns: ..."  ✅ NEW  │
│  │     ├─ is_indexed ← True if done                        │
│  │     │                                                    │
│  │     └─ columns table (1-to-many)                        │
│  │        ├─ id, table_id, name, data_type                 │
│  │        ├─ is_nullable                                   │
│  │        ├─ sample_values ← ["Rock", "Jazz", ...]  ✅ NEW│
│  │        │   (JSON, first 20 values)                      │
│  │        └─ (optional embeddings refs)                    │
│  │                                                          │
│  └─ samples table (optional)                               │
│     └─ Full row examples for advanced analytics            │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ CACHE STORAGE (Qdrant Vector Store)                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Collection: "context"                                       │
│                                                              │
│  Vector: {                                                   │
│    id: "conn_3_table_genre",                                │
│    vector: [0.12, 0.34, ..., 0.89],  (768 dims)            │
│    payload: {                                                │
│      type: "table",                                         │
│      connection_id: 3,                                       │
│      table_name: "genre",                                   │
│      description: "Table: genre..."                         │
│    }                                                         │
│  }                                                           │
│                                                              │
│  Vector: {                                                   │
│    id: "conn_3_col_genre_name",                             │
│    vector: [0.23, 0.45, ..., 0.78],  (768 dims)            │
│    payload: {                                                │
│      type: "column",                                        │
│      connection_id: 3,                                       │
│      table_name: "genre",                                   │
│      column_name: "name",                                   │
│      column_type: "varchar"                                 │
│    }                                                         │
│  }                                                           │
│                                                              │
│  Vector: {                                                   │
│    id: "conn_3_data_genre_name_12345",                      │
│    vector: [0.34, 0.56, ..., 0.89],  (768 dims)            │
│    payload: {                                                │
│      type: "data",  ← ✅ NEW in v2                         │
│      connection_id: 3,                                       │
│      table_name: "genre",                                   │
│      column_name: "name",                                   │
│      value: "Rock"                                          │
│    }                                                         │
│  }                                                           │
│                                                              │
│  ... (50+ data vectors per table)                           │
│                                                              │
└─────────────────────────────────────────────────────────────┘

KEY DIFFERENCES:
✅ PostgreSQL: Persistent across restarts, human-readable
❌ Qdrant: Ephemeral (cache), fast for similarity search
```

---

## 4. 3-Layer Retrieval Pipeline

```
                    USER QUERY
                       │
                       ▼
            ┌─────────────────────┐
            │ Layer 1: LLM Select │
            │ (HIGH CONFIDENCE)   │
            └─────────┬───────────┘
                      │
        ┌─────────────▼─────────────┐
        │ LLM analyzes summaries    │
        │ Returns table names       │
        │ Limit: 5 tables max       │
        └─────────────┬─────────────┘
                      │
        ┌─────────────▼──────────────┐
        │ Confidence Gate Check      │
        │ similarity >= 0.35?        │
        └─────┬────────────┬─────────┘
              │ YES        │ NO
              │            │
         ┌────▼────┐   ┌───▼────────────────┐
         │ Accept  │   │ Layer 2: Fallback  │
         │ → SQL   │   │ Vector Search      │
         │ Gen     │   │ (Filter: type=     │
         └─────────┘   │  "table" only)     │
                       └───┬────────────────┘
                           │
                    ┌──────▼──────┐
                    │ Got tables? │
                    └─┬────────┬──┘
                      │ YES    │ NO
                      │        │
              ┌───────▼─┐  ┌──▼─────────────┐
              │ SQL Gen │  │ Layer 3:       │
              │ & Exec  │  │ Fallback Mixed │
              │         │  │ (No filter)    │
              └─────────┘  └──┬─────────────┘
                              │
                       ┌──────▼──────┐
                       │ Combine all │
                       │ results     │
                       └──┬──────────┘
                          │
                    ┌─────▼──────┐
                    │ SQL Gen    │
                    │ & Exec     │
                    └─────┬──────┘
                          │
                    ┌─────▼──────┐
                    │ Return     │
                    │ Results    │
                    └────────────┘

CONFIDENCE GATE THRESHOLD: 0.35
  - Above 0.35: High confidence, use LLM selection
  - Below 0.35: Low confidence, fallback to vector
  
FALLBACK CHAIN:
  1. LLM selects from summaries (no hallucination possible)
  2. Vector search refinement (uses Qdrant similarity)
  3. Last resort: all results combined
  
NO QUERY FAILS (at minimum, some tables selected)
```

---

## 5. Data Usage During Query

```
USER QUERY: "Show me rock music albums"
                         │
        ┌────────────────┴────────────────┐
        │                                 │
        ▼                                 ▼
    LLM sees:                      Vector Search sees:
    ─────────────                  ──────────────────
    
    "Table: genre                  Similar embeddings:
     Columns: genre_id,            - genre.name vector
     name (varchar)                - genre_id vector
     
     Samples: [               +    - Value "Rock" vector
     'Rock',                        - Value "Jazz" vector
     'Jazz',                        - etc.
     'Classical',
     'Pop',
     'Blues',
     'Latin',
     'Metal',
     'Alternative'
     ]"
    
    LLM knows "Rock" is        Combined results:
    a valid genre value!       Most relevant tables
                               for query identified
    
    → SELECT WHERE             → Backup if LLM
      genre.name = 'Rock'        uncertain

RESULT: Accurate query generation with fallback
```

---

## 6. Re-Indexing Flow (For Existing Databases)

```
OLD DATABASE (v1 - Before Re-Index):
┌────────────────────────────────────┐
│ Tables:                            │
│ ├─ Table.context ✅ (has value)   │
│ ├─ Table.is_indexed ✅ (True)      │
│ │                                  │
│ └─ Columns:                        │
│    ├─ Column.data_type ✅ (String) │
│    ├─ Column.sample_values ❌(NULL)│
│                                    │
│ Qdrant:                            │
│ ├─ type="table" embeddings ✅     │
│ ├─ type="column" embeddings ✅    │
│ ├─ type="data" embeddings ❌(NONE) │
└────────────────────────────────────┘
                 │
    ┌────────────▼────────────┐
    │ API: POST /api/admin/   │
    │      reindex/3          │
    └────────────┬────────────┘
                 │
    ┌────────────▼────────────┐
    │ Background Task:        │
    │ Same as initial index   │
    │ (See Onboarding Flow)   │
    └────────────┬────────────┘
                 │
    ┌────────────▼──────────────────────┐
    │ NEW: Data-Variation Sampling      │
    │ Now that we have DB credentials   │
    │ (stored in Connection record)     │
    └────────────┬──────────────────────┘
                 │
    ┌────────────▼──────────────────────┐
    │ NEW: Embed Data Values            │
    │ Add type="data" to Qdrant         │
    └────────────┬──────────────────────┘
                 │
NEW DATABASE (After Re-Index):
┌────────────────────────────────────┐
│ Tables:                            │
│ ├─ Table.context ✅ (regenerated) │
│ ├─ Table.is_indexed ✅ (True)      │
│ │                                  │
│ └─ Columns:                        │
│    ├─ Column.data_type ✅ (String) │
│    ├─ Column.sample_values ✅(JSON)│ ← NEWLY POPULATED
│                                    │
│ Qdrant:                            │
│ ├─ type="table" embeddings ✅     │
│ ├─ type="column" embeddings ✅    │
│ ├─ type="data" embeddings ✅(NEW) │ ← NEWLY ADDED
└────────────────────────────────────┘

Time: 30-60 seconds
Result: Database now has full v2 metadata
```

---

## 7. Confidence Gate Mechanism

```
            LLM Table Selection
                    │
                    ▼
        ┌──────────────────────┐
        │ Selected tables:     │
        │ ["genre", "album"]   │
        └──────────┬───────────┘
                   │
                   ▼
        ┌──────────────────────┐
        │ Get summaries for    │
        │ selected tables      │
        │                      │
        │ Summary text:        │
        │ "Table: genre...     │
        │  Table: album..."    │
        └──────────┬───────────┘
                   │
                   ▼
        ┌──────────────────────┐
        │ Compute similarity:  │
        │ cosine(              │
        │  prompt_embedding,   │
        │  summary_embedding   │
        │ )                    │
        └──────────┬───────────┘
                   │
                   ▼
        ┌──────────────────────────────────┐
        │ Score: 0.75                      │
        │                                  │
        │ Gate Check: 0.75 >= 0.35? ✅     │
        └──────────┬───────────────────────┘
                   │
       ┌───────────┴───────────┐
       │ YES                   │ NO
       │ (≥ 0.35)              │ (< 0.35)
       │                       │
       ▼                       ▼
    Use LLM         Vector Search Fallback
    selection       (Layer 2)
    (Confident)     (Uncertain, need help)

THRESHOLD: 0.35 (tight, catches weak matches)
EXAMPLES:
  0.85 → Very confident ✅ Use LLM
  0.60 → Confident ✅ Use LLM
  0.35 → Borderline ✅ Use LLM (barely)
  0.30 → Uncertain ❌ Vector fallback
  0.10 → Very uncertain ❌ Vector fallback
```

---

**These diagrams show the complete v2 architecture flow from registration through query execution.**
