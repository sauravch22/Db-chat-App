# DbChat System Flow Documentation

## Table of Contents
1. [System Architecture](#system-architecture)
2. [Database Onboarding Flow](#database-onboarding-flow)
3. [Query Processing Flow](#query-processing-flow)
4. [Component Interactions](#component-interactions)
5. [Data Models](#data-models)

---

## System Architecture

```
┌─────────────┐
│   Client    │
│  (Postman/  │
│   Frontend) │
└──────┬──────┘
       │ HTTP/JSON
       ▼
┌─────────────────────────────────────────┐
│         FastAPI Application             │
│  ┌───────────────────────────────────┐  │
│  │   API Routes                      │  │
│  │  - /health                        │  │
│  │  - /api/admin/connections         │  │
│  │  - /api/admin/index/:id           │  │
│  │  - /api/chat                      │  │
│  └───────────┬───────────────────────┘  │
│              │                           │
│  ┌───────────┴───────────────────────┐  │
│  │   Services Layer                  │  │
│  │  - ChatService                    │  │
│  │  - SchemaService                  │  │
│  │  - IndexingService                │  │
│  │  - OllamaService                  │  │
│  │  - VectorService                  │  │
│  └───────────┬───────────────────────┘  │
└──────────────┼───────────────────────────┘
               │
     ┌─────────┼─────────┐
     ▼         ▼         ▼
┌─────────┐ ┌──────┐ ┌─────────┐
│PostgreSQL│ │Ollama│ │ Qdrant  │
│Metadata │ │ LLM  │ │ Vector  │
│   DB    │ │      │ │   DB    │
└─────────┘ └──────┘ └─────────┘
     │
     ▼
┌─────────────┐
│   User's    │
│  External   │
│  Database   │
└─────────────┘
```

---

## Database Onboarding Flow

### Overview
The onboarding process registers an external database, extracts its schema, generates embeddings, and stores metadata for future queries.

### Step-by-Step Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                    ONBOARDING FLOW                               │
└──────────────────────────────────────────────────────────────────┘

1. REGISTER CONNECTION
   ↓
   POST /api/admin/connections
   {
     "name": "Production DB",
     "host": "db.example.com",
     "port": 5432,
     "database": "mydb",
     "username": "user",
     "password": "pass"
   }
   ↓
   [Test Connection]
   ↓
   [Save to metadata DB]
   ↓
   Returns connection_id: 3

2. TRIGGER INDEXING
   ↓
   POST /api/admin/index/3
   ↓
   ┌─────────────────────────────────────┐
   │  SchemaService.extract_schema()     │
   │                                     │
   │  1. Connect to external DB          │
   │  2. Query information_schema:       │
   │     - tables                        │
   │     - columns                       │
   │     - data_types                    │
   │     - constraints                   │
   │                                     │
   │  Returns: List[TableSchema]         │
   └─────────────┬───────────────────────┘
                 ▼
   ┌─────────────────────────────────────┐
   │  IndexingService.index_database()   │
   │                                     │
   │  For each table/column:             │
   │                                     │
   │  3. Generate embedding text:        │
   │     "Table: artist                  │
   │      Columns: ArtistId (integer),   │
   │      Name (varchar)"                │
   │                                     │
   │  4. Call OllamaService.embed_text() │
   │     → Get 768-dim vector            │
   │                                     │
   │  5. Store in Qdrant:                │
   │     - vector: [0.123, -0.456, ...]  │
   │     - payload: {                    │
   │         connection_id: 3,           │
   │         table_name: "artist",       │
   │         columns: [...],             │
   │         embedding_text: "..."       │
   │       }                             │
   │                                     │
   │  6. Persist metadata to PostgreSQL: │
   │     - Database record               │
   │     - Table records                 │
   │     - Column records                │
   │                                     │
   └─────────────────────────────────────┘
                 ▼
   ✅ Indexing Complete
   - 11 tables indexed
   - 127 columns extracted
   - 138 embeddings stored
   - Metadata persisted
```

### Detailed Steps

#### 1. Connection Registration
- **Input**: Database credentials
- **Process**:
  - Validate connection parameters
  - Test connection with timeout (10s)
  - Store encrypted credentials (TODO: encryption)
  - Return connection_id
- **Output**: Connection object with ID

#### 2. Schema Extraction
**File**: `app/services/schema_service.py`

```python
def extract_schema(connection: Connection) -> List[TableSchema]:
    # Build connection URL with SSL
    db_url = f"postgresql://{user}:{pass}@{host}:{port}/{db}?sslmode=require"
    
    # Query information_schema
    tables_query = """
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema='public'
    """
    
    for table in tables:
        columns_query = """
            SELECT column_name, data_type, is_nullable, 
                   column_default, character_maximum_length
            FROM information_schema.columns
            WHERE table_name = :table_name
            ORDER BY ordinal_position
        """
        # Extract columns for each table
    
    return List[TableSchema]
```

**Key Points**:
- Uses `information_schema` for portability
- SSL mode required for remote connections
- Extracts: tables, columns, types, nullability, defaults

#### 3. Embedding Generation
**File**: `app/services/indexing_service.py`

```python
def index_database(connection_id: int):
    schema = schema_service.extract_schema(connection)
    
    for table in schema.tables:
        # Build embedding text
        text = f"Table: {table.name}\n"
        text += f"Columns: {', '.join([f'{c.name} ({c.type})' for c in table.columns])}"
        
        # Generate embedding via Ollama
        embedding = ollama_service.embed_text(text)  # Returns 768-dim vector
        
        # Store in Qdrant
        vector_service.upsert(
            collection="dbchat_embeddings",
            points=[{
                "id": uuid.uuid4(),
                "vector": embedding,
                "payload": {
                    "connection_id": connection_id,
                    "table_name": table.name,
                    "columns": [c.name for c in table.columns],
                    "embedding_text": text
                }
            }]
        )
        
        # Persist metadata to PostgreSQL
        db_record = Database(connection_id=connection_id, name=db_name)
        table_record = Table(database_id=db_record.id, name=table.name)
        for col in table.columns:
            Column(table_id=table_record.id, name=col.name, data_type=col.type)
```

**Key Points**:
- Each table → one embedding
- Embedding includes table name + column descriptions
- Qdrant stores vector + metadata payload
- PostgreSQL stores structured metadata for relationships

#### 4. Vector Storage (Qdrant)
**Collection**: `dbchat_embeddings`
**Dimensions**: 768 (nomic-embed-text model)

```json
{
  "id": "uuid-here",
  "vector": [0.123, -0.456, 0.789, ...],  // 768 dimensions
  "payload": {
    "connection_id": 3,
    "database_name": "chinook",
    "table_name": "artist",
    "columns": ["ArtistId", "Name"],
    "embedding_text": "Table: artist\nColumns: ArtistId (integer), Name (varchar)"
  }
}
```

#### 5. Metadata Storage (PostgreSQL)
**Tables**: `connections`, `databases`, `tables`, `columns`

```sql
-- Hierarchy
connections (id, name, host, port, database, username, password)
    └── databases (id, connection_id, name)
            └── tables (id, database_id, name)
                    └── columns (id, table_id, name, data_type, is_nullable)
```

---

## Query Processing Flow

### Overview
Two types of queries are supported:
1. **Catalog Queries**: Introspection (schema, indexes, connections)
2. **Data Queries**: Natural language → SQL → Results

### Flow Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                    QUERY PROCESSING FLOW                         │
└──────────────────────────────────────────────────────────────────┘

POST /api/chat
{
  "connection_id": 3,
  "prompt": "How many artists are in the database?"
}
   ↓
┌────────────────────────────────────────┐
│  ChatService.process_query()           │
│                                        │
│  Step 1: INTENT CLASSIFICATION         │
│  ┌──────────────────────────────────┐  │
│  │ OllamaService.classify_intent()  │  │
│  │                                  │  │
│  │ Prompt to LLM:                   │  │
│  │ "Classify this query:            │  │
│  │  'How many artists...'           │  │
│  │                                  │  │
│  │ Answer: catalog or data"         │  │
│  │                                  │  │
│  │ Result: "data"                   │  │
│  └──────────────────────────────────┘  │
│                 │                       │
│                 ▼                       │
│  ┌────────────────────────┐             │
│  │  Is intent="catalog"?  │             │
│  └───┬──────────────┬─────┘             │
│      │ YES          │ NO                │
│      ▼              ▼                   │
│  [CATALOG PATH]  [DATA PATH]            │
└──────┬──────────────┬───────────────────┘
       │              │
       │              └──────────────────────────┐
       │                                         ▼
       │                          ┌──────────────────────────────┐
       │                          │  Step 2: EMBED PROMPT        │
       │                          │                              │
       │                          │  embedding = ollama.embed(   │
       │                          │    "How many artists..."     │
       │                          │  )                           │
       │                          │  → [0.234, -0.567, ...]      │
       │                          └──────────────┬───────────────┘
       │                                         ▼
       │                          ┌──────────────────────────────┐
       │                          │  Step 3: VECTOR SEARCH       │
       │                          │                              │
       │                          │  results = qdrant.search(    │
       │                          │    collection: "embeddings", │
       │                          │    vector: embedding,        │
       │                          │    filter: {                 │
       │                          │      connection_id: 3        │
       │                          │    },                        │
       │                          │    limit: 5                  │
       │                          │  )                           │
       │                          │                              │
       │                          │  Top matches:                │
       │                          │  1. artist (score: 0.89)     │
       │                          │  2. album (score: 0.72)      │
       │                          │  3. track (score: 0.65)      │
       │                          └──────────────┬───────────────┘
       │                                         ▼
       │                          ┌──────────────────────────────┐
       │                          │  Step 4: BUILD CONTEXT       │
       │                          │                              │
       │                          │  For each matched table:     │
       │                          │  - Query metadata DB         │
       │                          │  - Get column details        │
       │                          │                              │
       │                          │  Context:                    │
       │                          │  "Table: artist              │
       │                          │   Columns: ArtistId (int),   │
       │                          │            Name (varchar)"   │
       │                          └──────────────┬───────────────┘
       │                                         ▼
       │                          ┌──────────────────────────────┐
       │                          │  Step 5: GENERATE SQL        │
       │                          │                              │
       │                          │  sql = ollama.generate_sql(  │
       │                          │    prompt: "How many...",    │
       │                          │    schema_context: context   │
       │                          │  )                           │
       │                          │                              │
       │                          │  Generated:                  │
       │                          │  "SELECT COUNT(*) FROM       │
       │                          │   artist;"                   │
       │                          └──────────────┬───────────────┘
       │                                         ▼
       │                          ┌──────────────────────────────┐
       │                          │  Step 6: VALIDATE SQL        │
       │                          │                              │
       │                          │  - Must start with SELECT    │
       │                          │  - No DELETE/DROP/UPDATE     │
       │                          │  - No ALTER/TRUNCATE/CREATE  │
       │                          │                              │
       │                          │  ✅ Valid                    │
       │                          └──────────────┬───────────────┘
       │                                         ▼
       │                          ┌──────────────────────────────┐
       │                          │  Step 7: EXECUTE SQL         │
       │                          │                              │
       │                          │  Connect to user DB (conn=3) │
       │                          │  Execute: SELECT COUNT(*)... │
       │                          │                              │
       │                          │  Result: [[275]]             │
       │                          │  Columns: ["count"]          │
       │                          └──────────────┬───────────────┘
       │                                         ▼
       │                          ┌──────────────────────────────┐
       │                          │  Step 8: FORMAT ANSWER       │
       │                          │                              │
       │                          │  answer = ollama.generate(   │
       │                          │    "Format this result:      │
       │                          │     Question: 'How many...'  │
       │                          │     SQL: 'SELECT COUNT...'   │
       │                          │     Result: [[275]]"         │
       │                          │  )                           │
       │                          │                              │
       │                          │  → "There are 275 artists    │
       │                          │     in the database."        │
       │                          └──────────────┬───────────────┘
       │                                         │
       ▼                                         ▼
┌──────────────────┐              ┌──────────────────────┐
│  CATALOG RESULT  │              │    DATA RESULT       │
│                  │              │                      │
│  {               │              │  {                   │
│   type: catalog, │              │   status: success,   │
│   answers: {     │              │   answer: "There...",│
│     schema:...,  │              │   sql: "SELECT...",  │
│     indexes:...  │              │   rows: [[275]],     │
│   }              │              │   columns: ["count"],│
│  }               │              │   row_count: 1       │
│                  │              │  }                   │
└──────────────────┘              └──────────────────────┘
```

### Detailed Steps

#### Step 1: Intent Classification
**File**: `app/services/ollama_service.py`

```python
def classify_intent(prompt: str) -> str:
    system_prompt = """
    Classify the user query as either 'catalog' or 'data'.
    
    Catalog queries ask about:
    - Schema, tables, columns, indexes
    - Database structure or metadata
    - Open connections, slow queries
    - System information
    
    Data queries ask about:
    - Actual data stored in tables
    - Counts, aggregations, filtering
    - Business questions requiring data retrieval
    
    Answer with just one word: catalog or data
    """
    
    response = ollama.chat(
        model="llama3.2",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    )
    
    return response.strip().lower()  # "catalog" or "data"
```

#### Step 2-3: Embedding & Vector Search
**Files**: `app/services/ollama_service.py`, `app/services/vector_service.py`

```python
# Generate embedding
embedding = ollama_service.embed_text(prompt)  # 768-dim vector

# Search Qdrant
results = qdrant_client.search(
    collection_name="dbchat_embeddings",
    query_vector=embedding,
    query_filter={
        "must": [
            {"key": "connection_id", "match": {"value": connection_id}}
        ]
    },
    limit=top_k_tables,
    with_payload=True,
    score_threshold=0.5  # Minimum similarity
)

# Results sorted by cosine similarity
# Each result contains: id, score, payload{table_name, columns, ...}
```

#### Step 4: Schema Context Building
**File**: `app/services/chat_service.py`

```python
def _build_schema_context(connection_id, table_names):
    context_parts = []
    
    for table_name in table_names:
        # Get table from metadata DB
        table = db.query(Table).filter(
            Table.database.has(connection_id=connection_id),
            Table.name == table_name
        ).first()
        
        if not table:
            continue
        
        # Get columns
        columns = db.query(Column).filter(
            Column.table_id == table.id
        ).all()
        
        # Format context
        col_desc = ", ".join([
            f"{c.name} ({c.data_type}{'? nullable' if c.is_nullable else ''})"
            for c in columns
        ])
        
        context_parts.append(
            f"Table: {table.name}\nColumns: {col_desc}"
        )
    
    return "\n\n".join(context_parts)
```

**Example Output**:
```
Table: artist
Columns: ArtistId (integer), Name (character varying? nullable)

Table: album
Columns: AlbumId (integer), Title (character varying? nullable), ArtistId (integer? nullable)
```

#### Step 5: SQL Generation
**File**: `app/services/ollama_service.py`

```python
def generate_sql(prompt: str, schema_context: str) -> str:
    system_prompt = f"""
    You are a PostgreSQL expert. Generate a valid SELECT query.
    
    Available schema:
    {schema_context}
    
    Rules:
    - Only generate SELECT statements
    - Use proper PostgreSQL syntax
    - Return only the SQL, no explanation
    - Use table and column names exactly as shown
    """
    
    response = ollama.chat(
        model="llama3.2",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    )
    
    # Extract SQL (handle code blocks)
    sql = response.strip()
    if "```" in sql:
        sql = re.search(r"```(?:sql)?\n(.*?)\n```", sql, re.DOTALL).group(1)
    
    return sql.strip()
```

#### Step 6: SQL Validation
**File**: `app/services/chat_service.py`

```python
def _validate_sql(sql: str) -> Optional[str]:
    if not sql:
        return "SQL is empty"
    
    sql_upper = sql.strip().upper()
    
    # Must start with SELECT
    if not sql_upper.startswith("SELECT"):
        return "Only SELECT queries allowed"
    
    # Forbidden commands
    forbidden = ["DELETE", "DROP", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "CREATE"]
    for cmd in forbidden:
        if cmd in sql_upper:
            return f"Command '{cmd}' not allowed"
    
    return None  # Valid
```

#### Step 7: SQL Execution
**File**: `app/services/chat_service.py`

```python
def _execute_query(connection: Connection, sql: str):
    # Build connection URL
    db_url = f"postgresql://{connection.username}:{connection.password}@" \
             f"{connection.host}:{connection.port}/{connection.database}?sslmode=require"
    
    engine = create_engine(db_url, poolclass=NullPool)
    
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        rows = result.fetchall()
        columns = list(result.keys())
    
    engine.dispose()
    
    return {
        "rows": [list(row) for row in rows],
        "columns": columns,
        "row_count": len(rows)
    }
```

#### Step 8: Natural Language Formatting
**File**: `app/services/ollama_service.py` + `chat_service.py`

```python
def _format_answer(prompt, sql, rows, columns):
    # Build result summary
    result_text = f"SQL: {sql}\nRows returned: {len(rows)}\n"
    if rows:
        result_text += f"First few rows: {rows[:3]}"
    
    system_prompt = """
    Format the SQL query result into a natural language answer.
    Be concise and clear.
    """
    
    user_prompt = f"""
    Question: {prompt}
    SQL: {sql}
    Result: {result_text}
    
    Provide a clear natural language answer.
    """
    
    answer = ollama.chat(
        model="llama3.2",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )
    
    return answer.strip()
```

---

## Catalog Query Path

For catalog/introspection queries, the flow is simpler:

```
Intent = "catalog"
   ↓
Analyze prompt for keywords:
- "schema of <table>" → query information_schema.columns
- "indexes" → query pg_catalog
- "open connections" → query pg_stat_activity
- "slow queries" → query pg_stat_activity (long-running)
   ↓
Execute direct SQL on target database
   ↓
Return structured results (no LLM formatting needed)
```

**Example Catalog Queries**:

```python
# Schema
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema='public' AND table_name=:table_name
ORDER BY ordinal_position;

# Indexes
SELECT i.relname as indexname, array_to_string(array_agg(a.attname), ',') as columns
FROM pg_class t
JOIN pg_index ix ON t.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
WHERE t.relname = :table_name
GROUP BY i.relname;

# Active connections
SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();

# Slow queries
SELECT pid, usename, state, now() - query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active' AND datname = current_database()
ORDER BY now() - query_start DESC LIMIT 10;
```

---

## Component Interactions

### Services Overview

```
┌────────────────────────────────────────────────────────────┐
│                    SERVICES LAYER                          │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ChatService                                               │
│  ├─ Orchestrates entire query flow                        │
│  ├─ Calls OllamaService for classification & generation   │
│  ├─ Calls VectorService for embedding search              │
│  └─ Handles both catalog and data query paths             │
│                                                            │
│  SchemaService                                             │
│  ├─ Connects to external databases                        │
│  ├─ Extracts schema from information_schema               │
│  └─ Returns structured TableSchema objects                │
│                                                            │
│  IndexingService                                           │
│  ├─ Takes schema and generates embeddings                 │
│  ├─ Stores vectors in Qdrant                              │
│  └─ Persists metadata in PostgreSQL                       │
│                                                            │
│  OllamaService                                             │
│  ├─ classify_intent(prompt) → "catalog" | "data"          │
│  ├─ embed_text(text) → 768-dim vector                     │
│  ├─ generate_sql(prompt, context) → SQL string            │
│  └─ generate(prompt) → natural language text              │
│                                                            │
│  VectorService                                             │
│  ├─ upsert(collection, points) → store embeddings         │
│  ├─ search(collection, vector, filter) → similar vectors  │
│  └─ delete_collection(name) → cleanup                     │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Database Interactions

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│  PostgreSQL  │       │    Qdrant    │       │    Ollama    │
│  (Metadata)  │       │   (Vectors)  │       │     (LLM)    │
└──────┬───────┘       └──────┬───────┘       └──────┬───────┘
       │                      │                       │
       │ Store metadata       │ Store embeddings      │ Generate
       │ (connections,        │ (768-dim vectors      │ (intent,
       │  databases,          │  + payloads)          │  SQL,
       │  tables,             │                       │  answers)
       │  columns)            │                       │
       │                      │                       │
       └──────────┬───────────┴───────────┬───────────┘
                  │                       │
                  │   Called by Services  │
                  │                       │
              ┌───┴───────────────────────┴───┐
              │    Application Services       │
              └───────────────────────────────┘
```

---

## Data Models

### Metadata Database Schema

```sql
-- Connection to external database
CREATE TABLE connections (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    host VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL DEFAULT 5432,
    database VARCHAR(255) NOT NULL,
    username VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,  -- TODO: encrypt
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Database extracted from connection
CREATE TABLE databases (
    id SERIAL PRIMARY KEY,
    connection_id INTEGER REFERENCES connections(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(connection_id, name)
);

-- Tables in database
CREATE TABLE tables (
    id SERIAL PRIMARY KEY,
    database_id INTEGER REFERENCES databases(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    row_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(database_id, name)
);

-- Columns in table
CREATE TABLE columns (
    id SERIAL PRIMARY KEY,
    table_id INTEGER REFERENCES tables(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    data_type VARCHAR(100) NOT NULL,
    is_nullable BOOLEAN DEFAULT TRUE,
    column_default TEXT,
    ordinal_position INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Qdrant Vector Storage

```json
{
  "collection_name": "dbchat_embeddings",
  "vector_size": 768,
  "distance": "Cosine",
  "points": [
    {
      "id": "uuid-1",
      "vector": [0.123, -0.456, 0.789, ...],  // 768 dimensions
      "payload": {
        "connection_id": 3,
        "database_name": "chinook",
        "table_name": "artist",
        "columns": ["ArtistId", "Name"],
        "embedding_text": "Table: artist\nColumns: ArtistId (integer), Name (varchar)"
      }
    }
  ]
}
```

---

## Performance Considerations

### Caching Strategy
- **Redis**: Cache frequent queries and results
- **TTL**: 5 minutes for query results
- **Keys**: `query:{connection_id}:{hash(prompt)}`

### Vector Search Optimization
- **Index**: HNSW (Hierarchical Navigable Small World)
- **Similarity**: Cosine distance
- **Threshold**: 0.5 minimum score
- **Top-K**: Limit to 5 tables by default

### Connection Pooling
- **NullPool**: Used for external database connections (no pooling)
- **Timeout**: 10 seconds for connection attempts
- **SSL**: Required for remote connections

### Query Timeouts
- **Ollama**: 30 seconds per request
- **SQL Execution**: 30 seconds query timeout
- **Total Request**: ~60 seconds max

---

## Error Handling

### Common Error Scenarios

1. **Connection Failure**
   - Database unreachable
   - Invalid credentials
   - SSL/TLS issues
   - → Return 500 with connection error message

2. **Invalid SQL**
   - LLM generates non-SELECT query
   - Validation fails
   - → Return 400 with validation error

3. **Query Execution Error**
   - Syntax error in generated SQL
   - Table/column doesn't exist
   - → Return 500 with execution error

4. **No Relevant Tables Found**
   - Vector search returns no results above threshold
   - → Return message: "No relevant tables found for your question"

5. **LLM Service Down**
   - Ollama unavailable
   - Timeout
   - → Return 503 Service Unavailable

---

## Future Enhancements

### Planned Features
1. **Multi-database JOIN queries** - Query across multiple connected databases
2. **Query history** - Store and retrieve past queries
3. **Query optimization** - Suggest indexes, analyze query plans
4. **Role-based access** - User permissions per connection
5. **Async processing** - Background indexing, queue long queries
6. **Webhook notifications** - Alert on slow queries, errors
7. **Natural language updates** - Support INSERT/UPDATE via approval workflow
8. **Auto-refresh metadata** - Detect schema changes and re-index
9. **Multi-tenant support** - Isolate connections per organization
10. **Advanced caching** - Semantic cache for similar queries

---

## Troubleshooting

### Common Issues

**Issue**: Indexing fails with "connection timeout"
- **Solution**: Check network connectivity, increase timeout, verify credentials

**Issue**: Vector search returns no results
- **Solution**: Check if embeddings were created, verify connection_id filter, lower similarity threshold

**Issue**: Generated SQL is invalid
- **Solution**: Improve schema context, add examples to LLM prompt, tune model parameters

**Issue**: Catalog queries return empty results
- **Solution**: Verify information_schema access, check table_schema filter ('public')

**Issue**: Slow query performance
- **Solution**: Add indexes on external DB, limit result rows, optimize vector search top_k

---

## Monitoring & Logging

### Log Levels
- **INFO**: Request flow, query execution
- **DEBUG**: Vector search results, LLM responses
- **ERROR**: Failures, exceptions
- **WARNING**: Validation issues, slow queries

### Key Metrics to Monitor
- Request latency (p50, p95, p99)
- Vector search time
- SQL execution time
- LLM response time
- Error rate by type
- Active connections count
- Qdrant collection size
- Metadata DB growth

---

## Security Best Practices

### Current Implementation
- SQL validation (SELECT only)
- Connection timeout limits
- SSL required for remote connections

### Recommended Additions
1. **Password encryption** - Encrypt stored credentials
2. **API authentication** - JWT tokens, API keys
3. **Rate limiting** - Per-user/IP limits
4. **Query whitelisting** - Approve specific query patterns
5. **Audit logging** - Track all queries and access
6. **Network isolation** - VPN/private network for DB connections
7. **Secrets management** - Use Vault or AWS Secrets Manager
8. **Input sanitization** - Additional SQL injection protection

---

## Appendix: Example Queries

### Onboarding Example
```bash
# Register connection
curl -X POST http://localhost:8000/api/admin/connections \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Chinook Production",
    "host": "ep-quiet-rain-12345.us-east-2.aws.neon.tech",
    "port": 5432,
    "database": "chinook",
    "username": "neondb_owner",
    "password": "your_password"
  }'

# Index database
curl -X POST http://localhost:8000/api/admin/index/3
```

### Data Query Examples
```bash
# Simple count
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "How many tracks are there?"
  }'

# Aggregation
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "What is the total duration of all tracks by genre?"
  }'

# Join query
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "Show me all albums by artists whose name starts with A"
  }'
```

### Catalog Query Examples
```bash
# Schema inspection
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "Give me the schema of the track table"
  }'

# Index information
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "Which columns in the invoice table have indexes?"
  }'

# Active connections
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "How many open connections are there?"
  }'
```

---

**Document Version**: 1.0  
**Last Updated**: 2026-02-23  
**Maintained By**: DbChat Development Team
