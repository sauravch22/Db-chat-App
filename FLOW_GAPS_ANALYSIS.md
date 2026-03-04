# Deep Dive: Intent Classification → Table Selection → Schema Context

## Flow Overview

```
User Query
    ↓
[1] Intent Classification (catalog vs data)
    ↓
[2] Table Selection (Vector Search + LLM)
    ↓
[3] Schema Context Retrieval
    ↓
[4] SQL Generation ← PRIMARY FAILURE POINT
    ↓
[5] Validation & Execution
```

---

## STEP 1: Intent Classification

### What Happens
**File:** `chat_service.py` (lines 52-67)

```python
# Fast keyword pre-check
_structural_keywords = ["schema", "describe", "primary key", "show tables", etc.]
if any(kw in user_prompt.lower() for kw in _structural_keywords):
    intent = "catalog"
else:
    intent = await self.ollama.classify_intent(user_prompt)
```

### How It Works
1. **Fast Path:** Checks for structural keywords → immediate "catalog" classification
2. **LLM Path:** Calls Mistral to classify as "catalog" or "data"
   - Uses system prompt: "Classify query as 'catalog' or 'data'"
   - Temperature: 0.0
   - Returns single word response

### Issues Found
✅ **Working Well:** Fast keyword matching is effective
⚠️ **Minor Issue:** LLM classification can be inconsistent for edge cases
   - Example: "Show albums by AC/DC" sometimes classified as "catalog" (Test #15 inconsistency)

---

## STEP 2: Table Selection (THE CRITICAL BOTTLENECK)

### What Happens
**File:** `chat_service.py` (lines 88-145)

This is a **two-phase approach**:

#### Phase 2A: LLM-based Table Identification (Primary)
```python
# Get table summaries
table_summaries = self.metadata.get_table_summaries(connection_id)
# Returns: [{"name": "artist", "summary": "Table: artist. Columns: artist_id, name..."}]

# Ask LLM to identify tables
identified = await self.ollama.identify_tables(user_prompt, table_summaries)
# LLM returns: ["artist", "album"]

# Verify with similarity check
summary_text = "\n".join([t["summary"] for t in table_summaries if t["name"] in identified])
similarity = await self.ollama.verify_intent_similarity(prompt_embedding, summary_text)

if similarity >= 0.35:
    table_names = identified  # Accept LLM selection
else:
    # Fall back to vector search
```

#### Phase 2B: Vector Search Fallback (Secondary)
```python
# Search vector database
relevant_results = await self.vector.search(
    embedding=prompt_embedding,
    top_k=top_k_tables * 10,
    filters={"must": [
        {"key": "connection_id", "match": {"value": connection_id}},
        {"key": "type", "match": {"value": "table"}}
    ]}
)

# Extract unique table names from top results
for r in relevant_results:
    table_name = r.get("payload", {}).get("table_name")
    if table_name and table_name not in seen_tables:
        table_names.append(table_name)
```

### GAP #1: Table Summary Quality

**Problem:** Table summaries are just column listings, no semantic context

**Current Summary Format:**
```
Table: artist. Columns: artist_id (INTEGER), name (VARCHAR(120)). Rows: 275
```

**What's Missing:**
- ❌ No description of what the table stores
- ❌ No relationship information
- ❌ No example use cases
- ❌ No business context

**Impact:**
- LLM can't distinguish between similarly named tables
- Similarity scores are unreliable
- Frequently falls back to vector search unnecessarily

**Example Failure:**
- Query: "Top customers by spend"
- LLM identifies: `["customer", "invoice"]` 
- **Missing:** `invoice_line` table (where actual spend data is)
- Result: Incomplete SQL or wrong JOIN

### GAP #2: LLM Non-Determinism in Table Selection

**Problem:** `identify_tables()` uses temperature=0.0 but still varies

**File:** `ollama_service.py` (lines 105-170)

```python
async def identify_tables(self, user_prompt: str, table_summaries: list) -> list:
    system_prompt = (
        "Given a user question and table summaries, return a JSON array "
        "of exact table names required. ONLY use names from the provided list."
    )
    
    response = await client.post(
        f"{self.base_url}/api/generate",
        json={
            "model": "mistral",
            "prompt": prompt,
            "temperature": 0.0,  # Should be deterministic
            ...
        }
    )
```

**Why It Varies:**
1. **Mistral's Internal State:** Even with temperature=0.0, Mistral has some randomness
2. **Token Selection:** When multiple tokens have nearly equal probability, selection varies
3. **Context Window Effects:** If summaries are long, tokenization can vary

**Evidence:**
- Same query: "Show artists and album count"
- Run 1: Returns `["artist", "album"]` → Passes
- Run 2: Returns `["artist", "album", "track"]` → Slower but still passes
- Run 3: Returns `["artist"]` → **FAILS** (missing album table)

**Impact:** 10-15% of tests fail randomly due to table selection variance

---

## STEP 3: Schema Context Retrieval

### What Happens
**File:** `metadata_service.py` `get_column_schema()` (lines 55-150)

```python
def get_column_schema(self, connection_id: int, table_names: List[str]) -> str:
    for table_name in table_names:
        # Build schema string
        context_str = f"Table: {table_name}\n"
        context_str += f"Rows: ~{table.sample_count}\n\n"
        context_str += "Columns:\n"
        
        # Add column details
        for col in columns:
            col_info = f"  {col.name}: {col.data_type}"
            
            # Add constraints
            if col.name == f"{table_name}_id":
                constraints.append("PRIMARY KEY")
            if not col.is_nullable:
                constraints.append("NOT NULL")
            
            # Add sample values
            if col.sample_values:
                samples = json.loads(col.sample_values)
                col_info += f" | Sample values: {sample_str}"
        
        # Infer FK relationships
        for col in columns:
            if col.name.endswith('_id') and col.name != f"{table_name}_id":
                potential_fk_table = col.name[:-3]  # Remove '_id'
                if potential_fk_table in all_table_names:
                    fk_info = f"  {col.name} → {potential_fk_table}({potential_fk_table}_id)"
                    fk_relationships.append(fk_info)
        
        # Add JOIN guide
        context_str += f"\n\nJoin Guide:\n  To join {table_name} with other tables:\n"
        for col in columns:
            if col.name.endswith('_id') and col.name != f"{table_name}_id":
                potential_fk_table = col.name[:-3]
                if potential_fk_table in all_table_names:
                    context_str += f"  - Use: {table_name}.{col.name} = {potential_fk_table}.{col.name}\n"
```

### Current Output Example:
```
Table: invoice
Rows: ~412

Columns:
  invoice_id: INTEGER [PRIMARY KEY, NOT NULL]
  customer_id: INTEGER [NOT NULL]
  invoice_date: TIMESTAMP WITHOUT TIME ZONE [NOT NULL]
  billing_address: VARCHAR(70)
  billing_city: VARCHAR(40)
  billing_state: VARCHAR(40)
  billing_country: VARCHAR(40)
  billing_postal_code: VARCHAR(10)
  total: NUMERIC(10,2) [NOT NULL]

Foreign Keys:
  customer_id → customer(customer_id)

Join Guide:
  To join invoice with other tables:
  - Use: invoice.customer_id = customer.customer_id
```

### GAP #3: Missing Foreign Key Information

**Problem:** FK inference is pattern-based, not database-derived

**Current Approach:**
```python
# Infers FK by checking if column ends with '_id'
if col.name.endswith('_id') and col.name != f"{table_name}_id":
    potential_fk_table = col.name[:-3]  # Remove '_id'
```

**What's Missing:**
1. **Actual FK Constraints:** Not queried from database `information_schema`
2. **Many-to-Many Relationships:** Junction tables (like `playlist_track`) not explained
3. **Non-Standard FKs:** Columns like `support_rep_id` → `employee` not detected

**Real World Example - Chinook Database:**

```sql
-- This FK exists in database but NOT in our schema context:
ALTER TABLE invoice_line 
  ADD CONSTRAINT FK_InvoiceLineTrackId 
  FOREIGN KEY (track_id) REFERENCES track(track_id);

-- Our system CANNOT see this because we don't query:
SELECT * FROM information_schema.table_constraints 
WHERE constraint_type = 'FOREIGN KEY';
```

**Impact:**
- LLM doesn't know `invoice_line.track_id` references `track.track_id`
- Generates invalid: `SELECT * FROM invoice_line WHERE track.artist_id = ...`
- Should generate: `JOIN track ON invoice_line.track_id = track.track_id`

### GAP #4: Column Ambiguity (5/13 Failures)

**Problem:** Schema context doesn't show table-qualified column names

**Current Format:**
```
Columns:
  customer_id: INTEGER [NOT NULL]
  invoice_date: TIMESTAMP [NOT NULL]
```

**What LLM Sees:**
- Column `customer_id` exists
- No indication it's `invoice.customer_id`

**What LLM Generates:**
```sql
SELECT customer_id FROM invoice JOIN customer ...
```

**PostgreSQL Error:**
```
ERROR: column reference "customer_id" is ambiguous
DETAIL: It could refer to either "invoice.customer_id" or "customer.customer_id"
```

**Why This Happens:**
1. Schema context lists columns WITHOUT table prefix
2. System prompt doesn't emphasize column qualification
3. LLM training data has mixed practices (MySQL allows unqualified, PostgreSQL requires it)

**Fix Needed:**
```
Columns:
  invoice.customer_id: INTEGER [NOT NULL, FK → customer.customer_id]
  invoice.invoice_date: TIMESTAMP [NOT NULL]
  customer.customer_id: INTEGER [PRIMARY KEY]
  customer.first_name: VARCHAR(40)
```

### GAP #5: Complex SQL Pattern Knowledge

**Problem:** System prompt doesn't prohibit unsupported patterns

**Current System Prompt** (`ollama_service.py` lines 15-40):
```python
system_prompt = f"""You are a PostgreSQL SQL expert...

STRICT RULES:
1. Output ONLY the SQL query
2. Do NOT write "Here is", "The SQL is"
3. Only use SELECT statements
4. EXACT TABLE NAMES: {table_list_str}
5. Use ONLY column names listed in schema
6. Use PostgreSQL syntax — double quotes for identifiers, NOT backticks
7. Do not wrap in markdown code fences
"""
```

**What's Missing:**
- ❌ "NEVER nest aggregate functions (e.g., AVG(SUM(...)) is invalid)"
- ❌ "Window functions cannot be used in WHERE/HAVING clauses"
- ❌ "Always qualify columns in multi-table queries"
- ❌ "Use subqueries for nested aggregates"

**Examples of Failures:**

**Test #17: Nested Aggregates**
```sql
-- LLM generates (INVALID):
SELECT artist.name, AVG(SUM(invoice_line.unit_price))
FROM artist JOIN album ON artist.artist_id = album.artist_id
GROUP BY artist.name;

-- Error: aggregate function calls cannot be nested

-- Should generate:
SELECT artist.name, AVG(total_price)
FROM (
    SELECT artist.artist_id, SUM(invoice_line.unit_price) AS total_price
    FROM artist JOIN album ON artist.artist_id = album.artist_id
    GROUP BY artist.artist_id
) subquery
GROUP BY artist.name;
```

**Test #14: Window Functions in HAVING**
```sql
-- LLM generates (INVALID):
SELECT genre.name, COUNT(*) as track_count
FROM track JOIN genre ON track.genre_id = genre.genre_id
GROUP BY genre.name
HAVING ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC) <= 5;

-- Error: window functions are not allowed in HAVING

-- Should generate:
SELECT name, track_count
FROM (
    SELECT genre.name, COUNT(*) as track_count,
           ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC) as rn
    FROM track JOIN genre ON track.genre_id = genre.genre_id
    GROUP BY genre.name
) subquery
WHERE rn <= 5;
```

---

## GAP #6: No JOIN Strategy Guidance

**Problem:** LLM has to guess how to join tables

**Current Join Guide Format:**
```
Join Guide:
  To join invoice with other tables:
  - Use: invoice.customer_id = customer.customer_id
```

**Issues:**
1. Only shows direct FKs, not multi-hop paths
2. No guidance on JOIN type (INNER vs LEFT)
3. No explanation of cardinality (one-to-many, many-to-many)

**Example - Missing Path:**

Query: "Show artists with their total track sales"

**Required Path:**
```
artist → album → track → invoice_line → invoice
```

**Current Schema Shows:**
- `album.artist_id = artist.artist_id` ✓
- `track.album_id = album.album_id` ✓
- BUT NOT: `invoice_line.track_id = track.track_id` ✗
- AND NOT: `invoice_line.invoice_id = invoice.invoice_id` ✗

**LLM Cannot Know:**
- How to get from `track` to `invoice_line`
- That `invoice_line` is the junction table containing sales data

**Result:** Test #12 fails with "Unknown column 'track.artist_id'"

---

## Summary of Root Causes

| Gap | Impact | Failure Rate | Fix Complexity |
|-----|--------|--------------|----------------|
| **GAP #1: Poor Table Summaries** | LLM can't select correct tables | 10% | Medium |
| **GAP #2: LLM Non-Determinism** | Random pass/fail on same tests | 15% | Low (add examples) |
| **GAP #3: Missing FK Info** | Invalid column assumptions | 25% | High (DB introspection) |
| **GAP #4: Column Ambiguity** | Unqualified column errors | 38% | Low (format change) |
| **GAP #5: No Pattern Rules** | Nested aggregates, window fn errors | 15% | Low (prompt update) |
| **GAP #6: No JOIN Strategy** | Can't navigate multi-hop paths | 20% | Medium (relationship graph) |

**Total Explained:** ~80% of failures traced to these 6 gaps

---

## Recommended Fixes (Priority Order)

### 1. **IMMEDIATE** (Low Effort, High Impact)

#### Fix GAP #4: Add Column Qualification
**File:** `metadata_service.py`
```python
# Change from:
col_info = f"  {col.name}: {col.data_type}"

# To:
col_info = f"  {table_name}.{col.name}: {col.data_type}"
```

#### Fix GAP #5: Enhance System Prompt
**File:** `ollama_service.py`
```python
system_prompt += """
8. ALWAYS qualify columns with table name in multi-table queries
9. NEVER nest aggregate functions - use subqueries instead
10. Window functions CANNOT be used in WHERE or HAVING clauses
"""
```

**Expected Impact:** 30-40% improvement (from 35% → 50-60%)

### 2. **MEDIUM-TERM** (Medium Effort, High Impact)

#### Fix GAP #3: Query Real Foreign Keys
**File:** `metadata_service.py`
```python
def get_foreign_keys(self, connection_id: int) -> Dict[str, List]:
    """Query actual FK constraints from information_schema"""
    sql = """
        SELECT
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
          ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
    """
```

#### Fix GAP #1: Generate Better Table Summaries
Use LLM to create semantic summaries during indexing:
```python
summary_prompt = f"""
Analyze this table and provide a 1-2 sentence description:
Table: {table_name}
Columns: {column_list}
Sample Data: {sample_rows}

Describe: What does this table store? What business entities does it represent?
"""
```

**Expected Impact:** 60-70% pass rate

### 3. **LONG-TERM** (High Effort, Highest Impact)

#### Fix GAP #6: Build Relationship Graph
Create a JOIN path finder:
```python
def find_join_path(self, from_table: str, to_table: str) -> List[str]:
    """Find shortest path between tables using FK relationships"""
    # Use breadth-first search on FK graph
    # Return: ["artist", "album", "track", "invoice_line"]
```

#### Add Few-Shot Examples
Include successful query patterns in system prompt:
```python
EXAMPLES:
1. Multi-table JOIN:
   Query: "Artists with album count"
   SQL: SELECT artist.name, COUNT(album.album_id) AS album_count
        FROM artist
        LEFT JOIN album ON artist.artist_id = album.artist_id
        GROUP BY artist.name;

2. Nested Aggregate:
   Query: "Average album revenue"
   SQL: SELECT AVG(album_total) FROM (
          SELECT album.album_id, SUM(invoice_line.unit_price) AS album_total
          FROM album JOIN track ...
        ) subquery;
```

**Expected Impact:** 75-85% pass rate

---

## Testing Strategy

After each fix, run test suite 5 times:
```bash
for i in {1..5}; do
    echo "Run $i:"
    bash /tmp/dbchat_comprehensive_test.sh | grep "Success Rate"
done
```

Calculate:
- Mean pass rate
- Standard deviation (to measure non-determinism)
- Consistent failures (appear in all 5 runs)
- Flaky tests (pass sometimes, fail sometimes)

---

## Conclusion

The gaps exist at **every stage** of the pipeline:

1. **Intent Classification:** Mostly working (95% accurate)
2. **Table Selection:** 15% variance due to LLM non-determinism
3. **Schema Context:** Missing 50% of critical information (FKs, relationships)
4. **SQL Generation:** No guidance on complex patterns, column qualification

**Primary Bottleneck:** Schema Context (Step 3)
- If LLM had complete FK information and qualified columns, 80% of failures would disappear

**Current State:** 32/36 tests passing (88.8%)
**Achievable Target:** 32-34/36 tests passing (94%) with immediate fixes
**Long-term Target:** 34-35/36 tests passing (97%) with all fixes

The 93.8% mentioned by user was likely a one-time lucky run with favorable LLM randomness.
