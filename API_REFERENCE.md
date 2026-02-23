# DbChat API Reference

## Base URL
```
http://localhost:8000
```

## Endpoints

### 1. Health Check

**Endpoint**: `GET /health`

**Description**: Check if the API is running and healthy.

**Response**:
```json
{
  "status": "healthy",
  "timestamp": "2026-02-23T10:30:45.123456"
}
```

---

### 2. Register Database Connection

**Endpoint**: `POST /api/admin/connections`

**Description**: Register a new database connection for onboarding.

**Request Body**:
```json
{
  "name": "My Production DB",
  "host": "db.example.com",
  "port": 5432,
  "database": "mydb",
  "username": "dbuser",
  "password": "secretpass"
}
```

**Response** (201 Created):
```json
{
  "id": 1,
  "name": "My Production DB",
  "host": "db.example.com",
  "port": 5432,
  "database": "mydb",
  "username": "dbuser",
  "created_at": "2026-02-23T10:30:45.123456"
}
```

**Error Responses**:
- `400 Bad Request`: Invalid connection parameters
- `500 Internal Server Error`: Connection test failed

---

### 3. List Database Connections

**Endpoint**: `GET /api/admin/connections`

**Description**: Get all registered database connections.

**Response**:
```json
[
  {
    "id": 1,
    "name": "My Production DB",
    "host": "db.example.com",
    "port": 5432,
    "database": "mydb",
    "username": "dbuser",
    "created_at": "2026-02-23T10:30:45.123456"
  }
]
```

---

### 4. Index Database

**Endpoint**: `POST /api/admin/index/{connection_id}`

**Description**: Extract schema from database and index embeddings into vector store.

**Path Parameters**:
- `connection_id` (integer): ID of the database connection to index

**Response**:
```json
{
  "status": "success",
  "connection_id": 1,
  "tables_indexed": 15,
  "columns_indexed": 127,
  "embeddings_created": 142
}
```

**Error Responses**:
- `404 Not Found`: Connection ID not found
- `500 Internal Server Error`: Indexing failed

**Notes**:
- This process extracts all tables and columns from `information_schema`
- Generates embeddings using Ollama (nomic-embed-text model)
- Stores vectors in Qdrant collection `dbchat_embeddings`
- Persists metadata in PostgreSQL

---

### 5. Chat Query

**Endpoint**: `POST /api/chat`

**Description**: Process natural language queries - either catalog/introspection queries or data queries that generate SQL.

**Request Body**:
```json
{
  "connection_id": 1,
  "prompt": "How many users signed up last month?",
  "top_k_tables": 5
}
```

**Parameters**:
- `connection_id` (integer, required): Database connection to query
- `prompt` (string, required): Natural language question or request
- `top_k_tables` (integer, optional, default=5): Number of relevant tables to consider

**Response Types**:

#### A. Data Query Response (SQL Generated)
```json
{
  "status": "success",
  "answer": "There are 275 artists in the database.",
  "sql": "SELECT COUNT(*) FROM artist;",
  "rows": [[275]],
  "columns": ["count"],
  "row_count": 1,
  "execution_time_ms": 1250,
  "query_time_ms": 45,
  "error": null
}
```

#### B. Catalog Query Response (Introspection)
```json
{
  "status": "success",
  "type": "catalog",
  "answers": {
    "schema:artist": [
      {
        "column_name": "ArtistId",
        "data_type": "integer",
        "is_nullable": "NO",
        "column_default": "nextval('artist_artistid_seq'::regclass)"
      },
      {
        "column_name": "Name",
        "data_type": "character varying",
        "is_nullable": "YES",
        "column_default": null
      }
    ]
  },
  "execution_time_ms": 850,
  "error": null
}
```

#### C. Error Response
```json
{
  "status": "error",
  "error": "Connection not found",
  "execution_time_ms": 10,
  "answer": null,
  "sql": null,
  "rows": null,
  "columns": null
}
```

**Catalog Query Types**:

The system automatically detects catalog/introspection queries:

1. **Schema Information**
   - Prompt: "Give me the schema of artist table"
   - Returns: Column names, data types, nullable, defaults

2. **Index Information**
   - Prompt: "Which columns in album table have indexes?"
   - Returns: Index names and indexed columns

3. **Active Connections**
   - Prompt: "How many open connections are there?"
   - Returns: Connection count and active query details

4. **Slow Queries**
   - Prompt: "Show me slow queries"
   - Returns: Long-running active queries with duration

5. **Table List**
   - Prompt: "What tables are in the database?"
   - Returns: List of all tables in public schema

**Data Query Examples**:

```bash
# Simple count
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "How many artists are in the database?"
  }'

# Join query
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "Show me albums by AC/DC"
  }'

# Aggregation
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "What is the average track length by genre?"
  }'
```

**Catalog Query Examples**:

```bash
# Schema inspection
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "Give me the schema of artist table"
  }'

# Active connections
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "How many open connections are there?"
  }'
```

**Error Responses**:
- `404 Not Found`: Connection ID not found
- `400 Bad Request`: Invalid SQL generated or validation failed
- `500 Internal Server Error`: Query execution failed

---

## Query Processing Flow

1. **Intent Classification**: LLM determines if query is "catalog" or "data"
2. **Catalog Path**: Direct information_schema/pg_catalog queries
3. **Data Path**:
   - Embed user prompt
   - Vector search for relevant tables
   - Build schema context
   - Generate SQL using LLM
   - Validate SQL (SELECT only)
   - Execute on target database
   - Format natural language answer

---

## Security & Validation

### SQL Validation Rules
- Only `SELECT` statements allowed
- Forbidden commands: `DELETE`, `DROP`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, `CREATE`
- Queries are executed with read-only intent

### Connection Security
- Passwords are stored in plaintext (TODO: implement encryption)
- SSL mode required for remote connections
- Connection timeout: 10 seconds

---

## Rate Limiting

Currently not implemented. Consider adding rate limiting for production:
- Per-user request limits
- Query complexity limits
- Concurrent execution limits

---

## Authentication

Currently not implemented. Future considerations:
- API key authentication
- JWT tokens
- Role-based access control (RBAC)
- Connection-level permissions

---

## Error Codes

| Status Code | Description |
|-------------|-------------|
| 200 | Success |
| 201 | Created (new connection) |
| 400 | Bad Request (invalid input or SQL) |
| 404 | Not Found (connection ID) |
| 500 | Internal Server Error |

---

## Environment Variables

```bash
# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=dbchat_metadata
DB_USER=dbchat
DB_PASSWORD=dbchat123

# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
OLLAMA_EMBED_MODEL=nomic-embed-text

# Qdrant Configuration
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=dbchat_embeddings

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Application
LOG_LEVEL=INFO
```

---

## Dependencies

- **FastAPI**: Web framework
- **SQLAlchemy**: ORM and database toolkit
- **PostgreSQL**: Metadata storage
- **Qdrant**: Vector database
- **Ollama**: LLM and embeddings
- **Redis**: Caching layer
- **Uvicorn**: ASGI server

---

## Development

### Start Server
```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Start with Docker
```bash
docker-compose up -d
```

### Run Tests
```bash
pytest tests/
```

---

## Support

For issues or questions, please check the project repository or contact the development team.
