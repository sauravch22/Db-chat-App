# Data-Variation Samples: Storage & Onboarding Flow

## Quick Answer

**Q: Are data-variation samples stored anywhere?**
**A: YES - They are stored in TWO places:**

1. **PostgreSQL Database** - `Column.sample_values` field (JSON text)
2. **Qdrant Vector Store** - Individual value embeddings with metadata

---

## Storage Locations

### 1. Database Storage (PostgreSQL)

**Table**: `columns`
**Field**: `sample_values` (Text, JSON format)

**Example**:
```sql
SELECT name, data_type, sample_values 
FROM columns 
WHERE table_id = 5 AND name = 'genre_name';

-- Output:
-- name       | data_type | sample_values
-- genre_name | varchar   | ["Rock", "Jazz", "Classical", "Pop", "Blues", "Latin", "Metal", "Alternative"]
```

**Why store here?**
- Fast lookup during query processing
- No vector search needed for categorical hints
- Human-readable format for debugging

---

### 2. Vector Store Storage (Qdrant)

**Collection**: `context` (default Qdrant collection)
**Metadata type**: `type="data"`

**Example entry**:
```json
{
  "id": "conn_3_data_genre_genre_name_12345",
  "vector": [0.12, 0.34, ..., 0.89],  // 768 dimensions
  "payload": {
    "type": "data",
    "connection_id": 3,
    "database": "chinook",
    "table_name": "genre",
    "column_name": "genre_name",
    "value": "Rock",
    "description": "Value: Rock. Column: genre_name. Table: genre."
  }
}
```

**Why store here?**
- Enables vector similarity search for data patterns
- Fallback when LLM suggestions are weak
- Support for semantic filter generation

---

## Onboarding Flow (Complete)

### New Databases (Recommended)

```
1. Register Database (API call)
   POST /api/admin/register-db
   ↓
2. Schema Extraction (Background)
   - Query database for tables/columns
   - Extract data types, constraints
   ↓
3. Table Summary Generation
   - Auto-generate from column names + types
   - Persist to Table.context
   ↓
4. Data-Variation Sampling ← KEY STEP
   - For each categorical column:
     a) Execute: SELECT DISTINCT col FROM table LIMIT 50
     b) Store up to 20 values in Column.sample_values (JSON)
     c) Embed each value using Ollama
     d) Upsert to Qdrant with type="data"
   ↓
5. Embedding & Indexing
   - Embed table summaries → Qdrant (type="table")
   - Embed column info → Qdrant (type="column")
   ↓
6. Mark as Indexed
   - Database.last_indexed_at = now()
   - Table.is_indexed = True for each
```

**Time**: 30-60 seconds total
**Result**: Full metadata ready for queries

---

### Existing Databases (Need Re-Index)

If you upgraded to v2 and a database was already registered with v1:

```
Database exists with:
  ✅ Schema extracted
  ✅ Table summaries (Table.context)
  ❌ Data-variation samples (Column.sample_values is NULL)
  ❌ Data embeddings in Qdrant (missing type="data")

Solution: Re-Index
  POST /api/admin/reindex/3  (where 3 is connection_id)
  
This will:
  ✅ Re-extract schema (fast, from cache)
  ✅ Regenerate summaries
  ✅ NEW: Sample categorical values
  ✅ NEW: Embed value variations
  ✅ Update Vector store
```

**Time**: Same as new database (30-60 seconds)
**Result**: Column.sample_values populated, Qdrant updated with type="data"

---

## Data-Variation Sampling: Technical Details

### What Gets Sampled?

**Categorical Columns** (VARCHAR, CHAR, TEXT, ENUM, UUID):
```sql
SELECT DISTINCT column_name FROM table_name LIMIT 50
```
- Returns up to 50 distinct values
- Stored: First 20 in Column.sample_values
- Embedded: All 50 in Qdrant (separately)

**Example (Chinook)**:
```
Table: genre
  Column: name (varchar)
    Sample values: ["Rock", "Jazz", "Classical", "Pop", "Blues", 
                    "Latin", "Metal", "Alternative", "Reggae", "Hip-Hop"]
    Embedding count: 10 vectors in Qdrant (one per value)

Table: customer  
  Column: country (varchar)
    Sample values: ["USA", "Canada", "France", "Germany", "UK", 
                    "Brazil", "Spain", "India", "Sweden", "Italy"]
    Embedding count: 10 vectors in Qdrant
```

**Numeric/Date Columns** (Not sampled, but stats could be added):
- MIN, MAX, COUNT stored as column metadata
- Optional: P10, P25, P50, P75, P90 percentiles

---

## Code References

### IndexingService Data Sampling
**File**: `app/services/indexing_service.py`

**Lines 25-57**: Helper methods
```python
def _quote_ident(name, db_type)          # DB-specific quoting
def _is_categorical_type(col_type)       # Detect VARCHAR, TEXT, etc.
def _sample_data_variations(engine, table_name, columns, db_type)
  # Execute SELECT DISTINCT for each categorical column
  # Return {col_name: [value1, value2, ...]}
```

**Lines 245-280**: Sampling & Embedding Loop
```python
if data_engine is not None:
  sampled_values = self._sample_data_variations(...)
  
  for col_name, values in sampled_values.items():
    # 1. Persist to Database
    col_record.sample_values = json.dumps(values[:20])
    
    # 2. Embed each value
    for value in values:
      value_embedding = await self.ollama.embed_text(...)
      
      # 3. Store in Qdrant
      await self.vector.upsert_vector(
        vector_id=f"conn_{connection_id}_data_{table_name}_{col_name}_{hash(value)}",
        embedding=value_embedding,
        metadata={
          "type": "data",
          "table_name": table_name,
          "column_name": col_name,
          "value": str(value)
        }
      )
```

### MetadataService Retrieval
**File**: `app/services/metadata_service.py`

```python
def get_table_summaries(connection_id):
  # Returns: [{"name": "genre", "summary": "..."}, ...]
  # Source: Table.context from database

def get_column_schema(connection_id, table_names):
  # Includes column.sample_values in schema context
  # Format: "Column: genre_name (varchar). Samples: Rock, Jazz, ..."
```

### During Query Processing
**File**: `app/services/chat_service.py`

```python
# Fetch summaries for LLM table selection
table_summaries = await self.metadata.get_table_summaries(connection_id)

# Later: Get full schema for SQL generation
schema_context = await self.metadata.get_column_schema(connection_id, table_names)
# Schema includes: column names, types, AND sample_values

# Schema passed to LLM:
# "Table: genre\nColumns: genre_id (int), name (varchar). Samples: Rock, Jazz..."
```

---

## Verification Checklist

### After Onboarding (New Database)

- [ ] Check PostgreSQL:
  ```sql
  SELECT COUNT(*) FROM tables WHERE database_id = 3;
  SELECT COUNT(*) FROM columns WHERE table_id = 5;
  SELECT sample_values FROM columns WHERE name = 'genre_name' LIMIT 1;
  ```
  
- [ ] Check Qdrant:
  ```bash
  curl -X GET http://localhost:6333/collections/context/points \
    -d '{"filter": {"type": {"value": "data"}}}' | jq '.result | length'
  ```
  Expected: ~500+ (50 values × 10+ tables)

- [ ] Check Database metadata:
  ```sql
  SELECT last_indexed_at FROM databases WHERE id = 3;
  -- Should be recent timestamp, not NULL
  ```

### After Re-Index (Existing Database)

Same as above - all Column.sample_values should now be populated.

---

## Performance Impact

### Onboarding Time Breakdown
| Phase | Time | Details |
|-------|------|---------|
| Schema extraction | 1-5s | Database query |
| Summary generation | 1-2s | Column analysis |
| Data sampling | 5-10s | SELECT DISTINCT × 50+ columns |
| Embeddings (Ollama) | 10-20s | 100+ embeddings @ 100-200ms each |
| Vector indexing | 2-5s | Qdrant upserts |
| **Total** | **25-45s** | Typical database |

### Query Time Impact
- **Added benefit**: More accurate filter suggestions
- **Added cost**: None (data already embedded, just faster lookup)
- **Vector search**: ~100-200ms vs LLM 5-10s

---

## Storage Space

### Database (PostgreSQL)
```
Column.sample_values: ~200 bytes per categorical column
  Example: 10 columns × 200 bytes = 2 KB per table
  Total (11-table DB): ~20 KB
```

### Vector Store (Qdrant)
```
Data embeddings: 768 dimensions × 8 bytes = 6.1 KB per vector
  Example: 50 values × 10 tables = 500 vectors
  Total: 500 × 6.1 KB + metadata = ~5-8 MB
```

---

## FAQ

**Q: Do I lose data-variation samples if I restart the system?**
- PostgreSQL (Column.sample_values): ✅ Persistent
- Qdrant (vector embeddings): ❌ Ephemeral (unless persistence enabled)
- Solution: Qdrant has snapshots, or rebuild on startup (fast, <1 minute)

**Q: Can I manually update samples?**
```sql
UPDATE columns 
SET sample_values = '["value1", "value2", ...]'
WHERE id = 123;
```
Yes, but won't update Qdrant vectors. Better to re-index.

**Q: What if data has many distinct values (>50)?**
- First 50 are sampled uniformly
- Top by frequency (TBD future feature)
- All 50 embedded and indexed

**Q: Can I disable data sampling?**
Yes, just don't provide DB connection info to `index_schema()`:
```python
# Sampling disabled:
await indexing_service.index_schema(
  connection_id=3,
  database_name="chinook",
  schema_data=schema_data
  # No: db_type, host, port, etc.
)
```
Tables + columns still indexed, just no data samples.

---

## Summary

| Component | Storage | Persistence | Purpose |
|-----------|---------|-------------|---------|
| Table summary | Table.context | ✅ Database | LLM table selection |
| Column metadata | Column columns | ✅ Database | SQL generation |
| Data samples | Column.sample_values | ✅ Database | Quick lookup, human-readable |
| Table vectors | Qdrant (type="table") | ❌ Ephemeral | Fallback table search |
| Column vectors | Qdrant (type="column") | ❌ Ephemeral | Fallback column search |
| Data vectors | Qdrant (type="data") | ❌ Ephemeral | Fallback filter suggestions |

**Re-indexing needed after v2 upgrade**: YES
- Existing databases have schema + summaries
- But missing Column.sample_values and data embeddings
- Call: `POST /api/admin/reindex/{connection_id}`
