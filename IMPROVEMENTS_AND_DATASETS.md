# DbChat: Recommended Improvements & Open Source Datasets

---

## Part 1: Technical Improvements

### 1. **Query Result Limiting & Pagination**
**Priority: HIGH** | **Effort: MEDIUM**

**Current Issue:**
- No row limits on data queries (e.g., `_format_answer()` returns ALL rows from result set)
- Large result sets (e.g., 10K+ rows) cause:
  - Slow response times
  - Large JSON payloads
  - Network bottlenecks
  - Poor UX (user can't read 50K rows)

**Solution:**
```python
# In ChatService._format_answer()
MAX_DISPLAY_ROWS = 100
MAX_RESULT_ROWS = 10000  # Hard limit on execution

# Add pagination to response:
{
  "status": "success",
  "answer": "...",
  "sql": "...",
  "rows": [...first 100],
  "columns": [...],
  "row_count": 10000,
  "total_rows": 47283,        # NEW
  "rows_returned": 100,        # NEW
  "pagination": {              # NEW
    "limit": 100,
    "offset": 0,
    "has_more": true
  },
  "execution_time_ms": 450,
  "query_time_ms": 120
}
```

**Implementation:**
- Add `LIMIT` clause to generated SQL (after semicolon extraction)
- Modify `_execute_query()` to pass `top_k*100` as row limit
- Add `OFFSET` support for `GET /api/chat/results/{request_id}/page/{page_num}`
- Cache full result sets in Redis with 5-min TTL

---

### 2. **Multi-Step Query Reasoning & Self-Correction**
**Priority: HIGH** | **Effort: HARD**

**Current Issue:**
- LLM generates SQL in single pass without validation
- Hallucinations (wrong column names, missing joins) are common
- No mechanism to ask clarifying questions

**Solution: Chain-of-Thought + Self-Correction Loop**
```
Step 1: LLM generates SQL (current flow)
         ↓
Step 2: NEW - Validate SQL syntax
         ├─ If error: Pass error + hint back to LLM
         └─ If syntax OK: Continue
         ↓
Step 3: NEW - Dry-run validation on Postgres
         ├─ Execute: EXPLAIN ANALYZE ... LIMIT 0
         ├─ If error: Pass error back to LLM with schema hint
         └─ If OK: Execute for real
         ↓
Step 4: NEW - Validate result semantics
         ├─ Is row count reasonable? (0 or > 1M rows might be wrong)
         ├─ Are column types sensible?
         └─ If suspicious: Ask LLM to reconsider
```

**Implementation:**
```python
async def _validate_and_refine_sql(self, sql: str, schema_context: str, user_prompt: str, attempt: int = 1) -> str:
    """Try to execute SQL, refine if it fails"""
    if attempt > 3:
        raise Exception("Max refinement attempts reached")
    
    # Step 1: Dry-run with EXPLAIN
    try:
        result = await self._execute_query(connection, f"EXPLAIN {sql}", timeout=5)
        if result["status"] != "error":
            return sql  # SQL is valid
    except Exception as e:
        pass
    
    # Step 2: Ask LLM to fix the error
    error_msg = str(result.get("error", "Unknown error"))
    refinement_prompt = f"""Previous SQL failed with error: {error_msg}
    
Please provide a corrected SQL query. User asked: {user_prompt}

Available schema:
{schema_context}"""
    
    refined_sql = await self.ollama.generate_sql(refinement_prompt, schema_context, "")
    return await self._validate_and_refine_sql(refined_sql, schema_context, user_prompt, attempt + 1)
```

---

### 3. **Better Error Messages & Disambiguation**
**Priority: MEDIUM** | **Effort: MEDIUM**

**Current Issue:**
- Generic error messages: "Invalid SQL", "No relevant tables found"
- User doesn't know what went wrong or how to fix it
- No suggestions for similar tables/queries

**Solution:**
```python
# Add error context objects
{
  "status": "error",
  "error": "No relevant tables found for your query",
  "suggestions": {                          # NEW
    "similar_tables": ["invoices", "invoice_line", "order_items"],
    "sample_queries": [
      "Show me invoices by customer",
      "What is the total revenue?",
      "List all customers"
    ],
    "hint": "Did you mean to query 'invoice' instead of 'invoices'?"
  },
  "execution_time_ms": 145
}
```

**Implementation:**
- Add `SimilarityService` to find closest table names via Qdrant fuzzy search
- Cache popular sample queries per database
- Add Levenshtein distance to suggest corrections

---

### 4. **Request Caching & Query Deduplication**
**Priority: MEDIUM** | **Effort: LOW**

**Current Issue:**
- Same question asked twice = runs twice (expensive LLM calls + DB queries)
- No cache key strategy

**Solution:**
```python
# In ChatService.process_query()
cache_key = f"query:{connection_id}:{hash(user_prompt)}"

# Check cache first
cached = await self.cache.get(cache_key)
if cached:
    logger.info(f"Cache hit for {user_prompt[:50]}")
    return cached

# ... execute query ...

# Cache result (TTL varies by query type)
ttl = 3600 if intent == "data" else 86400  # 1hr for data, 24hr for catalog
await self.cache.set(cache_key, result, ttl=ttl)
```

**Benefits:**
- 50-90% faster for repeated questions
- Reduced LLM API calls
- Lower database load

---

### 5. **Cost & Performance Tracking**
**Priority: MEDIUM** | **Effort: LOW**

**Current Issue:**
- No visibility into query costs (LLM tokens, DB query time, etc.)
- Can't identify expensive queries

**Solution:**
```python
# Add telemetry to response
{
  "status": "success",
  "answer": "...",
  "telemetry": {                           # NEW
    "tokens_used": 342,
    "llm_call_time_ms": 2100,
    "embedding_time_ms": 450,
    "vector_search_time_ms": 120,
    "sql_generation_time_ms": 890,
    "sql_execution_time_ms": 180,
    "total_time_ms": 3840,
    "estimated_cost_usd": 0.0034,          # Based on token count
    "database_rows_scanned": 47283,
    "database_rows_returned": 100
  }
}
```

**Implementation:**
- Add timestamps at each stage
- Calculate token count from LLM response
- Track DB stats via EXPLAIN ANALYZE
- Store in analytics table for dashboarding

---

### 6. **Support for Non-Relational Databases**
**Priority: MEDIUM** | **Effort: HARD**

**Current Issue:**
- Only PostgreSQL/MySQL supported
- No MongoDB, DynamoDB, Elasticsearch, BigQuery, Snowflake, etc.

**Solution:**
```python
# Create database adapters
class DatabaseAdapter(ABC):
    @abstractmethod
    async def get_schema(self): pass
    
    @abstractmethod
    async def execute_query(self, sql): pass

class PostgresAdapter(DatabaseAdapter):
    # ... current implementation

class MongoDBAdapter(DatabaseAdapter):
    async def execute_query(self, mongo_query):
        # Convert SQL-like intent to MongoDB aggregation
        # or use text2mongo LLM prompt
        pass

class ElasticsearchAdapter(DatabaseAdapter):
    async def execute_query(self, es_query):
        # Convert to ES DSL
        pass
```

**Priority Databases:**
1. **MongoDB** (document stores are common)
2. **BigQuery** (enterprise data warehousing)
3. **Snowflake** (modern data cloud)
4. **Elasticsearch** (search/logging)

---

### 7. **Conversation History & Multi-Turn Queries**
**Priority: MEDIUM** | **Effort: MEDIUM**

**Current Issue:**
- Single-turn only: no context between queries
- User can't say: "Show revenue by genre" → "Now just show top 5"

**Solution:**
```python
# Add session management
POST /api/chat/sessions       # Create session
POST /api/chat/sessions/{id}  # Send query with context

# Request
{
  "session_id": "sess_abc123",
  "prompt": "Now just show top 5",
  "context": {
    "previous_sql": "SELECT genre, revenue FROM ...",
    "previous_answer": "..."
  }
}

# LLM system prompt includes:
"Previous query context:
Query: Show revenue by genre
Result: 24 genres listed
Now user asks: Now just show top 5
Refined query: SELECT genre, revenue FROM ... ORDER BY revenue DESC LIMIT 5"
```

---

### 8. **Audit & Security Logging**
**Priority: HIGH** | **Effort: LOW**

**Current Issue:**
- No audit trail of who queried what
- No PII redaction
- Can't detect suspicious patterns

**Solution:**
```python
# Log all queries with metadata
{
  "timestamp": "2026-02-24T10:30:00Z",
  "user_id": "user_123",
  "connection_id": 3,
  "prompt": "Show all customer email addresses",
  "intent": "data",
  "sql_generated": "SELECT email FROM customer",
  "row_count": 5000,
  "execution_time_ms": 234,
  "status": "success",
  "pii_detected": ["email"],                # NEW
  "pii_redacted": false,                    # NEW
  "ip_address": "192.168.1.1"
}
```

---

## Part 2: Open Source Datasets to Test

### **Tier 1: Most Valuable (Start Here)**

#### 1. **IMDB (Movie Database)**
- **Size**: ~10M rows, ~20 tables
- **Complexity**: Medium (foreign keys, text search)
- **Value**: Real-world schema, natural queries
- **Download**: [IMDB Datasets](https://datasets.imdbws.com/)
- **Test Cases**:
  - "Which movies released in 2020 have ratings above 8?"
  - "Show top 10 directors by average movie rating"
  - "Find actors who appear in both comedies and dramas"

**Benefit**: Movie domain is familiar to users, lots of natural questions.

---

#### 2. **TPC-H (Benchmark Dataset)**
- **Size**: 100MB–100GB+ (scalable)
- **Complexity**: HIGH (22 complex OLAP queries included)
- **Value**: Industry standard for testing SQL performance
- **Download**: [TPC-H Benchmark](http://www.tpc.org/tpch/)
- **Test Cases**:
  - "What is the revenue of orders from France in 1995?"
  - "Find the suppliers with the highest supply share in each region"
  - "Analyze market segment profitability by nation"

**Benefit**: Validates system on complex multi-join, multi-aggregate queries.

---

#### 3. **Sakila (MySQL Demo DB)**
- **Size**: Small (~100K rows, 16 tables)
- **Complexity**: Medium (relationships, business logic)
- **Value**: Movie rental business scenario
- **Download**: [MySQL Sakila](https://dev.mysql.com/doc/sakila/en/)
- **Test Cases**:
  - "Which customer rented the most movies?"
  - "Show revenue by film category"
  - "Find actors with the highest number of film appearances"

**Benefit**: Good intermediate complexity; already has sample queries for comparison.

---

#### 4. **Amazon Reviews (Large-Scale Text)**
- **Size**: 130M reviews, 5 tables
- **Complexity**: Medium (text search, aggregations)
- **Value**: Real large-scale data; text analytics
- **Download**: [Amazon Reviews Dataset](https://huggingface.co/datasets/amazon_us_reviews)
- **Test Cases**:
  - "Which products have the highest average rating?"
  - "Show number of reviews per year"
  - "Find reviewers with the most helpful votes"

**Benefit**: Tests system on large-scale data and text fields.

---

### **Tier 2: Specialized Use Cases (Secondary)**

#### 5. **OpenStreetMap (Geospatial)**
- **Complexity**: HARD (geometry columns, spatial joins)
- **Value**: Tests non-standard data types
- **Use Case**: "Find all hospitals within 5km of downtown"

#### 6. **Wikipedia (Full-Text Search)**
- **Complexity**: HARD (text indexing, full-text search)
- **Value**: Tests search/information retrieval queries
- **Use Case**: "Find articles mentioning both 'machine learning' and 'neural networks'"

#### 7. **COVID-19 Dataset (Time Series)**
- **Complexity**: Medium (time-series aggregations, grouping)
- **Value**: Tests temporal queries
- **Use Case**: "Show weekly death rate trend by country"

#### 8. **GitHub Events (JSON/NoSQL)**
- **Complexity**: HARD (nested JSON, event streaming)
- **Value**: Tests semi-structured data
- **Use Case**: "Find repos with the most recent push activity"

---

### **Tier 3: Integration Tests (Stretch)**

#### 9. **Northwind (Multi-DB Testing)**
- **Available For**: PostgreSQL, MySQL, SQL Server
- **Use**: Test same queries across different SQL dialects
- **Size**: ~90K rows, 13 tables

#### 10. **World Bank Open Data**
- **Size**: Varies (economic indicators)
- **Complexity**: Medium (time-series, grouping)
- **API-Based**: Can test real API integration
- **Use Case**: "Show GDP per capita growth by region"

---

## Part 3: Implementation Plan

### **Week 1: Quick Wins**
1. Implement **#4 Request Caching** (1-2 hours)
2. Implement **#3 Better Error Messages** (3 hours)
3. Implement **#5 Cost Tracking** (2 hours)

### **Week 2: Core Improvements**
1. Implement **#1 Query Result Limiting** (4 hours)
2. Start **#2 Multi-Step Reasoning** (8 hours)

### **Week 3: Testing Expansion**
1. Onboard **IMDB** database to test query variety
2. Onboard **Sakila** to test MySQL compatibility
3. Run **TPC-H queries** to stress-test system

### **Week 4: Advanced Features**
1. Implement **#7 Conversation History**
2. Implement **#8 Audit Logging**

---

## Part 4: Test Matrix for New Datasets

| Dataset | Tables | Rows | Joins | Aggregations | Text Search | Recommended LLM | Expected Success Rate |
|---------|--------|------|-------|--------------|-------------|-----------------|----------------------|
| Chinook (current) | 11 | 100K | 2-3 | Yes | No | llama3.2 | 85% |
| Sakila | 16 | 100K | 3-4 | Yes | No | llama3.2 | 80% |
| IMDB | 20 | 10M | 2-5 | Yes | Yes | llama3.2 → mistral | 70% |
| TPC-H | 8 | 100M+ | 5-8 | Heavy | No | mistral → gpt-4 | 60% |

---

## Priority Recommendation

**Start With:**
1. ✅ Sakila (easiest, MySQL variety)
2. ✅ IMDB (most intuitive, diverse queries)
3. ✅ Implement caching + error messages (easy wins)

**Then:**
4. TPC-H (validates scalability)
5. Multi-step reasoning (improves accuracy)
6. Conversation history (improves UX)

---

**Document Version**: 1.1 | **Date**: February 2026
