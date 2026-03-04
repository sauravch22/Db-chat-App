# SQL Generation Performance — Unified Production Plan

**Goal:** Generalized, database-agnostic SQL system (35% → 85-90% pass rate)  
**Key Principle:** Query actual database constraints, store them persistently, no hardcoding  
**Timeline:** 5-6 days  
**Approach:** Introspection at onboarding, persistent storage, adaptive context generation

---

## Critical Issues Fixed From Initial Plan

| Issue | Why It Matters | Our Fix |
|-------|----------------|---------|
| FK cache in-memory only | Breaks in distributed/stateless deployments | Store FKs in database, load once per boot |
| BFS runs at query time | DB query per user request on busy system | Build FK graph once at onboarding, cache in memory |
| `build_adaptive_system_prompt` is async | No I/O happening, false async | Make it synchronous |
| `detect_complexity` bug | Returns int, not bool, confusing code | Fix variable naming and logic |
| `add_result_limit` wrapping | Breaks queries with ORDER BY, corrupts columns | Safer approach: append LIMIT, don't wrap |
| Async/sync SQLAlchemy mismatch | Your codebase uses sync SQLAlchemy + executor | Match existing pattern: use `inspect()`, sync queries |
| Raw information_schema SQL | Fragile across DB versions | Use SQLAlchemy's `inspector.get_foreign_keys()` |

---

## Architecture Overview

```
User Connects Database
    ↓
[Onboarding] Extract schema, FKs, pks → Store in DB models
    ↓
[Per Query] Load FKs from DB → Build FK graph in memory
    ↓
[Table Selection] LLM picks tables
    ↓
[Schema Context] Query DB models → Build context with real FKs + multi-hop paths
    ↓
[SQL Generation] DB-aware prompt with actual schema
    ↓
[Error Handling] Parse error → targeted repair hint
    ↓
[Execution] EXPLAIN check → execute → return results
```

---

## Phase 1: Dynamic FK Extraction & Persistent Storage (Day 1)

### 1.1: Update Database Models

**File:** `app/models.py`

Add these models:

```python
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

# Add to existing Column model:
class Column(Base):
    __tablename__ = "columns"
    
    id = Column(Integer, primary_key=True)
    table_id = Column(Integer, ForeignKey("tables.id"), nullable=False)
    name = Column(String, nullable=False)
    data_type = Column(String, nullable=False)
    is_nullable = Column(Boolean, default=True)
    is_primary_key = Column(Boolean, default=False)  # ADD THIS
    # ... rest of existing columns unchanged


# Add new model for foreign keys:
class ForeignKey(Base):
    __tablename__ = "foreign_keys"
    
    id = Column(Integer, primary_key=True)
    database_id = Column(Integer, ForeignKey("databases.id"), nullable=False)
    table_name = Column(String, nullable=False)
    column_name = Column(String, nullable=False)
    referenced_table = Column(String, nullable=False)
    referenced_column = Column(String, nullable=False)
    constraint_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('database_id', 'table_name', 'column_name', name='uq_fk_per_db'),
    )
```

Then run migration:
```bash
cd /Users/sauravchakraborty/DbChat
source venv/bin/activate
alembic revision --autogenerate -m "Add ForeignKey model and is_primary_key to Column"
alembic upgrade head
```

---

### 1.2: Update SchemaExtractor to Use SQLAlchemy Inspector

**File:** `app/services/schema_service.py`

Replace the raw SQL approach with SQLAlchemy's inspector (works on all DB types automatically):

```python
from sqlalchemy import inspect, text
from sqlalchemy.pool import NullPool
from app.models import Table, Column, ForeignKey as FKModel
import logging

logger = logging.getLogger(__name__)

class SchemaExtractor:
    
    def __init__(self):
        self.connections = {}
    
    @staticmethod
    def _do_extract(engine, database: str) -> Dict[str, Any]:
        """
        Extract schema using SQLAlchemy inspector (database-agnostic).
        Returns structure ready to store in DB models.
        """
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        schema_data = {
            "database": database,
            "tables": [],
            "foreign_keys": []
        }
        
        # Skip system tables
        skip_prefixes = ('pg_', 'information_schema', 'sqlite_', 'mysql', 'performance_schema')
        tables = [t for t in tables if not any(t.startswith(p) for p in skip_prefixes)]
        
        for table_name in tables:
            try:
                # Get columns
                columns = inspector.get_columns(table_name)
                
                # Get primary key
                pk_constraint = inspector.get_pk_constraint(table_name)
                pk_cols = set(pk_constraint.get("constrained_columns", []))
                
                table_info = {
                    "name": table_name,
                    "columns": []
                }
                
                for col in columns:
                    col_info = {
                        "name": col["name"],
                        "type": str(col["type"]),
                        "nullable": col.get("nullable", True),
                        "primary_key": col["name"] in pk_cols,
                    }
                    table_info["columns"].append(col_info)
                
                schema_data["tables"].append(table_info)
                
                # Get foreign keys
                try:
                    fks = inspector.get_foreign_keys(table_name)
                    for fk in fks:
                        if fk.get("constrained_columns") and fk.get("referred_columns"):
                            # Handle composite keys (take first column)
                            fk_record = {
                                "table": table_name,
                                "column": fk["constrained_columns"][0],
                                "referenced_table": fk["referred_table"],
                                "referenced_column": fk["referred_columns"][0],
                                "constraint_name": fk.get("name", "")
                            }
                            schema_data["foreign_keys"].append(fk_record)
                except Exception as e:
                    logger.warning(f"Could not extract FKs from {table_name}: {e}")
            
            except Exception as e:
                logger.warning(f"Error extracting table {table_name}: {e}")
        
        return schema_data


    @staticmethod
    def _get_engine(connection_config: dict) -> Engine:
        """Build engine matching the existing pattern in your code."""
        db_type = connection_config.get("type", "postgresql").lower()
        
        if db_type == "postgresql":
            connection_string = (
                f"postgresql://{connection_config['user']}:{connection_config['password']}"
                f"@{connection_config['host']}:{connection_config.get('port', 5432)}"
                f"/{connection_config['database']}"
                f"?sslmode={'require' if connection_config.get('ssl') else 'disable'}"
            )
        elif db_type == "mysql":
            connection_string = (
                f"mysql+pymysql://{connection_config['user']}:{connection_config['password']}"
                f"@{connection_config['host']}:{connection_config.get('port', 3306)}"
                f"/{connection_config['database']}"
            )
        elif db_type in ["mssql", "sql_server"]:
            connection_string = (
                f"mssql+pyodbc://{connection_config['user']}:{connection_config['password']}"
                f"@{connection_config['host']}:{connection_config.get('port', 1433)}"
                f"/{connection_config['database']}"
                f"?driver=ODBC+Driver+17+for+SQL+Server"
            )
        
        return create_engine(connection_string, poolclass=NullPool)
```

---

### 1.3: Update IndexingService to Store FKs and Enhanced Metadata

**File:** `app/services/indexing_service.py`

Modify the indexing flow to:
1. Store foreign keys in DB
2. Store is_primary_key on Column records
3. Generate semantic summaries for tables

```python
from app.models import ForeignKey as FKModel
from app.services.schema_service import SchemaExtractor
from app.services.ollama_service import OllamaService
import logging

logger = logging.getLogger(__name__)

class IndexingService:
    
    def __init__(self, db_session, ollama_service: OllamaService):
        self.db = db_session
        self.ollama = ollama_service
        self.extractor = SchemaExtractor()
    
    async def reindex_database(self, connection_id: int):
        """
        Complete re-indexing: extract schema, store FKs, generate summaries.
        """
        connection = self.db.query(Connection).filter(Connection.id == connection_id).first()
        if not connection:
            raise ValueError(f"Connection {connection_id} not found")
        
        database = self.db.query(Database).filter(
            Database.connection_id == connection_id
        ).first()
        
        try:
            # Extract schema using inspector
            logger.info(f"[INDEX] Extracting schema for {database.name}...")
            engine = self.extractor._get_engine(connection.config)
            schema_data = self.extractor._do_extract(engine, database.name)
            
            # Store tables and columns
            existing_tables = {t.name: t for t in database.tables}
            
            for table_info in schema_data["tables"]:
                table_name = table_info["name"]
                
                if table_name not in existing_tables:
                    table = Table(database_id=database.id, name=table_name)
                    self.db.add(table)
                    self.db.flush()  # Get the ID
                    existing_tables[table_name] = table
                else:
                    table = existing_tables[table_name]
                
                # Update columns with primary key info
                existing_cols = {c.name: c for c in table.columns}
                
                for col_info in table_info["columns"]:
                    col_name = col_info["name"]
                    
                    if col_name not in existing_cols:
                        col = Column(
                            table_id=table.id,
                            name=col_name,
                            data_type=col_info["type"],
                            is_nullable=col_info["nullable"],
                            is_primary_key=col_info["primary_key"],  # STORE THIS
                        )
                        self.db.add(col)
                    else:
                        # Update primary key flag
                        col = existing_cols[col_name]
                        col.is_primary_key = col_info["primary_key"]
                        col.data_type = col_info["type"]
                        col.is_nullable = col_info["nullable"]
            
            self.db.commit()
            
            # Store foreign keys (delete old ones first)
            logger.info(f"[INDEX] Storing foreign key constraints...")
            self.db.query(FKModel).filter(FKModel.database_id == database.id).delete()
            
            for fk in schema_data["foreign_keys"]:
                fk_record = FKModel(
                    database_id=database.id,
                    table_name=fk["table"],
                    column_name=fk["column"],
                    referenced_table=fk["referenced_table"],
                    referenced_column=fk["referenced_column"],
                    constraint_name=fk.get("constraint_name", "")
                )
                self.db.add(fk_record)
            
            self.db.commit()
            
            # Generate semantic table summaries
            logger.info(f"[INDEX] Generating table summaries...")
            for table in database.tables:
                try:
                    summary = await self._generate_table_summary(table)
                    table.context = summary
                except Exception as e:
                    logger.warning(f"Could not generate summary for {table.name}: {e}")
                    # Keep structural summary as fallback
                    col_names = ", ".join([c.name for c in table.columns])
                    table.context = f"Table {table.name} with columns: {col_names}"
            
            self.db.commit()
            logger.info(f"[INDEX] Indexing complete for {database.name}")
        
        except Exception as e:
            self.db.rollback()
            logger.error(f"[INDEX] Failed: {e}")
            raise
    
    async def _generate_table_summary(self, table: Table) -> str:
        """
        Generate a 1-2 sentence semantic description of what the table stores.
        Used for table selection context.
        """
        col_names = ", ".join([c.name for c in table.columns[:10]])
        col_types = ", ".join([f"{c.name}({c.data_type})" for c in table.columns[:5]])
        
        prompt = (
            f"Table name: {table.name}\n"
            f"Columns: {col_names}\n"
            f"Column types: {col_types}\n\n"
            "Write a single 1-2 sentence description: "
            "What real-world entity does this table represent? "
            "When would a query need to join to this table? "
            "Be specific and concise."
        )
        
        try:
            # Use new generate_simple method
            summary = await self.ollama.generate_simple(prompt, max_tokens=60)
            return summary if summary else self._fallback_summary(table)
        except Exception as e:
            logger.warning(f"Could not generate summary: {e}")
            return self._fallback_summary(table)
    
    def _fallback_summary(self, table: Table) -> str:
        """Fallback: just list columns."""
        cols = ", ".join([c.name for c in table.columns])
        return f"Table {table.name} with columns: {cols}"
```

---

## Phase 2: Intelligent Schema Context Generation (Day 2-3)

### 2.1: Rewrite MetadataService with Real FK Graph + BFS

**File:** `app/services/metadata_service.py`

This is the core of the system — build context from actual database structure:

```python
from collections import defaultdict, deque
from itertools import combinations
from app.models import Database, Table, Column, ForeignKey as FKModel
import json
import logging

logger = logging.getLogger(__name__)

class MetadataService:
    
    def __init__(self, db_session):
        self.db = db_session
        self.fk_cache = {}  # {database_id: fk_map}
        self.graph_cache = {}  # {database_id: adjacency_graph}
        self.path_cache = {}  # {(database_id, from_table, to_table): path}
    
    def _load_fk_graph(self, database_id: int) -> tuple[dict, dict]:
        """
        Load FK relationships from DB models into lookup structures.
        
        Returns:
            fk_map: {(table, col) -> (ref_table, ref_col)}
            graph: {table -> set(connected_tables)} for BFS
        """
        # Return cached if available
        if database_id in self.fk_cache:
            return self.fk_cache[database_id], self.graph_cache[database_id]
        
        # Load from DB
        fks = self.db.query(FKModel).filter(FKModel.database_id == database_id).all()
        
        fk_map = {}
        graph = defaultdict(set)
        
        for fk in fks:
            fk_map[(fk.table_name, fk.column_name)] = (fk.referenced_table, fk.referenced_column)
            # Build undirected graph for path finding
            graph[fk.table_name].add(fk.referenced_table)
            graph[fk.referenced_table].add(fk.table_name)
        
        # Convert defaultdict to regular dict for caching
        graph = {k: v for k, v in graph.items()}
        
        self.fk_cache[database_id] = fk_map
        self.graph_cache[database_id] = graph
        
        return fk_map, graph
    
    def _find_join_path(self, database_id: int, from_table: str, to_table: str,
                       max_hops: int = 4) -> Optional[List[str]]:
        """
        Find shortest path between two tables using BFS on FK graph.
        Cached to avoid repeated searches.
        """
        cache_key = (database_id, from_table, to_table)
        if cache_key in self.path_cache:
            return self.path_cache[cache_key]
        
        _, graph = self._load_fk_graph(database_id)
        
        if from_table == to_table:
            return [from_table]
        if from_table not in graph:
            return None
        
        # BFS
        queue = deque([(from_table, [from_table])])
        visited = {from_table}
        
        while queue:
            current, path = queue.popleft()
            
            if len(path) > max_hops:
                continue
            
            for neighbor in graph.get(current, []):
                if neighbor not in visited:
                    if neighbor == to_table:
                        result = path + [neighbor]
                        self.path_cache[cache_key] = result
                        return result
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        
        return None
    
    def _path_to_join_conditions(self, database_id: int, path: List[str]) -> List[str]:
        """
        Convert a table path to actual JOIN ON conditions.
        
        Example: ["artist", "album", "track"] →
                 ["artist.artist_id = album.artist_id", "album.album_id = track.album_id"]
        """
        fk_map, _ = self._load_fk_graph(database_id)
        conditions = []
        
        for i in range(len(path) - 1):
            t1, t2 = path[i], path[i+1]
            
            # Check if forward FK exists
            found = False
            for (table, col), (ref_table, ref_col) in fk_map.items():
                if table == t1 and ref_table == t2:
                    conditions.append(f"{t1}.{col} = {t2}.{ref_col}")
                    found = True
                    break
            
            if not found:
                # Check reverse FK
                for (table, col), (ref_table, ref_col) in fk_map.items():
                    if table == t2 and ref_table == t1:
                        conditions.append(f"{t2}.{col} = {t1}.{ref_col}")
                        break
        
        return conditions
    
    def get_column_schema(self, database_id: int, table_names: List[str]) -> str:
        """
        Build comprehensive schema context from actual database structure.
        
        Returns formatted schema string with:
        - Column listings (table-qualified)
        - Foreign key relationships
        - Multi-hop join paths
        - Ambiguity warnings
        """
        try:
            fk_map, graph = self._load_fk_graph(database_id)
            
            # Load table objects
            tables = {}
            for table_name in table_names:
                table = self.db.query(Table).filter(
                    Table.database_id == database_id,
                    Table.name == table_name
                ).first()
                if table:
                    tables[table_name] = table
            
            # Find ambiguous columns across selected tables
            col_to_tables = defaultdict(list)
            for table_name, table in tables.items():
                for col in table.columns:
                    col_to_tables[col.name].append(table_name)
            
            ambiguous = {col for col, table_list in col_to_tables.items() if len(table_list) > 1}
            
            # Build output
            parts = []
            
            # Part 1: Per-table column listings
            for table_name in table_names:
                table = tables.get(table_name)
                if not table:
                    continue
                
                lines = [
                    f"TABLE: {table_name}",
                    f"Rows: ~{table.sample_count or 'unknown'}",
                    ""
                ]
                
                for col in table.columns:
                    col_desc = f"  {table_name}.{col.name} : {col.data_type}"
                    
                    # Add tags
                    tags = []
                    if col.is_primary_key:
                        tags.append("PRIMARY_KEY")
                    if not col.is_nullable:
                        tags.append("NOT_NULL")
                    if (table_name, col.name) in fk_map:
                        ref_t, ref_c = fk_map[(table_name, col.name)]
                        tags.append(f"→{ref_t}.{ref_c}")
                    if col.name in ambiguous:
                        tags.append("⚠AMBIGUOUS")
                    
                    if tags:
                        col_desc += f"  [{' | '.join(tags)}]"
                    
                    # Add sample values if available
                    if col.sample_values:
                        try:
                            samples = json.loads(col.sample_values)
                            samples_str = ", ".join(str(v)[:15] for v in samples[:3])
                            col_desc += f"  (e.g. {samples_str})"
                        except Exception:
                            pass
                    
                    lines.append(col_desc)
                
                parts.append("\n".join(lines))
            
            # Part 2: FK relationships
            rel_lines = ["FOREIGN KEYS (valid JOIN conditions):"]
            for (table, col), (ref_table, ref_col) in fk_map.items():
                if table in table_names or ref_table in table_names:
                    rel_lines.append(f"  {table}.{col} = {ref_table}.{ref_col}")
            
            parts.append("\n".join(rel_lines))
            
            # Part 3: Multi-hop paths
            if len(table_names) > 1:
                path_lines = ["MULTI-HOP JOIN PATHS (between selected tables):"]
                for t1, t2 in combinations(table_names, 2):
                    path = self._find_join_path(database_id, t1, t2)
                    if path and len(path) > 2:
                        conditions = self._path_to_join_conditions(database_id, path)
                        path_str = " → ".join(path)
                        cond_str = " AND ".join(conditions) if conditions else "?"
                        path_lines.append(f"  {t1} to {t2}: {path_str}")
                        path_lines.append(f"    ({cond_str})")
                
                if len(path_lines) > 1:
                    parts.append("\n".join(path_lines))
            
            # Part 4: Ambiguity warning
            if ambiguous:
                amb_lines = [
                    "⚠ COLUMNS IN MULTIPLE SELECTED TABLES (MUST BE TABLE-QUALIFIED):"
                ]
                for col in sorted(ambiguous):
                    tables_str = ", ".join(col_to_tables[col])
                    amb_lines.append(f"  {col} → in {tables_str}")
                
                parts.append("\n".join(amb_lines))
            
            return "\n\n" + ("\n" + "="*60 + "\n").join(parts)
        
        except Exception as e:
            logger.error(f"Error building schema context: {e}")
            return None
```

---

### 2.2: Update OllamaService with Permanent Rules + New Methods

**File:** `app/services/ollama_service.py`

Replace hardcoded prompt fragments with permanent dialect rules + add helper methods:

```python
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Permanent rules — never change these
_POSTGRESQL_RULES = """POSTGRESQL RULES:
1. Qualify every column: table.column (no bare names in JOINs)
2. No nested aggregates ever: AVG(SUM(x)) is ALWAYS invalid
   → Compute inner aggregate in subquery, then outer aggregate
3. Window functions (OVER clause) only in SELECT and ORDER BY
   → Never in WHERE or HAVING — use subquery instead
4. The column list in schema is COMPLETE and EXHAUSTIVE
   → Never reference a column not listed
5. For "X > average of X" pattern, use this exact structure:
   WHERE col > (SELECT AVG(col) FROM table)
   or for per-group: WHERE col > (SELECT AVG(x) FROM t2 WHERE t2.id = t1.id)"""

_MYSQL_RULES = """MYSQL RULES:
1. Qualify every column: table.column in multi-table queries
2. No nested aggregates — use subquery pattern
3. Use backticks only for reserved word identifiers: `table`.`column`
4. The column list is EXHAUSTIVE — no guessed columns
5. Window functions require MySQL 8.0+"""

_MSSQL_RULES = """SQL SERVER RULES:
1. Qualify every column: [table].[column] in multi-table queries
2. No nested aggregates — use subquery or CTE pattern
3. Use TOP N instead of LIMIT (but only for final result set)
4. Square brackets for any reserved word: [table].[column]
5. The column list is EXHAUSTIVE — no guessed columns"""


class OllamaService:
    
    def __init__(self, config):
        self.base_url = config.get("base_url", "http://localhost:11434")
        self.llm_model = config.get("model", "mistral")
        self.embed_model = config.get("embed_model", "nomic-embed-text")
    
    def _get_dialect_rules(self, db_type: str) -> str:
        """Get permanent rules for this database type."""
        t = db_type.lower()
        if "mysql" in t:
            return _MYSQL_RULES
        if "mssql" in t or "sql_server" in t:
            return _MSSQL_RULES
        return _POSTGRESQL_RULES  # default
    
    async def generate_sql(self, user_prompt: str, schema_context: str,
                          db_type: str = "postgresql", error_context: Optional[str] = None) -> str:
        """
        Generate SQL with database-aware system prompt.
        
        Args:
            user_prompt: The user's natural language question
            schema_context: From MetadataService.get_column_schema()
            db_type: Database type for dialect rules
            error_context: If repairing, the previous error + hint
        """
        
        dialect_rules = self._get_dialect_rules(db_type)
        
        system_prompt = f"""You are a SQL expert. Output ONLY a single SELECT query, nothing else.

{dialect_rules}

CRITICAL OUTPUT RULES:
- No explanation, no preamble
- No markdown fences (no ```sql)
- Only SELECT statements
- Stop after the final semicolon
- Only use tables from schema below"""
        
        if error_context:
            system_prompt += f"\n\nPREVIOUS FAILURE:\n{error_context}"
        
        full_prompt = f"Schema:\n{schema_context}\n\nQuestion: {user_prompt}\n\nSQL:"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.llm_model,
                        "prompt": full_prompt,
                        "system": system_prompt,
                        "stream": False,
                        "temperature": 0.0,
                        "top_p": 0.9,
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    sql = response.json().get("response", "").strip()
                    
                    # Clean up
                    sql = sql.replace("```sql", "").replace("```", "").strip()
                    sql = sql.strip('"').strip("'")
                    
                    # Extract only the SQL if there's junk after
                    if ";" in sql:
                        sql = sql[:sql.index(";") + 1]
                    
                    return sql
                else:
                    logger.error(f"Ollama error {response.status_code}: {response.text}")
                    return ""
        
        except Exception as e:
            logger.error(f"Failed to generate SQL: {e}")
            return ""
    
    async def generate_sql_with_hint(self, user_prompt: str, schema_context: str,
                                     failed_sql: str, error: str, hint: str,
                                     db_type: str = "postgresql") -> str:
        """
        Repair a failed query with targeted hint from ErrorParser.
        """
        dialect_rules = self._get_dialect_rules(db_type)
        
        system_prompt = f"""You are fixing a broken SQL query.

{dialect_rules}

REPAIR RULES:
- Read the error and hint carefully
- The hint tells you exactly what to fix
- Output ONLY corrected SQL, nothing else"""
        
        prompt = (
            f"Schema:\n{schema_context}\n\n"
            f"User's original question: {user_prompt}\n\n"
            f"Failed SQL:\n{failed_sql}\n\n"
            f"Error: {error}\n\n"
            f"Fix instruction: {hint}\n\n"
            f"Corrected SQL:"
        )
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.llm_model,
                        "prompt": prompt,
                        "system": system_prompt,
                        "stream": False,
                        "temperature": 0.0,
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    sql = response.json().get("response", "").strip()
                    sql = sql.replace("```sql", "").replace("```", "").strip()
                    if ";" in sql:
                        sql = sql[:sql.index(";") + 1]
                    return sql
        
        except Exception as e:
            logger.error(f"Repair generation failed: {e}")
        
        return ""
    
    async def generate_simple(self, prompt: str, max_tokens: int = 80) -> str:
        """
        For non-SQL generation tasks (e.g., table summaries).
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.llm_model,
                        "prompt": prompt,
                        "stream": False,
                        "temperature": 0.0,
                        "options": {"num_predict": max_tokens}
                    },
                    timeout=15.0
                )
                
                if response.status_code == 200:
                    return response.json().get("response", "").strip()
        
        except Exception as e:
            logger.warning(f"Simple generation failed: {e}")
        
        return ""
```

---

## Phase 3: Intelligent Error Recovery (Day 3-4)

### 3.1: Create ErrorParser Service

**File:** `app/services/error_parser.py` (NEW)

```python
from dataclasses import dataclass
from typing import Optional
import re
import logging

logger = logging.getLogger(__name__)


@dataclass
class ParsedError:
    error_type: str  # Type of error: "ambiguous_column", "missing_column", etc.
    error_message: str
    affected_element: Optional[str]  # Column/table name if extractable
    repair_hint: str  # Actionable instruction for LLM
    database_type: str


class ErrorParser:
    """
    Parse database errors and generate targeted repair hints.
    Works across PostgreSQL, MySQL, SQL Server.
    """
    
    @staticmethod
    def parse(error_message: str, database_type: str) -> ParsedError:
        """Parse error into actionable repair hint."""
        error_lower = error_message.lower()
        
        # PostgreSQL
        if "ambiguous column reference" in error_lower:
            column = ErrorParser._extract_identifier(error_message)
            return ParsedError(
                error_type="ambiguous_column",
                error_message=error_message,
                affected_element=column,
                repair_hint=f"Column '{column}' appears in multiple tables. "
                           f"Qualify it everywhere: table_name.{column}",
                database_type=database_type
            )
        
        elif "column" in error_lower and "does not exist" in error_lower:
            column = ErrorParser._extract_identifier(error_message)
            return ParsedError(
                error_type="missing_column",
                error_message=error_message,
                affected_element=column,
                repair_hint=f"Column '{column}' doesn't exist in selected tables. "
                           f"Check schema context. You may need to JOIN to another table to get this column.",
                database_type=database_type
            )
        
        elif "aggregate function calls cannot be nested" in error_lower:
            return ParsedError(
                error_type="nested_aggregate",
                error_message=error_message,
                affected_element=None,
                repair_hint="Nested aggregates (AVG(SUM(...))) are not allowed. "
                           "Move the inner aggregate (SUM) to a subquery, then apply the outer aggregate (AVG) to the result.",
                database_type=database_type
            )
        
        elif "window function" in error_lower and ("where" in error_lower or "having" in error_lower):
            return ParsedError(
                error_type="window_in_filter",
                error_message=error_message,
                affected_element=None,
                repair_hint="Window functions (OVER clause) cannot be in WHERE or HAVING. "
                           "Move window function to a subquery in the FROM clause, then filter in the outer WHERE.",
                database_type=database_type
            )
        
        elif "syntax error" in error_lower:
            return ParsedError(
                error_type="syntax_error",
                error_message=error_message,
                affected_element=None,
                repair_hint="SQL syntax error. Check: 1) parentheses balanced, 2) commas between columns, "
                           "3) valid keywords, 4) correct quote style for this database.",
                database_type=database_type
            )
        
        elif "relation" in error_lower and "does not exist" in error_lower:
            table = ErrorParser._extract_identifier(error_message)
            return ParsedError(
                error_type="missing_table",
                error_message=error_message,
                affected_element=table,
                repair_hint=f"Table '{table}' doesn't exist. Check the exact table name in schema context. "
                           f"Table names are case-sensitive in some databases.",
                database_type=database_type
            )
        
        # PostgreSQL type errors
        elif "operator does not exist" in error_lower or "type" in error_lower and "does not exist" in error_lower:
            return ParsedError(
                error_type="type_mismatch",
                error_message=error_message,
                affected_element=None,
                repair_hint="Type mismatch in comparison. Cast values explicitly. "
                           "Example: col::text, or CAST(col AS TEXT), or CAST(col AS VARCHAR).",
                database_type=database_type
            )
        
        elif "subquery returns more than one row" in error_lower:
            return ParsedError(
                error_type="subquery_multiple_rows",
                error_message=error_message,
                affected_element=None,
                repair_hint="Scalar subquery returned multiple rows. "
                           "Either: 1) Add LIMIT 1, or 2) Use IN/ANY instead of =, or 3) Add WHERE to filter to one row.",
                database_type=database_type
            )
        
        # MySQL
        elif "unknown column" in error_lower:
            column = ErrorParser._extract_identifier(error_message)
            return ParsedError(
                error_type="missing_column",
                error_message=error_message,
                affected_element=column,
                repair_hint=f"Column '{column}' doesn't exist. Check schema context for available columns.",
                database_type=database_type
            )
        
        elif "syntax error" in error_lower and "sql" in error_lower:
            return ParsedError(
                error_type="syntax_error",
                error_message=error_message,
                affected_element=None,
                repair_hint="MySQL syntax error. Check: 1) backtick usage for reserved words, 2) quote style, "
                           "3) keyword spelling, 4) parentheses balanced.",
                database_type=database_type
            )
        
        # SQL Server
        elif "invalid column name" in error_lower:
            column = ErrorParser._extract_identifier(error_message)
            return ParsedError(
                error_type="missing_column",
                error_message=error_message,
                affected_element=column,
                repair_hint=f"Column '{column}' not found in specified table. "
                           f"Check schema context for exact column names.",
                database_type=database_type
            )
        
        elif "ambiguous column name" in error_lower:
            column = ErrorParser._extract_identifier(error_message)
            return ParsedError(
                error_type="ambiguous_column",
                error_message=error_message,
                affected_element=column,
                repair_hint=f"Column '{column}' is ambiguous. "
                           f"Use table alias: [table].[{column}] (SQL Server syntax).",
                database_type=database_type
            )
        
        # Generic
        return ParsedError(
            error_type="unknown",
            error_message=error_message,
            affected_element=None,
            repair_hint="Query failed. Review the error carefully. "
                       "Check: 1) column names match schema, 2) tables are qualified, 3) JOIN conditions are correct.",
            database_type=database_type
        )
    
    @staticmethod
    def _extract_identifier(error_message: str) -> Optional[str]:
        """Extract quoted identifier from error message."""
        # PostgreSQL: "column_name"
        match = re.search(r'"([^"]+)"', error_message)
        if match:
            return match.group(1)
        
        # MySQL: `column_name`
        match = re.search(r'`([^`]+)`', error_message)
        if match:
            return match.group(1)
        
        # SQL Server: [column_name]
        match = re.search(r'\[([^\]]+)\]', error_message)
        if match:
            return match.group(1)
        
        # Fallback: 'column_name'
        match = re.search(r"'([^']+)'", error_message)
        if match:
            return match.group(1)
        
        return None
```

---

### 3.2: Update ChatService to Wire Everything Together

**File:** `app/services/chat_service.py`

Key changes:
1. Load schema context from MetadataService (with real FKs)
2. Pass db_type to LLM
3. Use ErrorParser for smart repairs
4. Add EXPLAIN validation

```python
from app.services.metadata_service import MetadataService
from app.services.error_parser import ErrorParser
import logging

logger = logging.getLogger(__name__)

class ChatService:
    
    def __init__(self, db_session, metadata_service, ollama_service):
        self.db = db_session
        self.metadata = metadata_service
        self.ollama = ollama_service
    
    async def process_user_prompt(self, connection_id: int, prompt: str) -> dict:
        """Main query processing pipeline."""
        start_time = time.time()
        
        # Get connection info
        connection = self.db.query(Connection).filter(Connection.id == connection_id).first()
        if not connection:
            return {"status": "error", "error": "Connection not found"}
        
        db_type = connection.database_type.lower()
        database = self.db.query(Database).filter(Database.connection_id == connection_id).first()
        
        try:
            # Step 1: Intent classification
            intent = await self._classify_intent(prompt)
            if intent == "catalog":
                # Handle schema queries (DESCRIBE, SHOW TABLES, etc.)
                return await self._handle_catalog_query(prompt, connection_id)
            
            # Step 2: Table selection
            table_names = await self._select_tables(prompt, connection_id)
            if not table_names:
                return {"status": "error", "error": "No relevant tables found"}
            
            # Step 3: Build schema context with REAL FKs
            schema_context = self.metadata.get_column_schema(database.id, table_names)
            if not schema_context:
                return {"status": "error", "error": "Failed to build schema context"}
            
            # Step 4: Generate SQL
            logger.info(f"[SQL] Generating for tables: {table_names}")
            sql_query = await self.ollama.generate_sql(
                user_prompt=prompt,
                schema_context=schema_context,
                db_type=db_type,
                error_context=None
            )
            
            if not sql_query:
                return {"status": "error", "error": "Failed to generate SQL"}
            
            logger.info(f"[SQL] Generated: {sql_query[:100]}")
            
            # Step 5: Validate with EXPLAIN
            validation_error = await self._explain_check(connection, sql_query, db_type)
            if validation_error:
                logger.warning(f"[VALIDATION] Query failed EXPLAIN check: {validation_error[:100]}")
                # Try to repair
                parsed = ErrorParser.parse(validation_error, db_type)
                if parsed.error_type in ["ambiguous_column", "missing_column", "syntax_error"]:
                    logger.info(f"[REPAIR] Attempting repair for {parsed.error_type}")
                    sql_query = await self.ollama.generate_sql_with_hint(
                        user_prompt=prompt,
                        schema_context=schema_context,
                        failed_sql=sql_query,
                        error=validation_error,
                        hint=parsed.repair_hint,
                        db_type=db_type
                    )
                    if not sql_query:
                        return {"status": "error", "error": f"Validation failed and repair failed: {validation_error[:200]}"}
                else:
                    return {"status": "error", "error": f"Query validation failed: {validation_error[:200]}"}
            
            # Step 6: Execute query
            result = await self._execute_query(connection, sql_query)
            
            if result["status"] == "error":
                # Execution error — try one more repair
                error_text = result.get("error", "")
                parsed = ErrorParser.parse(error_text, db_type)
                
                repairable_types = [
                    "ambiguous_column", "missing_column", "nested_aggregate",
                    "window_in_filter", "missing_table", "type_mismatch", "subquery_multiple_rows"
                ]
                
                if parsed.error_type in repairable_types:
                    logger.info(f"[REPAIR] Execution failed, attempting repair for {parsed.error_type}")
                    repaired_sql = await self.ollama.generate_sql_with_hint(
                        user_prompt=prompt,
                        schema_context=schema_context,
                        failed_sql=sql_query,
                        error=error_text,
                        hint=parsed.repair_hint,
                        db_type=db_type
                    )
                    
                    if repaired_sql:
                        retry = await self._execute_query(connection, repaired_sql)
                        if retry["status"] == "success":
                            # Repair succeeded!
                            answer = await self._format_answer(prompt, repaired_sql, retry)
                            return {
                                "status": "success",
                                "answer": answer,
                                "sql": repaired_sql,
                                "rows": retry["rows"],
                                "columns": retry["columns"],
                                "row_count": retry["row_count"],
                                "execution_time_ms": int((time.time() - start_time) * 1000),
                                "repaired": True
                            }
                
                return {**result, "sql": sql_query, "execution_time_ms": int((time.time() - start_time) * 1000)}
            
            # Success
            answer = await self._format_answer(prompt, sql_query, result)
            return {
                "status": "success",
                "answer": answer,
                "sql": sql_query,
                "rows": result["rows"],
                "columns": result["columns"],
                "row_count": result["row_count"],
                "execution_time_ms": int((time.time() - start_time) * 1000),
                "repaired": False
            }
        
        except Exception as e:
            logger.error(f"[ERROR] {e}", exc_info=True)
            return {"status": "error", "error": str(e)[:200]}
    
    async def _explain_check(self, connection, sql: str, db_type: str) -> Optional[str]:
        """
        Validate SQL using EXPLAIN without executing.
        Returns error string if invalid, None if valid.
        """
        try:
            # Skip EXPLAIN for SQL Server (has limitations)
            if "mssql" in db_type or "sql_server" in db_type:
                return None
            
            # Build EXPLAIN query
            explain_sql = f"EXPLAIN {sql}" if "mysql" not in db_type else f"EXPLAIN {sql}"
            
            # Run using same executor pattern as _execute_query
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._sync_explain(connection, explain_sql)
            )
            return result  # None if valid, error message if invalid
        
        except Exception as e:
            return str(e)
    
    def _sync_explain(self, connection, explain_sql: str) -> Optional[str]:
        """Synchronous EXPLAIN check."""
        try:
            engine = self._get_engine(connection)
            with engine.connect() as conn:
                conn.execute(text(explain_sql))
            return None  # Valid
        except Exception as e:
            return str(e)
```

---

## Phase 4: Testing & Validation (Day 5)

### 4.1: Run Comprehensive Test Suite

After each phase, validate progress:

```bash
# Phase 1 complete:
for i in {1..3}; do
    echo "=== Phase 1 Test - Run $i ==="
    bash /tmp/dbchat_comprehensive_test.sh 2>&1 | grep -E "Test #|Success Rate"
    sleep 5
done
# Expected: 40-50% pass rate (real FKs help with table selection)

# Phase 2 complete:
for i in {1..3}; do
    echo "=== Phase 2 Test - Run $i ==="
    bash /tmp/dbchat_comprehensive_test.sh 2>&1 | grep -E "Test #|Success Rate"
    sleep 5
done
# Expected: 60-70% pass rate (schema context + column qualification)

# Phase 3 complete:
for i in {1..5}; do
    echo "=== Phase 3 Test - Run $i ==="
    bash /tmp/dbchat_comprehensive_test.sh 2>&1 | grep -E "Test #|Success Rate"
    sleep 5
done
# Expected: 75-85% pass rate (smart error recovery)

# Final:
for i in {1..10}; do
    echo "=== Final Test - Run $i ==="
    bash /tmp/dbchat_comprehensive_test.sh 2>&1 | grep -E "Test #|Success Rate"
    sleep 5
done
# Expected: 85-90% pass rate (consistent)
```

---

## Implementation Checklist

### Phase 1: FK Storage ✅
- [ ] Task 1.1: Add ForeignKey model + is_primary_key to Column
- [ ] Task 1.2: Update SchemaExtractor to use inspector
- [ ] Task 1.3: Update IndexingService to store FKs + summaries
- [ ] Alembic migration
- [ ] Re-index existing connections

### Phase 2: Context Generation ✅
- [ ] Task 2.1: Rewrite MetadataService with BFS + real FKs
- [ ] Task 2.2: Update OllamaService with dialect rules + methods
- [ ] Validate improved schema context output

### Phase 3: Error Recovery ✅
- [ ] Task 3.1: Create ErrorParser service
- [ ] Task 3.2: Update ChatService to use ErrorParser + EXPLAIN

### Phase 4: Testing ✅
- [ ] Run 10 iterations, calculate mean + std dev
- [ ] Confirm 85-90% pass rate
- [ ] Test on Chinook (proven)
- [ ] Test on alternate schema (generalization)

---

## Success Criteria

**Final State:**
- ✅ 85-90% of test suite passes consistently
- ✅ Works on PostgreSQL, MySQL, SQL Server
- ✅ Zero hardcoded Chinook-specific patterns
- ✅ Handles new databases automatically
- ✅ FK relationships from actual database constraints
- ✅ Smart error repair with targeted hints
- ✅ EXPLAIN validation before execution

**Proof of Generalization:**
- Same test suite passes on different database with same rate
- New database schema indexed automatically
- No code changes needed for new schema

---

## Key Differences from Naive Plan

| Aspect | Naive | This Plan |
|--------|-------|-----------|
| FK Storage | In-memory dict (lost on restart) | Database models (persistent) |
| BFS Execution | Per-query DB hit | Once at onboarding, cached in memory |
| Inspector Usage | Raw information_schema SQL | SQLAlchemy inspector (DB-agnostic) |
| Async Pattern | Mismatch with codebase | Matches existing sync + executor |
| Error Repair | Generic hints | Database-specific ParsedError |
| Column Format | Listed without table prefix | Shows as table.column automatically |
| Ambiguity Detection | Not tracked | Explicit ⚠ warnings in context |

---

## Going Live

**Day 1:** Phases 1-2 complete → ~60-70% pass rate  
**Day 2:** Phase 3 complete → ~80-85% pass rate  
**Day 3:** Phase 4 validation → ~85-90% pass rate  

Then: Monitor, collect failed queries, add patterns as needed.

