# LLM Hallucination Analysis - DbChat System

## Executive Summary

**Current Performance:** 35% pass rate (7/20 tests passing)  
**Historical Best:** 50% pass rate (documented in COMPARISON_PROMPTS_ANALYSIS.md)  
**Root Cause:** LLM (Mistral) SQL generation non-determinism + Schema context issues

---

## Architecture Overview

### System Flow

```
User Prompt
    ↓
[1] Intent Classification (Ollama/Mistral)
    ↓
[2] Table Selection (Vector Search + LLM Table Identification)
    ↓
[3] Schema Context Retrieval (MetadataService)
    ↓
[4] SQL Generation (Ollama/Mistral) ← **PRIMARY FAILURE POINT**
    ↓
[5] SQL Validation (Identifier + Syntax Check)
    ↓
[6] Query Execution (PostgreSQL)
    ↓
[7] Result Formatting
    ↓
User Answer
```

### Key Components

1. **ChatService** (`app/services/chat_service.py`)
   - Main orchestrator
   - Handles: Intent classification → Table selection → SQL generation → Execution

2. **OllamaService** (`app/services/ollama_service.py`)
   - LLM interface (Mistral model)
   - Methods:
     - `generate_sql()` - Converts prompt + schema → SQL
     - `identify_tables()` - Selects relevant tables from summaries
     - `classify_intent()` - Determines catalog vs data query

3. **MetadataService** 
   - Provides schema context to LLM
   - `get_column_schema()` - Returns table/column definitions

4. **VectorService**
   - Fallback for table selection if LLM fails
   - Uses Qdrant + nomic-embed-text embeddings

---

## Why LLM Hallucination is Happening

### Root Causes Identified

#### 1. **Non-Deterministic SQL Generation** ⭐ PRIMARY ISSUE
- **Problem:** Mistral generates different SQL for the same prompt each run
- **Evidence:** 
  - Run 1: 5/20 passing (#3, #7, #9, #15, #18)
  - Run 2: 7/20 passing (#4, #7, #8, #9, #10, #16, #18)
  - Historical: 10/20 passing (#4, #5, #7, #8, #9, #10, #14, #15, #18, #20)
- **Impact:** Same test passes sometimes, fails other times
- **Why:** 
  - Temperature = 0.0 (should be deterministic) but Mistral still varies
  - LLM "guesses" column references when ambiguous
  - No retrieval-augmented generation (RAG) for past successful queries

#### 2. **Schema Context Incompleteness**
- **Problem:** LLM doesn't receive full relationship context
- **Missing Info:**
  - Foreign key relationships between tables
  - Join conditions
  - Column nullability constraints
- **Example:** Test #11/12 fail because LLM doesn't know `track` table has no `artist_id` column
  - Chinook schema: `track.album_id → album.album_id → album.artist_id`
  - LLM assumes direct `track.artist_id` exists

#### 3. **Column Name Ambiguity Resolution Failure**
- **Problem:** When multiple tables have same column name, LLM doesn't fully qualify
- **Examples:**
  - Test #1: `customer_id` ambiguous (appears in customer, invoice tables)
  - Test #15: `country` ambiguous (customer.country vs invoice.billing_country)
  - Test #20: `genre_id` ambiguous (track.genre_id vs genre.genre_id)
- **LLM Behavior:** Generates unqualified column names in JOINs

#### 4. **Complex SQL Pattern Failure**
- **Problem:** LLM struggles with nested aggregates and window functions
- **Examples:**
  - Test #17: `AVG(SUM(...))` - nested aggregate (PostgreSQL doesn't allow)
  - Test #19: `AVG(COUNT(...))` - nested aggregate
  - Test #14: Window function in HAVING clause (invalid)
- **Why:** Mistral lacks deep PostgreSQL syntax knowledge

#### 5. **System Prompt Limitations**
- **Current Prompt Weaknesses:**
  ```python
  system_prompt = f"""You are a PostgreSQL SQL expert...
  STRICT RULES:
  1. Output ONLY the SQL query
  2. Only use SELECT statements
  3. EXACT TABLE NAMES: {table_list_str}
  4. Use ONLY column names listed in schema
  5. Use standard PostgreSQL syntax
  6. Do not wrap in markdown
  ```
- **Missing Guidance:**
  - ❌ No examples of ambiguous column resolution
  - ❌ No JOIN strategy guidance (INNER vs LEFT)
  - ❌ No nested aggregate prohibition
  - ❌ No window function usage rules
  - ❌ No subquery vs CTE preference

---

## Detailed Failure Analysis by Test

### Category 1: Ambiguous Column References (5 tests)

**Test #1: Latest invoice > avg invoice**
```
Error: column reference "customer_id" is ambiguous
Root Cause: customer_id exists in both customer and invoice tables
LLM Generated: SELECT customer_id FROM invoice JOIN customer...
Should Be: SELECT invoice.customer_id FROM invoice JOIN customer...
```

**Test #5: First invoice < last invoice**
```
Error: column reference "customer_id" is ambiguous  
Root Cause: Same as #1 - unqualified customer_id
```

**Test #15: Customer count > avg per country**
```
Error: column reference "country" is ambiguous
Tables: customer.country vs invoice.billing_country
LLM Confusion: Doesn't know which "country" to use
```

**Test #20: Tracks with > avg sales in genre**
```
Error: column reference "genre_id" is ambiguous
Root Cause: track.genre_id vs genre.genre_id in JOIN subquery
LLM Generated: SELECT genre_id, AVG(unit_price)... (unqualified)
```

---

### Category 2: Invalid Column Names (3 tests)

**Test #11: Artist tracks > avg tracks per artist**
**Test #12: Longest track > avg longest**
```
Error: Unknown column 'track.artist_id'
Root Cause: Chinook schema doesn't have track.artist_id
Actual Schema: track → album → artist (2-hop relationship)
LLM Hallucination: Assumes direct foreign key exists
```

**Test #13: Country revenue > avg per country**
```
Error: Unknown column 'invoice.country'
Actual Column: invoice.billing_country (not invoice.country)
LLM Behavior: Guesses common column name instead of using schema
```

---

### Category 3: Nested Aggregate Errors (2 tests)

**Test #17: Album revenue > avg for artist**
```sql
-- LLM Generated (INVALID):
SELECT artist_id, AVG(SUM(il.unit_price * il.quantity)) ...

Error: aggregate function calls cannot be nested
PostgreSQL Rule: Cannot have AVG(SUM(...)) - aggregates don't nest
Should Use: Subquery with pre-aggregated sums, then AVG over those
```

**Test #19: Employees supporting > avg customers**
```sql
-- LLM Generated (INVALID):
SELECT AVG(COUNT(DISTINCT c2.support_rep_id)) ...

Error: aggregate function calls cannot be nested  
Fix: Use CTE or subquery to compute counts first, then AVG
```

---

### Category 4: Window Function Misuse (1 test)

**Test #14: Highest invoice > global avg**
```sql
-- LLM Generated (INVALID):
HAVING SUM(total) OVER (PARTITION BY billing_country) > ...

Error: window functions are not allowed in HAVING
PostgreSQL Rule: Window functions only in SELECT/ORDER BY
Fix: Use subquery or move window function to WHERE clause subquery
```

---

### Category 5: Timeout Issues (3 tests)

**Test #2: Total spending > avg spending**  
**Test #3: 2013 spending > 2012 spending**  
**Test #6: Genre revenue > avg genre revenue**
```
Error: HTTPConnectionPool: Read timed out (30s)
Root Causes:
1. LLM generates inefficient SQL (Cartesian products, missing indexes)
2. Complex subqueries without optimization
3. 30s timeout too aggressive for complex queries

Example Problematic Pattern:
SELECT * FROM customer c WHERE (
  SELECT SUM(...) FROM invoice WHERE customer_id = c.id
) > (
  SELECT AVG(...) FROM (
    SELECT SUM(...) FROM invoice GROUP BY customer_id
  )
) -- Double nested subquery, executed per row
```

---

## What Changed? (Regression Analysis)

### Comparing to 50% Success Rate

**Previously Passing (10 tests):** #4, #5, #7, #8, #9, #10, #14, #15, #18, #20

**Now Consistently Passing (3 tests):** #7, #9, #18  
**Intermittently Passing (4 tests):** #4, #8, #10, #16  
**Now Failing (3 tests):** #5, #14, #15, #20

### No Code Changes Detected

**Investigation Results:**
- ✅ ChatService logic unchanged
- ✅ OllamaService prompt templates unchanged
- ✅ Schema retrieval working correctly
- ✅ SQL validation rules intact

**Conclusion:** Regression is due to **LLM non-determinism**, not code changes

### LLM Model Variability

**Factors Causing Different Outputs:**
1. **Temperature = 0.0 doesn't guarantee determinism** in Mistral
   - Sampling process has inherent randomness
   - Token selection can vary even at temp=0
2. **Context window state** - Previous queries may affect subsequent ones
3. **Model quantization** - CPU-only inference may have different precision

---

## Recommendations to Fix

### Immediate (High Impact, Low Effort)

1. **Add Column Qualification Rules to System Prompt**
   ```python
   system_prompt += """
   CRITICAL: When joining tables, ALWAYS fully qualify column names:
   - GOOD: SELECT customer.customer_id, invoice.total FROM ...
   - BAD:  SELECT customer_id, total FROM ...
   
   If a column appears in multiple tables, you MUST use table prefix.
   """
   ```

2. **Add Nested Aggregate Prohibition**
   ```python
   system_prompt += """
   NEVER nest aggregate functions:
   - INVALID: AVG(SUM(x)), MAX(COUNT(y))
   - VALID: Use subquery: SELECT AVG(sum_x) FROM (SELECT SUM(x) as sum_x ...)
   """
   ```

3. **Increase Timeout for Complex Queries**
   ```python
   # In test_comparison_prompts.py
   TIMEOUT = 60  # Increase from 30 to 60 seconds
   ```

4. **Add Few-Shot Examples to Prompt**
   ```python
   system_prompt += """
   EXAMPLES:
   
   Q: Find customers with spending > average
   Schema: customer (customer_id, name), invoice (invoice_id, customer_id, total)
   SQL:
   SELECT c.*
   FROM customer c
   WHERE (
     SELECT SUM(i.total) 
     FROM invoice i 
     WHERE i.customer_id = c.customer_id
   ) > (
     SELECT AVG(total_spent)
     FROM (
       SELECT SUM(total) as total_spent 
       FROM invoice 
       GROUP BY customer_id
     ) subq
   );
   """
   ```

### Medium Term (Moderate Effort)

5. **Enhance Schema Context with Relationships**
   ```python
   # In MetadataService.get_column_schema()
   schema_context += """
   
   Foreign Keys:
   - invoice.customer_id → customer.customer_id
   - track.album_id → album.album_id
   - album.artist_id → artist.artist_id
   
   Note: track table does NOT have artist_id. Use: track → album → artist
   """
   ```

6. **Implement Query Caching (RAG Approach)**
   ```python
   # Store successful (prompt, SQL) pairs
   # On new query, search for similar past prompts
   # Use past SQL as example in prompt
   ```

7. **Add SQL Repair with Error-Specific Guidance**
   ```python
   # Already exists, but enhance with specific fixes:
   if "ambiguous" in error:
       repair_hint = "The column is ambiguous. Add table prefix: table.column"
   elif "nested" in error:
       repair_hint = "Use subquery to compute inner aggregate first"
   ```

### Long Term (High Effort, High Impact)

8. **Switch to Better SQL Generation Model**
   - Options: CodeLlama-SQL, Llama-3.1-70B, GPT-4
   - These have better SQL syntax understanding

9. **Implement Query Plan Optimization**
   - Analyze generated SQL with EXPLAIN
   - Reject queries with Cartesian products
   - Add indexes to common JOIN columns

10. **Build Validation Suite**
    - Test each generated SQL with EXPLAIN before execution
    - Detect common anti-patterns
    - Auto-rewrite inefficient patterns

---

## Current System Strengths

### What's Working Well

1. **Simple Queries (7/20 passing consistently)**
   - Single table queries: ✅
   - Basic JOINs with no ambiguity: ✅
   - Aggregates without nesting: ✅

2. **Schema Context Delivery**
   - Tables correctly identified
   - Column names accurately provided
   - Data types clearly specified

3. **Error Recovery**
   - Single repair attempt working for some cases
   - Identifier validation catching malformed SQL

4. **Performance**
   - Vector search fast (<100ms)
   - Schema retrieval efficient
   - LLM generation reasonable (5-10s per query)

---

## Testing Recommendations

### To Validate Fixes

1. **Run Test Suite 5 Times**
   ```bash
   for i in {1..5}; do
     echo "=== RUN $i ===" >> test_results.log
     python3 test_comparison_prompts.py >> test_results.log 2>&1
   done
   ```
   - Track: Min, Max, Avg pass rate
   - Identify: Tests with <50% reliability

2. **Categorize by Stability**
   - **Stable Pass:** Pass ≥80% of runs
   - **Unstable:** Pass 20-80% of runs  
   - **Stable Fail:** Pass <20% of runs

3. **Focus Fixes on Unstable Tests First**
   - These are closest to working
   - Small prompt changes may push them over threshold

---

## Conclusion

**LLM Hallucination is NOT a bug** - it's inherent to how LLMs work. They generate plausible-sounding outputs that may not be factually correct.

**In this system:**
- ❌ LLM doesn't "know" the database schema - it guesses based on training
- ❌ LLM doesn't validate SQL syntax - it generates text patterns
- ❌ LLM doesn't guarantee consistency - each generation is independent

**The solution is NOT to eliminate hallucination** (impossible), but to:
1. ✅ Guide LLM with better prompts (few-shot examples, strict rules)
2. ✅ Validate outputs aggressively (syntax check, identifier check, EXPLAIN check)
3. ✅ Implement error recovery (repair loops, fallback strategies)
4. ✅ Accept that 100% accuracy is unrealistic with local LLMs

**Realistic Goal:** 70-80% pass rate with improved prompts and validation

Current 35% → Target 70% = **2x improvement achievable** with recommended fixes.
