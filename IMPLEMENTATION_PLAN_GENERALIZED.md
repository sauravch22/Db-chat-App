# SQL Generation Performance Improvement - Generalized Implementation Plan

**Goal:** Build a database-agnostic SQL generation system (35% → 85-90% pass rate)  
**Key Principle:** Query actual database constraints, don't hardcode  
**Timeline:** 5-6 days  
**Approach:** Dynamic introspection + adaptive prompting

---

## Why the Previous Plan Failed

The original plan hardcoded:
- ❌ Chinook-specific relationship maps
- ❌ Hardcoded column names (customer_id, track_id, etc.)
- ❌ Hardcoded JOIN examples
- ❌ Specific table names in few-shot examples

**Problem:** This approach breaks on day 1 when user connects a different database.

**Real Solution:** Query the actual database schema at runtime, build prompts dynamically.

---

## Core Philosophy: "Let the Database Tell Us the Rules"

Instead of hardcoding patterns, we:
1. **Query information_schema** to get actual FKs, constraints, data types
2. **Build dynamic schema context** based on selected tables
3. **Adapt prompts** to each specific database's capabilities
4. **Learn patterns** from actual database structure, not assumptions

---

## Phase 1: Dynamic Foreign Key Introspection (Day 1)
**Expected Impact:** Fixes 25% of failures (wrong column assumptions)  
**Effort:** Medium  
**Priority:** 🔴 CRITICAL

### Task 1.1: Create Database-Agnostic FK Query Function

**File:** `app/services/schema_service.py`  
**Method:** Create new method `get_foreign_keys()`  
**Database Support:** PostgreSQL, MySQL, SQL Server

```python
async def get_foreign_keys(self, engine, database_name: str) -> Dict[str, Dict[str, str]]:
    """
    Query actual foreign key constraints from the database.
    Returns structure:
    {
        "table_name": {
            "column_name": {
                "references_table": "ref_table",
                "references_column": "ref_column",
                "constraint_name": "fk_name"
            }
        }
    }
    
    Works on: PostgreSQL, MySQL (8.0+), SQL Server
    """
    
    db_type = self.detect_database_type(engine)
    
    if db_type == "postgresql":
        query = """
        SELECT
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name,
            tc.constraint_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = 'public'
        ORDER BY tc.table_name, kcu.column_name;
        """
    
    elif db_type == "mysql":
        query = """
        SELECT
            TABLE_NAME,
            COLUMN_NAME,
            REFERENCED_TABLE_NAME,
            REFERENCED_COLUMN_NAME,
            CONSTRAINT_NAME
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
            AND REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY TABLE_NAME, COLUMN_NAME;
        """
    
    elif db_type == "sql_server":
        query = """
        SELECT
            fk.constraint_name,
            OBJECT_NAME(fk.parent_object_id) AS table_name,
            c1.name AS column_name,
            OBJECT_NAME(fk.referenced_object_id) AS foreign_table_name,
            c2.name AS foreign_column_name
        FROM sys.foreign_keys AS fk
        JOIN sys.columns AS c1
            ON fk.parent_object_id = c1.object_id
            AND fk.parent_column_id = c1.column_id
        JOIN sys.columns AS c2
            ON fk.referenced_object_id = c2.object_id
            AND fk.referenced_column_id = c2.column_id
        ORDER BY table_name, column_name;
        """
    
    async with engine.connect() as conn:
        result = await conn.execute(text(query))
        rows = result.fetchall()
    
    # Normalize results into consistent structure
    fk_map = {}
    for row in rows:
        if db_type == "postgresql":
            table, col, ref_table, ref_col, constraint = row
        elif db_type == "mysql":
            table, col, ref_table, ref_col, constraint = row
        elif db_type == "sql_server":
            constraint, table, col, ref_table, ref_col = row
        
        if table not in fk_map:
            fk_map[table] = {}
        
        fk_map[table][col] = {
            "references_table": ref_table,
            "references_column": ref_col,
            "constraint_name": constraint
        }
    
    return fk_map


def detect_database_type(self, engine) -> str:
    """Detect database type from connection string"""
    dialect = engine.dialect.name.lower()
    return dialect  # Returns: "postgresql", "mysql", "mssql"
```

---

### Task 1.2: Create Multi-Hop Path Finder

**File:** `app/services/schema_service.py`  
**Method:** Create new method `find_join_paths()`

```python
async def find_join_paths(
    self,
    engine,
    from_table: str,
    to_table: str,
    max_hops: int = 4
) -> Optional[List[str]]:
    """
    Find shortest path from one table to another using FK relationships.
    
    Example:
    find_join_paths(engine, "artist", "invoice_line")
    → ["artist", "album", "track", "invoice_line"]
    
    Uses BFS to find minimum hops, avoiding cycles.
    """
    
    # Get all FK relationships
    all_fks = await self.get_foreign_keys(engine)
    
    # Build adjacency list (both directions)
    graph = {}
    for table in all_fks:
        if table not in graph:
            graph[table] = []
        for col, fk_info in all_fks[table].items():
            ref_table = fk_info["references_table"]
            if ref_table not in graph:
                graph[ref_table] = []
            
            # Add both directions (can join via FK or reverse FK)
            graph[table].append(ref_table)
            graph[ref_table].append(table)
    
    # BFS to find shortest path
    from collections import deque
    
    if from_table not in graph:
        return None
    
    queue = deque([(from_table, [from_table])])
    visited = {from_table}
    
    while queue:
        current, path = queue.popleft()
        
        if current == to_table:
            return path
        
        if len(path) > max_hops:
            continue
        
        for neighbor in graph.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    
    return None  # No path found


async def get_join_path_details(
    self,
    engine,
    path: List[str]
) -> List[Dict[str, str]]:
    """
    Given a path like ["artist", "album", "track"],
    return the JOIN conditions needed.
    
    Returns:
    [
        {
            "from_table": "artist",
            "to_table": "album",
            "condition": "artist.artist_id = album.artist_id",
            "fk_column": "artist_id",
            "ref_column": "artist_id"
        }
    ]
    """
    
    all_fks = await self.get_foreign_keys(engine)
    join_details = []
    
    for i in range(len(path) - 1):
        from_table = path[i]
        to_table = path[i + 1]
        
        # Find FK relationship between these tables
        condition = None
        fk_col = None
        ref_col = None
        
        # Check forward relationship
        if from_table in all_fks and any(
            fk["references_table"] == to_table for fk in all_fks[from_table].values()
        ):
            for col, fk_info in all_fks[from_table].items():
                if fk_info["references_table"] == to_table:
                    fk_col = col
                    ref_col = fk_info["references_column"]
                    condition = f"{from_table}.{fk_col} = {to_table}.{ref_col}"
                    break
        
        # Check reverse relationship
        elif to_table in all_fks and any(
            fk["references_table"] == from_table for fk in all_fks[to_table].values()
        ):
            for col, fk_info in all_fks[to_table].items():
                if fk_info["references_table"] == from_table:
                    fk_col = col
                    ref_col = fk_info["references_column"]
                    condition = f"{to_table}.{fk_col} = {from_table}.{ref_col}"
                    break
        
        if condition:
            join_details.append({
                "from_table": from_table,
                "to_table": to_table,
                "condition": condition,
                "fk_column": fk_col,
                "ref_column": ref_col
            })
    
    return join_details
```

---

### Task 1.3: Cache FK Information at Connection Time

**File:** `app/services/metadata_service.py`  
**Method:** Modify or create `__init__` / connection initialization

```python
class MetadataService:
    def __init__(self, schema_service):
        self.schema_service = schema_service
        self.fk_cache = {}  # {connection_id: fk_info}
        self.path_cache = {}  # {(conn_id, from_table, to_table): path}
    
    async def initialize_connection(self, connection_id: int, engine):
        """
        Cache FK information when user connects a database.
        Called once per connection.
        """
        if connection_id in self.fk_cache:
            return  # Already cached
        
        try:
            print(f"[FK INTROSPECTION] Analyzing FK constraints for connection {connection_id}...")
            fks = await self.schema_service.get_foreign_keys(engine)
            self.fk_cache[connection_id] = fks
            print(f"[FK INTROSPECTION] Found FKs for {len(fks)} tables")
        except Exception as e:
            print(f"[WARNING] Could not introspect FKs: {e}")
            self.fk_cache[connection_id] = {}
    
    async def get_cached_fks(self, connection_id: int) -> Dict:
        """Retrieve cached FK information"""
        return self.fk_cache.get(connection_id, {})
    
    async def find_path_between_tables(
        self,
        connection_id: int,
        engine,
        from_table: str,
        to_table: str
    ) -> Optional[List[str]]:
        """
        Find path between tables, using cache if available.
        Caches result to avoid repeated searches.
        """
        cache_key = (connection_id, from_table, to_table)
        if cache_key in self.path_cache:
            return self.path_cache[cache_key]
        
        path = await self.schema_service.find_join_paths(engine, from_table, to_table)
        if path:
            self.path_cache[cache_key] = path
        
        return path
```

---

### Task 1.4: Modify Schema Context to Include Real FKs

**File:** `app/services/metadata_service.py`  
**Method:** Update `get_column_schema()`

```python
async def get_column_schema(
    self,
    connection_id: int,
    table_names: List[str],
    engine
) -> str:
    """
    Build schema context using ACTUAL database constraints.
    """
    
    # Get actual FK information
    fk_info = await self.get_cached_fks(connection_id)
    if not fk_info:
        # Fallback to pattern-based inference if FKs not cached
        fk_info = {}
    
    schema_info = ""
    
    for table_name in table_names:
        schema_info += f"\n=== TABLE: {table_name} ===\n"
        
        # Get columns
        columns = await self.schema_service.get_columns(table_name, connection_id)
        
        # Build column list WITH table prefixes
        schema_info += "COLUMNS:\n"
        for col in columns:
            col_type = str(col.data_type).upper()
            col_info = f"  {table_name}.{col.name} : {col_type}"
            
            # Add constraints from actual database
            constraints = []
            if col.primary_key:
                constraints.append("PRIMARY KEY")
            if not col.nullable:
                constraints.append("NOT NULL")
            
            if constraints:
                col_info += f" [{', '.join(constraints)}]"
            
            schema_info += col_info + "\n"
        
        # Add ACTUAL foreign keys
        if table_name in fk_info and fk_info[table_name]:
            schema_info += "\nFOREIGN KEYS (from actual DB):\n"
            for col_name, fk_data in fk_info[table_name].items():
                ref_table = fk_data["references_table"]
                ref_col = fk_data["references_column"]
                schema_info += f"  {table_name}.{col_name} → {ref_table}.{ref_col}\n"
        
        # Add multi-hop paths to OTHER selected tables
        schema_info += "\nJOIN PATHS TO OTHER SELECTED TABLES:\n"
        for other_table in table_names:
            if other_table != table_name:
                path = await self.find_path_between_tables(
                    connection_id, engine, table_name, other_table
                )
                if path:
                    join_details = await self.schema_service.get_join_path_details(engine, path)
                    schema_info += f"  To {other_table}: "
                    
                    # Format the path
                    if len(path) == 2:
                        # Direct join
                        condition = join_details[0]["condition"]
                        schema_info += f"{condition}\n"
                    else:
                        # Multi-hop
                        path_str = " → ".join(path)
                        conditions = " AND ".join([j["condition"] for j in join_details])
                        schema_info += f"{path_str}\n    ({conditions})\n"
    
    return schema_info
```

**Example Output (Auto-Generated for Any Database):**
```
=== TABLE: artist ===
COLUMNS:
  artist.artist_id : INTEGER [PRIMARY KEY, NOT NULL]
  artist.name : VARCHAR(120) [NOT NULL]

=== TABLE: album ===
COLUMNS:
  album.album_id : INTEGER [PRIMARY KEY, NOT NULL]
  album.title : VARCHAR(160) [NOT NULL]
  album.artist_id : INTEGER [NOT NULL]

FOREIGN KEYS (from actual DB):
  album.artist_id → artist.artist_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To artist: album.artist_id = artist.artist_id

=== TABLE: track ===
COLUMNS:
  track.track_id : INTEGER [PRIMARY KEY, NOT NULL]
  track.name : VARCHAR(200) [NOT NULL]
  track.album_id : INTEGER [NOT NULL]
  track.genre_id : INTEGER [NOT NULL]

FOREIGN KEYS (from actual DB):
  track.album_id → album.album_id
  track.genre_id → genre.genre_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To artist: album → artist
    (track.album_id = album.album_id AND album.artist_id = artist.artist_id)
  To album: track.album_id = album.album_id
```

---

### Task 1.5: Validation After Phase 1

**Commands:**
```bash
# Test with Chinook (existing)
for i in {1..3}; do
    echo "=== Phase 1 Validation - Chinook - Run $i ==="
    bash /tmp/dbchat_comprehensive_test.sh 2>&1 | grep -E "Test #|Success Rate"
    sleep 5
done

# Test with different schema (create simple test schema)
# This validates generalization
bash /tmp/test_with_alternate_schema.sh
```

**Success Criteria:**
- ✅ At least 10/20 tests passing (50%)
- ✅ FK info shows actual DB constraints, not guesses
- ✅ Multi-hop paths correctly calculated
- ✅ Works on PostgreSQL, MySQL, SQL Server (if available)

**If Not Met:**
- Check FK query works for your specific DB version
- Verify all_fks dict populated correctly
- Debug path-finding algorithm with print statements

---

## Phase 2: Database-Aware Prompt Generation (Day 2-3)
**Expected Impact:** +5 tests → 65-70% pass rate  
**Effort:** Medium  
**Priority:** 🔴 CRITICAL

### Task 2.1: Create Adaptive System Prompt Generator

**File:** `app/services/ollama_service.py`  
**Method:** Create new method `build_adaptive_system_prompt()`

```python
async def build_adaptive_system_prompt(
    self,
    db_type: str,
    schema_context: str,
    selected_tables: List[str]
) -> str:
    """
    Generate database-aware system prompt.
    
    Adapts rules based on:
    - Database type (PostgreSQL vs MySQL vs SQL Server have different syntax)
    - Selected tables (only reference tables in current query)
    - Actual schema structure (not hardcoded patterns)
    """
    
    # Base rules (universal)
    base_rules = """You are a SQL expert. Your job is to write correct SQL queries.

CRITICAL RULES (ALL DATABASES):
1. Output ONLY the SQL query, nothing else
2. Do NOT explain, do NOT say "Here is the SQL"
3. ONLY return SELECT queries
4. ALWAYS qualify column names with table names (table.column)
5. Only use columns/tables provided in the schema context below
6. Test each JOIN condition in your head before writing it
"""
    
    # Database-specific syntax rules
    db_specific = ""
    
    if db_type.lower() == "postgresql":
        db_specific = """
DATABASE SPECIFIC - PostgreSQL:
7. Use double quotes for identifiers: "table_name"."column_name"
8. String literals use single quotes: 'value'
9. NEVER nest aggregate functions: AVG(SUM(...)) is INVALID
10. Use subqueries for nested aggregates:
    SELECT AVG(subtotal) FROM (SELECT SUM(amount) AS subtotal FROM ...) sub
11. Window functions (OVER clause) only in SELECT and ORDER BY, never in WHERE/HAVING
12. Use CREATE TEMPORARY TABLE or WITH clauses for complex subqueries
13. CASE statements work in any clause
14. COALESCE() handles NULL values
"""
    
    elif db_type.lower() == "mysql":
        db_specific = """
DATABASE SPECIFIC - MySQL:
7. Use backticks for identifiers: `table_name`.`column_name`
8. Or no quotes if identifier is simple: table_name.column_name
9. String literals use single quotes: 'value'
10. NEVER nest aggregate functions: AVG(SUM(...)) is INVALID
11. Window functions require MySQL 8.0+ and use OVER clause
12. Use subqueries with aliases: FROM (...) AS subquery_name
13. IFNULL() or COALESCE() for NULL handling
14. GROUP_CONCAT() for string aggregation
"""
    
    elif db_type.lower() in ["mssql", "sql_server"]:
        db_specific = """
DATABASE SPECIFIC - SQL Server:
7. Use square brackets for identifiers: [table_name].[column_name]
8. Or double quotes: "table_name"."column_name"
9. String literals use single quotes: 'value'
10. NEVER nest aggregate functions
11. Window functions (OVER, PARTITION BY) are fully supported
12. Use CTEs (WITH clause) extensively - they're optimized
13. ISNULL() or COALESCE() for NULL handling
14. Use CTE for recursive queries or complex logic
"""
    
    # Generic pattern rules (no hardcoded examples)
    pattern_rules = """
GENERIC SQL PATTERNS YOU MIGHT NEED:

For "average of aggregates" (common pattern):
- First aggregate in subquery: SELECT column, SUM(amount) AS total FROM ... GROUP BY column
- Then average in outer: SELECT AVG(total) FROM (...) sub

For filtering by aggregate:
- Use HAVING clause after GROUP BY
- Or use subquery in WHERE with IN/EXISTS

For multi-table queries:
- Find the JOIN path in the schema context
- Always write the full condition: table1.col = table2.col
- Check if you need LEFT JOIN (to keep unmatched rows) or INNER JOIN (only matches)

For top N per group:
- Use window function: ROW_NUMBER() OVER (PARTITION BY group ORDER BY sort_col)
- Wrap in subquery, then filter WHERE rn <= N
"""
    
    # Build final prompt
    full_prompt = base_rules + "\n" + db_specific + "\n" + pattern_rules
    
    full_prompt += f"\n\nSELECTED TABLES FOR THIS QUERY: {', '.join(selected_tables)}\n"
    full_prompt += "\nSCHEMA CONTEXT:\n" + schema_context
    
    return full_prompt


async def generate_sql(
    self,
    user_prompt: str,
    schema_context: str,
    selected_tables: List[str],
    db_type: str,  # NEW PARAMETER
    error_context: Optional[str] = None
) -> str:
    """
    Generate SQL with database-aware prompt.
    """
    
    # Build adaptive prompt (not hardcoded)
    system_prompt = await self.build_adaptive_system_prompt(
        db_type=db_type,
        schema_context=schema_context,
        selected_tables=selected_tables
    )
    
    # Include error context if provided (repair case)
    if error_context:
        system_prompt += f"\n\nPREVIOUS ATTEMPT FAILED:\n{error_context}"
    
    # Call Mistral with adaptive prompt
    response = await client.post(
        f"{self.base_url}/api/generate",
        json={
            "model": "mistral",
            "prompt": f"{system_prompt}\n\nUser Question: {user_prompt}\n\nSQL:",
            "temperature": 0.0,
            "top_p": 0.9,
            "stream": False
        }
    )
    
    result = response.json()
    sql = result.get("response", "").strip()
    
    return sql
```

---

### Task 2.2: Update ChatService to Pass DB Type

**File:** `app/services/chat_service.py`  
**Method:** Modify `process_user_prompt()`

```python
# BEFORE SQL generation, add:

# Get database type for adaptive prompting
db_engine = self.get_engine(connection_id)
db_type = db_engine.dialect.name  # "postgresql", "mysql", "mssql"

# THEN pass to generate_sql:
sql_query = await self.ollama.generate_sql(
    user_prompt=user_prompt,
    schema_context=schema_context,
    selected_tables=table_names,
    db_type=db_type,  # NEW
    error_context=None
)
```

---

### Task 2.3: Validation After Phase 2

**Commands:**
```bash
# Run tests - should see improvement from column qualification
for i in {1..3}; do
    echo "=== Phase 2 Validation - Run $i ==="
    bash /tmp/dbchat_comprehensive_test.sh 2>&1 | grep -E "Test #|Success Rate"
    sleep 5
done

# Expected: 13-15/20 tests passing (65-75%)
```

**Success Criteria:**
- ✅ At least 13/20 tests passing
- ✅ All columns showing table-qualified names
- ✅ Correct FK relationships from actual database
- ✅ No hardcoded Chinook-specific patterns in output

---

## Phase 3: Intelligent Error Recovery (Day 3-4)
**Expected Impact:** +2 tests → 75-80% pass rate  
**Effort:** Medium  
**Priority:** 🟡 MEDIUM

### Task 3.1: Create Error Parser (Database-Aware)

**File:** `app/services/error_parser.py` (NEW FILE)

```python
"""
Parse SQL errors and provide context-aware repair hints.
Works across PostgreSQL, MySQL, SQL Server.
"""

from dataclasses import dataclass
from typing import Optional

@dataclass
class ParsedError:
    error_type: str  # "ambiguous_column", "missing_column", "syntax", etc.
    error_message: str
    affected_element: Optional[str]  # Column/table name if extractable
    repair_hint: str
    database_type: str


class ErrorParser:
    
    @staticmethod
    def parse(error_message: str, database_type: str) -> ParsedError:
        """
        Parse database error into actionable repair hint.
        """
        error_lower = error_message.lower()
        
        # PostgreSQL errors
        if "ambiguous column reference" in error_lower:
            column = ErrorParser._extract_quoted_identifier(error_message)
            return ParsedError(
                error_type="ambiguous_column",
                error_message=error_message,
                affected_element=column,
                repair_hint=f"Column '{column}' appears in multiple tables. Qualify it: table_name.{column}",
                database_type=database_type
            )
        
        elif "column" in error_lower and "does not exist" in error_lower:
            column = ErrorParser._extract_quoted_identifier(error_message)
            return ParsedError(
                error_type="missing_column",
                error_message=error_message,
                affected_element=column,
                repair_hint=f"Column '{column}' doesn't exist. Check schema context. May need to JOIN to another table.",
                database_type=database_type
            )
        
        elif "aggregate function calls cannot be nested" in error_lower:
            return ParsedError(
                error_type="nested_aggregate",
                error_message=error_message,
                affected_element=None,
                repair_hint="Nested aggregates (e.g., AVG(SUM(...))) not allowed. Move inner aggregate to subquery.",
                database_type=database_type
            )
        
        elif "window function" in error_lower and ("where" in error_lower or "having" in error_lower):
            return ParsedError(
                error_type="window_in_filter",
                error_message=error_message,
                affected_element=None,
                repair_hint="Window functions can't be in WHERE/HAVING. Move to subquery.",
                database_type=database_type
            )
        
        elif "syntax error" in error_lower:
            return ParsedError(
                error_type="syntax_error",
                error_message=error_message,
                affected_element=None,
                repair_hint="SQL syntax error. Check: parentheses matched, commas between columns, valid keywords.",
                database_type=database_type
            )
        
        elif "relation" in error_lower and "does not exist" in error_lower:
            table = ErrorParser._extract_quoted_identifier(error_message)
            return ParsedError(
                error_type="missing_table",
                error_message=error_message,
                affected_element=table,
                repair_hint=f"Table '{table}' doesn't exist. Check exact table name in schema context.",
                database_type=database_type
            )
        
        # MySQL errors
        elif "unknown column" in error_lower:
            column = ErrorParser._extract_quoted_identifier(error_message)
            return ParsedError(
                error_type="missing_column",
                error_message=error_message,
                affected_element=column,
                repair_hint=f"Column '{column}' doesn't exist. Check schema context.",
                database_type=database_type
            )
        
        elif "you have an error in your sql syntax" in error_lower:
            return ParsedError(
                error_type="syntax_error",
                error_message=error_message,
                affected_element=None,
                repair_hint="MySQL syntax error. Check backticks, quotes, and keyword spelling.",
                database_type=database_type
            )
        
        # SQL Server errors
        elif "invalid column name" in error_lower:
            column = ErrorParser._extract_quoted_identifier(error_message)
            return ParsedError(
                error_type="missing_column",
                error_message=error_message,
                affected_element=column,
                repair_hint=f"Column '{column}' doesn't exist in the specified table.",
                database_type=database_type
            )
        
        elif "ambiguous column name" in error_lower:
            column = ErrorParser._extract_quoted_identifier(error_message)
            return ParsedError(
                error_type="ambiguous_column",
                error_message=error_message,
                affected_element=column,
                repair_hint=f"Column '{column}' is ambiguous. Use table alias: [table].[{column}]",
                database_type=database_type
            )
        
        # Generic fallback
        return ParsedError(
            error_type="unknown",
            error_message=error_message,
            affected_element=None,
            repair_hint="Query failed. Review error and schema context carefully. Check JOIN conditions and column names.",
            database_type=database_type
        )
    
    @staticmethod
    def _extract_quoted_identifier(error_message: str) -> Optional[str]:
        """Extract quoted column/table name from error message"""
        import re
        
        # Try PostgreSQL format: "column_name"
        match = re.search(r'"([^"]+)"', error_message)
        if match:
            return match.group(1)
        
        # Try MySQL format: `column_name`
        match = re.search(r'`([^`]+)`', error_message)
        if match:
            return match.group(1)
        
        # Try simple format
        match = re.search(r"'([^']+)'", error_message)
        if match:
            return match.group(1)
        
        return None
```

---

### Task 3.2: Enhance Repair Logic with Parsed Errors

**File:** `app/services/chat_service.py`  
**Method:** Update SQL execution error handling

```python
from app.services.error_parser import ErrorParser

# In process_user_prompt(), replace generic error handling with:

try:
    result = await execute_sql(sql_query, engine)
    
except Exception as sql_error:
    error_text = str(sql_error)
    
    # Parse error to understand what failed
    parsed = ErrorParser.parse(error_text, db_type)
    
    print(f"[ERROR] {parsed.error_type}: {parsed.repair_hint}")
    
    if parsed.error_type in ["ambiguous_column", "missing_column", "nested_aggregate", "window_in_filter"]:
        # These are worth repairing
        
        repair_context = f"""
PREVIOUS SQL FAILED:
{sql_query}

ERROR: {parsed.error_type}
MESSAGE: {parsed.error_message}

REPAIR INSTRUCTION:
{parsed.repair_hint}

Generate corrected SQL following the instruction above.
Database type: {db_type}
"""
        
        # Try repair with explicit guidance
        repaired_sql = await self.ollama.generate_sql(
            user_prompt=user_prompt,
            schema_context=schema_context,
            selected_tables=table_names,
            db_type=db_type,
            error_context=repair_context
        )
        
        if repaired_sql and repaired_sql != sql_query:
            print(f"[REPAIR] Attempting: {repaired_sql[:100]}")
            try:
                result = await execute_sql(repaired_sql, engine)
                # Success!
            except Exception as repair_error:
                # Second attempt failed
                return {"error": f"Repair failed: {str(repair_error)[:200]}"}
        else:
            return {"error": f"Could not repair: {parsed.repair_hint}"}
    else:
        # Generic errors - less likely to repair successfully
        return {"error": f"SQL error: {error_text[:200]}"}
```

---

### Task 3.3: Validation After Phase 3

```bash
for i in {1..3}; do
    echo "=== Phase 3 Validation - Run $i ==="
    bash /tmp/dbchat_comprehensive_test.sh 2>&1 | grep -E "Test #|Success Rate"
    sleep 5
done

# Expected: 15-16/20 tests passing (75-80%)
```

---

## Phase 4: Database-Aware Query Validation (Day 4-5)
**Expected Impact:** +1 test → 80-85% pass rate  
**Effort:** Low-Medium  
**Priority:** 🟢 MEDIUM

### Task 4.1: Create Database-Specific Validation

**File:** `app/services/query_validator.py` (NEW FILE)

```python
"""
Validate queries before execution using database-specific logic.
"""

class QueryValidator:
    
    @staticmethod
    async def validate(sql: str, engine, db_type: str) -> tuple[bool, Optional[str]]:
        """
        Validate SQL query using EXPLAIN or equivalent.
        Returns (is_valid, error_message).
        """
        
        db_type = db_type.lower()
        
        try:
            async with engine.connect() as conn:
                if db_type == "postgresql":
                    # PostgreSQL: EXPLAIN shows query plan
                    await conn.execute(text(f"EXPLAIN {sql}"))
                
                elif db_type == "mysql":
                    # MySQL: EXPLAIN EXTENDED for more detail
                    await conn.execute(text(f"EXPLAIN EXTENDED {sql}"))
                
                elif db_type in ["mssql", "sql_server"]:
                    # SQL Server: SET STATISTICS IO for validation
                    # Or just try parsing with sp_prepare
                    await conn.execute(text(f"SET ARITHABORT ON; {sql}"))
            
            return True, None
        
        except Exception as e:
            return False, str(e)
    
    @staticmethod
    def detect_complexity(sql: str) -> dict:
        """
        Analyze query complexity to estimate execution time.
        """
        sql_upper = sql.upper()
        
        complexity = {
            "has_joins": "JOIN" in sql_upper,
            "join_count": sql_upper.count("JOIN"),
            "has_subqueries": "SELECT" in sql_upper.count("(SELECT"),
            "has_aggregate": any(f in sql_upper for f in ["COUNT", "SUM", "AVG", "MIN", "MAX"]),
            "has_group_by": "GROUP BY" in sql_upper,
            "has_window": "OVER" in sql_upper,
            "is_complex": False
        }
        
        # Mark as complex if multiple expensive operations
        complexity["is_complex"] = (
            complexity["join_count"] > 3 or
            complexity["has_subqueries"] > 2 or
            (complexity["has_window"] and complexity["join_count"] > 2)
        )
        
        return complexity
```

---

### Task 4.2: Add Pre-Execution Validation to ChatService

**File:** `app/services/chat_service.py`

```python
from app.services.query_validator import QueryValidator

# Before executing SQL:

print(f"[VALIDATION] Checking SQL syntax...")
is_valid, error = await QueryValidator.validate(sql_query, engine, db_type)

if not is_valid:
    print(f"[VALIDATION FAILED] {error[:100]}")
    
    # Attempt repair before wasting time on execution
    parsed = ErrorParser.parse(error, db_type)
    repair_context = f"Query validation failed: {parsed.repair_hint}"
    
    sql_query = await self.ollama.generate_sql(
        user_prompt=user_prompt,
        schema_context=schema_context,
        selected_tables=table_names,
        db_type=db_type,
        error_context=repair_context
    )
    
    # Re-validate
    is_valid, error = await QueryValidator.validate(sql_query, engine, db_type)
    if not is_valid:
        return {"error": f"Generated invalid SQL: {error[:200]}"}

print(f"[VALIDATION] Query is valid, executing...")
result = await execute_sql(sql_query, engine)
```

---

## Phase 5: Database-Agnostic Optimization (Day 5-6)
**Expected Impact:** +2 tests → 85-90% pass rate  
**Effort:** Low  
**Priority:** 🟢 LOW

### Task 5.1: Add Database-Specific Query Hints

**File:** `app/services/ollama_service.py`  
**Method:** Add to `build_adaptive_system_prompt()`

```python
# After pattern rules, add optimization rules based on db_type:

if db_type.lower() == "postgresql":
    optimization_rules = """
PERFORMANCE - PostgreSQL:
- Use EXPLAIN ANALYZE to check query plans
- Indexes on FK columns are critical
- CTEs (WITH clause) are optimized well
- Use LIMIT for result limiting
- UNION ALL is faster than UNION
"""

elif db_type.lower() == "mysql":
    optimization_rules = """
PERFORMANCE - MySQL:
- Use LIMIT to prevent large result sets
- JOIN order matters - put tables with fewer rows first
- Use index hints if needed: JOIN table USE INDEX (index_name)
- UNION ALL faster than UNION
- Avoid correlated subqueries, use JOIN instead
"""

elif db_type.lower() in ["mssql", "sql_server"]:
    optimization_rules = """
PERFORMANCE - SQL Server:
- CTEs are highly optimized
- Window functions are well-optimized
- Table hints: WITH (NOLOCK) can speed up queries
- Use TOP N instead of LIMIT
- Avoid functions in WHERE clause filters
"""

return base_rules + db_specific + pattern_rules + optimization_rules
```

---

### Task 5.2: Add Result Set Limiting (Database-Aware)

**File:** `app/services/chat_service.py`

```python
def add_result_limit(sql: str, limit: int, db_type: str) -> str:
    """
    Add result limit appropriate to database type.
    """
    sql_upper = sql.upper()
    
    # Skip if already has LIMIT
    if "LIMIT" in sql_upper or "TOP" in sql_upper:
        return sql
    
    # Skip aggregate queries (usually return few rows)
    if any(kw in sql_upper for kw in ["COUNT(*)", "SUM(", "AVG(", "MAX(", "MIN(", "GROUP BY"]):
        return sql
    
    sql = sql.rstrip(";")
    
    if db_type.lower() in ["mssql", "sql_server"]:
        # SQL Server uses TOP
        return f"SELECT TOP {limit} * FROM ({sql}) result_limit"
    else:
        # PostgreSQL and MySQL use LIMIT
        return f"{sql} LIMIT {limit};"

# Use before execution:
sql_query = add_result_limit(sql_query, limit=1000, db_type=db_type)
```

---

### Task 5.3: Increase Timeout for Complex Queries

**File:** `app/services/chat_service.py`

```python
# Before executing query:

complexity = QueryValidator.detect_complexity(sql_query)

if complexity["is_complex"]:
    timeout = 120  # seconds
    print(f"[TIMEOUT] Complex query detected, using {timeout}s timeout")
else:
    timeout = 60  # seconds

result = await execute_sql_with_timeout(sql_query, engine, timeout)
```

---

## Implementation Checklist - Generalized Approach

### Phase 1: Dynamic FK Introspection ✅
- [ ] Task 1.1: Create `get_foreign_keys()` for PostgreSQL/MySQL/SQL Server
- [ ] Task 1.2: Create `find_join_paths()` using BFS on FK graph
- [ ] Task 1.3: Cache FK info at connection initialization
- [ ] Task 1.4: Update schema context to use actual FKs + multi-hop paths
- [ ] Task 1.5: Validate (expect 50% pass rate)

### Phase 2: Adaptive Prompt Generation ✅
- [ ] Task 2.1: Create `build_adaptive_system_prompt()` with DB-specific rules
- [ ] Task 2.2: Update `generate_sql()` to accept db_type parameter
- [ ] Task 2.3: Update ChatService to pass db_type
- [ ] Task 2.4: Validation (expect 65-75% pass rate)

### Phase 3: Intelligent Error Recovery ✅
- [ ] Task 3.1: Create `ErrorParser` class (works across DB types)
- [ ] Task 3.2: Replace generic repair with parsed error repair
- [ ] Task 3.3: Validation (expect 75-80% pass rate)

### Phase 4: Query Validation ✅
- [ ] Task 4.1: Create `QueryValidator` with DB-specific validation
- [ ] Task 4.2: Add pre-execution validation to ChatService
- [ ] Task 4.3: Validation (expect 80-85% pass rate)

### Phase 5: Database-Aware Optimization ✅
- [ ] Task 5.1: Add DB-specific optimization hints to prompt
- [ ] Task 5.2: Add DB-aware result limiting
- [ ] Task 5.3: Scale timeouts based on query complexity
- [ ] Task 5.4: Validation (expect 85-90% pass rate)

---

## Key Differences From Previous Plan

| Aspect | Previous Plan | Generalized Plan |
|--------|---------------|------------------|
| **FK Information** | Hardcoded relationship map | Query information_schema dynamically |
| **Table Examples** | Chinook-specific queries | Database-agnostic patterns |
| **Column Names** | Hardcoded (customer_id, artist_id) | Discovered from actual schema |
| **JOIN Paths** | Manual (artist→album→track) | Computed dynamically with BFS |
| **DB Differences** | Ignored | Detected and adapted to (PostgreSQL/MySQL/SQL Server) |
| **Scalability** | Breaks on new schema | Works on any schema |
| **Maintenance** | Add new hardcoded rules per schema | No changes needed for new schemas |

---

## How This Scales

**Today:** Connect Chinook → FK introspection finds all relationships → System learns them → Prompts adapt

**Tomorrow:** Connect Northwind (or any database) → FK introspection finds ITS relationships → Prompts adapt automatically

**Next Week:** Connect your company database → Same system works without code changes

---

## Testing Strategy

**Phase 1-3:** Test with Chinook (expected improvement)

**Phase 4+:** Test with alternate schema:
```bash
# Create simple test database
psql -c "CREATE DATABASE test_db"
psql -d test_db -f /tmp/test_schema.sql

# Run tests against it
# Should achieve similar pass rate (proving generalization works)
```

---

## Success Metrics

### Generalization Success:
- ✅ Same test suite passes on PostgreSQL, MySQL, SQL Server
- ✅ Works on schemas with no FK constraints (pattern fallback)
- ✅ Works on schemas with complex FK patterns
- ✅ No Chinook-specific hardcoding in production code

### Performance Targets:
- PostgreSQL: 85-90% pass rate
- MySQL: 85-90% pass rate
- SQL Server: 85-90% pass rate
- Unknown database type: Falls back gracefully (50-60% pass rate)

---

## Emergency Fallback (If Dynamic FK Fails)

If `get_foreign_keys()` fails for a specific database:

```python
# In MetadataService.initialize_connection():

try:
    fks = await self.schema_service.get_foreign_keys(engine)
except Exception as e:
    print(f"[WARNING] FK introspection failed: {e}")
    # Fall back to pattern-based inference
    fks = await self.fallback_infer_fks(engine)
```

The fallback uses the existing pattern-based approach, so the system still works.

---

## Next Steps

1. **Implement Phase 1 first** - This is foundational
   - Get FK introspection working for your databases
   - Cache and validate the FK map
   - Confirm multi-hop paths calculated correctly

2. **Test on Chinook** - Verify improvement from actual FKs

3. **Test on alternate schema** - Prove generalization

4. **Then proceed to Phase 2-5** - Each builds on Phase 1

---

## Questions This Approach Answers

**"Will it work on my company database?"** → Yes, same FK introspection logic applies to any schema

**"What if database has no FK constraints?"** → System falls back to pattern inference, still works

**"What if column names are different?"** → Schema context shows actual column names, LLM sees real data

**"What if we need to support Oracle/SQL Server/PostgreSQL?"** → Add new branch in `get_foreign_keys()` with appropriate query

**"How do we know if it's working?"** → Compare test results before/after each phase; if 4 databases show same improvement, it generalizes

