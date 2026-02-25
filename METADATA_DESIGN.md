# DbChat v2: Metadata & Data-Variation Design

## Overview

This document defines the required data structures and onboarding process for the v2 architecture, enabling robust multi-table query generation without database-specific hardcoding.

---

## Part 1: Required Data Structures

### 1.1 Table Summaries

**Purpose**: Natural language descriptions of each table for LLM table selection.

**Stored in**: `Table.context` (Text field in database)

**Format**:
```
Table: {table_name}
Purpose: {human-readable description}
Columns: {column1} ({type}), {column2} ({type}), ...
Sample data patterns: {categorical patterns}, {numeric ranges}
Common filters: {typical WHERE clauses}
```

**Example** (Chinook database):
```
Table: invoice
Purpose: Records of customer purchases and payments
Columns: invoice_id (int), customer_id (int), invoice_date (date), total (decimal)
Sample data patterns: dates from 2009-2013, totals range 0.99-307.55, status IN (Open, Paid, Uncollectible)
Common filters: WHERE invoice_date >= '2020-01-01', WHERE customer_id = X, WHERE total > 100
```

**Generation**: 
- Initial: Auto-generated from column names and types
- Optimized: Created during onboarding by analyzing actual data distribution

---

### 1.2 Data-Variation Samples

**Purpose**: Provide concrete examples of categorical values and data patterns for filter generation.

**Stored in**: 
- `Column.sample_values` (JSON string of up to 20 distinct values)
- `Sample` table (detailed sample embeddings for vector search)

**Format** (Column.sample_values):
```json
["Rock", "Jazz", "Classical", "Pop", "Blues", "Latin", "Metal", "Alternative"]
```

**Storage per column**:
| Column Type | Storage | Purpose |
|------------|---------|---------|
| VARCHAR, TEXT | Distinct values (LIMIT 50) | Value suggestions for filters |
| ENUM, CHAR | All possible values | Complete domain knowledge |
| NUMERIC, DATE | Min, Max, Count | Range understanding |
| FK references | Sample IDs + referenced values | Join hint |

**Example** (Chinook):

**genre table**:
- sample_values: `["Rock", "Jazz", "Classical", "Pop", "Blues", "Latin", "Metal", "Alternative", "Reggae", "Hip-Hop"]`

**customer table** (country column):
- sample_values: `["USA", "Canada", "France", "Germany", "UK", "Brazil", "Spain", "India", "Sweden", "Italy"]`

**invoice table** (total column):
- sample_values: Min: 0.99, Max: 307.55, distribution: mostly under $50

---

### 1.3 Schema Context

**Purpose**: Complete column-level information for SQL validation and generation.

**Stored in**: Dynamically built from Table + Column records

**Format**:
```
Table: {table_name}
Columns: col1 (int, NOT NULL), col2 (varchar(100), nullable), col3 (date, nullable)

[repeat for each selected table]
```

**Includes**:
- Column names and exact data types
- Nullable constraints
- Foreign key relationships (discovered during schema extraction)

---

## Part 2: Onboarding Flow

### Phase 0: Database Registration

**Endpoint**: `POST /api/admin/register-db`

**Input**:
```json
{
  "name": "my-chinook",
  "host": "db.example.com",
  "port": 5432,
  "username": "user",
  "password": "pass",
  "database": "chinook",
  "database_type": "postgres"
}
```

**Output**: `RegisterDBResponse`
```json
{
  "id": 3,
  "name": "my-chinook",
  "status": "registered",
  "indexing_scheduled": true
}
```

---

### Phase 1: Schema Extraction

**Triggered by**: Background task in admin endpoint

**Process**: 
1. Connect to user's database
2. Enumerate all tables and columns
3. Extract data types, constraints, FK relationships
4. Return schema as structured JSON

**Code**: `SchemaExtractor.extract_schema()`

**Output structure**:
```json
{
  "database": "chinook",
  "tables": [
    {
      "name": "artist",
      "columns": [
        {"name": "artist_id", "type": "int", "nullable": false},
        {"name": "name", "type": "varchar(120)", "nullable": true}
      ]
    },
    ...
  ]
}
```

**Time**: ~1-5 seconds for typical databases

---

### Phase 2: Table Summary Generation

**Triggered by**: IndexingService.index_schema()

**Process**:
1. For each table:
   - Analyze column types, names, count
   - Sample 50 rows (or full table if < 100 rows)
   - Detect categorical vs numeric columns
   - Generate human-readable summary

**Code**: `IndexingService._build_table_summary()`

**Output**: `Table.context` field populated
```
Table: genre
Purpose: Music categories and classifications
Columns: genre_id (int), name (varchar)
Sample genres: Rock, Jazz, Classical, Pop, Blues, Latin, Metal, Alternative
```

**Time**: ~1-2 seconds per table (disk access)

---

### Phase 3: Data-Variation Sampling

**Triggered by**: IndexingService.index_schema() (optional, requires DB connection)

**Process**:
1. For each categorical column (VARCHAR, TEXT, ENUM, CHAR):
   - Execute: `SELECT DISTINCT column_name FROM table LIMIT 50`
   - Store up to 20 values in `Column.sample_values`
   - Embed each value using Ollama nomic-embed-text
   - Upsert embeddings to Qdrant with metadata: `type="data"`

2. For numeric/date columns (optional):
   - Store min/max/count statistics
   - Sample percentile values (P10, P25, P50, P75, P90)

**Code**: `IndexingService._sample_data_variations()`

**Database-specific handling**:
```python
{
  "postgres": lambda col: f'SELECT DISTINCT "{col}" FROM "{table}" LIMIT 50',
  "mysql": lambda col: f'SELECT DISTINCT `{col}` FROM `{table}` LIMIT 50',
  "sqlserver": lambda col: f'SELECT DISTINCT [{col}] FROM [{table}]'
}
```

**Output**:
- `Column.sample_values = '["Rock", "Jazz", "Classical", ...]'`
- Qdrant embeddings with `type="data"` for vector fallback

**Time**: ~2-5 seconds per database (DB queries)

---

### Phase 4: Schema Embedding & Vector Indexing

**Triggered by**: IndexingService.index_schema()

**Process**:
1. Embed table summaries using Ollama nomic-embed-text
   - Store embedding ID in `Table.embedding_id`
   - Upsert to Qdrant with metadata: `type="table"`

2. Embed column contexts (name + data type + sample values)
   - Store embedding ID in `Column.embedding_id`
   - Upsert to Qdrant with metadata: `type="column"`

3. Index vector store with metadata for filtering:
   ```json
   {
     "id": "col_123",
     "vector": [0.1, 0.2, ...],
     "metadata": {
       "type": "column",
       "table": "genre",
       "column": "name",
       "data_type": "varchar",
       "connection_id": 3
     }
   }
   ```

**Code**: `OllamaService.embed_text()`, `VectorService.upsert()`

**Time**: ~1-3 seconds per database (embedding computation)

---

### Phase 5: Indexing Complete

**Triggered by**: End of Phase 4

**Status update**:
- `Database.last_indexed_at = now()`
- `Table.is_indexed = True` for each table
- `Table.last_indexed_at = now()`

**Verification**: 
- All tables have `context` populated
- All categorical columns have `sample_values`
- Qdrant has embeddings for all tables/columns

---

## Part 3: Data Access During Query

### Query Processing Pipeline

#### 1. LLM Table Selection
```python
# Get table summaries
table_summaries = metadata.get_table_summaries(connection_id)
# Output: [{"name": "genre", "summary": "Music categories..."}, ...]

# LLM selects relevant tables
identified = await ollama.identify_tables(user_prompt, table_summaries)
# Output: ["genre", "track"]
```

#### 2. Intent Verification
```python
# Verify LLM selection confidence
selected_summaries = "\n".join([s["summary"] for s in table_summaries if s["name"] in identified])
similarity = await ollama.verify_intent_similarity(prompt_embedding, selected_summaries)
# Output: 0.75 (gate: >= 0.35)
```

#### 3. Schema Retrieval
```python
# Get full column details for SQL generation
schema_context = metadata.get_column_schema(connection_id, identified)
# Output: "Table: genre\nColumns: genre_id (int), name (varchar)..."
```

#### 4. Vector Search Fallback
```python
# If LLM confidence too low, search vectors
if similarity < 0.35:
    relevant = await vector.search(embedding, filters={"type": "table"})
    # Returns top K table embeddings
```

#### 5. Data-Variation for Filter Hints
```python
# Optional: Get sample values for WHERE clause generation
for table_name in selected_tables:
    columns = metadata.get_column_samples(table_name)
    # Output: {"genre_name": ["Rock", "Jazz", ...], "year": [1995, 2001, ...]}
```

---

## Part 4: Database Schema Support

### Supported Types

| Category | Types |
|----------|-------|
| Integer | INT, BIGINT, SMALLINT, TINYINT |
| Float | FLOAT, DOUBLE, DECIMAL, NUMERIC |
| String | VARCHAR, CHAR, TEXT, NVARCHAR |
| Date/Time | DATE, TIME, TIMESTAMP, DATETIME |
| Boolean | BOOLEAN, BIT |
| Special | UUID, JSON, ENUM |

### Categorical Detection

Column is treated as **categorical** if:
- Type is VARCHAR, CHAR, TEXT, ENUM, or UUID
- Column name suggests category: *status*, *type*, *category*, *name*, *code*
- Distinct value count < column type max length / 10 (heuristic)

Example: A VARCHAR(50) column with 5 distinct values → categorical

---

## Part 5: Storage Requirements

### Database Space

| Component | Size | Notes |
|-----------|------|-------|
| Connection record | 1 KB | Host, port, credentials |
| Database metadata | 10 KB | Name, hashes, timestamps |
| Table metadata | 5 KB/table | Name, context (500 chars), timestamps |
| Column metadata | 2 KB/column | Name, type, nullable, sample_values |
| Sample data | 1 KB/table | JSON of 50 distinct values |

**Example (Chinook: 11 tables, ~90 columns)**:
- Total: ~0.5 MB for complete metadata

### Vector Store Space (Qdrant)

| Component | Vectors | Size | Notes |
|-----------|---------|------|-------|
| Table embeddings | 11 | 1.5 MB | 1 per table |
| Column embeddings | 90 | 12 MB | 1 per column |
| Data-value embeddings | ~500 | 70 MB | 50 values × 10 tables |

**Example (Chinook)**:
- Total: ~85 MB in Qdrant

---

## Part 6: Performance Metrics

### Onboarding Time (First Indexing)

| Phase | Time | Database Size |
|-------|------|----------------|
| Schema Extraction | 1-5s | ~100 tables |
| Summary Generation | 2-5s | Per table |
| Data Sampling | 2-5s | Per connection |
| Embedding (LLM) | 5-15s | Per table+column |
| Vector Indexing | 1-2s | All embeddings |
| **Total** | **15-45s** | **Typical DB** |

### Query Time (After Indexing)

| Component | Time |
|-----------|------|
| Fetch table summaries | 50ms |
| LLM table selection | 5-10s |
| Intent verification | 1-2s |
| Schema retrieval | 100ms |
| SQL generation | 5-15s |
| SQL validation | 500ms |
| Query execution | 500ms-30s |
| **Total** | **12-60s** |

---

## Part 7: Error Handling

### Missing Table Summary
- **Fallback**: Auto-generate from column schema
- **Code**: `MetadataService._build_fallback_summary()`
- **Result**: Still functional, lower quality for LLM table selection

### Missing Data-Variation Samples
- **Fallback**: Proceed without categorical hints
- **Impact**: SQL generator may suggest non-existent values
- **Mitigation**: Schema verification catches invalid columns

### Indexing Failure
- **Status**: Connection marked with `last_indexed_at = NULL`
- **Fallback**: Vector search degraded, LLM only
- **User action**: Manually retry via `/api/admin/re-index/{connection_id}` (to be added)

---

## Part 8: Future Extensions

### Planned Features

1. **Incremental Indexing**
   - Detect schema changes
   - Re-index only modified tables
   - Track column statistics over time

2. **Smart Sampling**
   - Weight categorical samples by frequency
   - Store metadata: `value_frequency` for each sample
   - Suggest most common filters first

3. **Relationship Mapping**
   - Auto-detect FK relationships during schema extraction
   - Store join paths: `invoice.customer_id → customer.id`
   - Hint LLM with likely JOIN patterns

4. **Performance Optimization**
   - Cache table summaries in memory
   - Lazy-load column samples (on-demand)
   - Batch vector operations

5. **Multi-Database Support**
   - Support cross-database joins
   - Metadata for federated queries
   - Connection aliasing

---

## Part 9: Configuration

### Environment Variables

```bash
# Vector store
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Ollama embeddings
OLLAMA_HOST=http://localhost:11434
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIM=768

# Indexing behavior
MAX_SAMPLES_PER_COLUMN=50
MAX_TABLE_SUMMARIES=20
CATEGORICAL_DETECTION_THRESHOLD=0.1
```

### Admin Configuration

```python
# app/config.py
INDEXING_TIMEOUT = 120  # seconds
SCHEMA_EXTRACTION_TIMEOUT = 30  # seconds
EMBEDDING_BATCH_SIZE = 10
VECTOR_BATCH_SIZE = 50
```

---

## Conclusion

The v2 architecture uses structured metadata (table summaries + data-variation samples) to enable robust multi-table query generation without database-specific hardcoding. The onboarding flow automates collection of this metadata during database registration, with clear fallback behavior if data is incomplete.

**Key invariants**:
- Every table has a summary (auto-generated if needed)
- Categorical columns have sample values (optional but recommended)
- Schema context is always available for SQL validation
- Vector store enables graceful fallback if LLM fails

**Result**: Database-agnostic design that scales to any SQL database.
