"""Metadata service for schema and table summaries"""

import logging
from typing import List, Dict, Optional, Set, Tuple
from collections import deque, defaultdict

from app.database import SessionLocal
from app.models import Database, Table, Column, ForeignKeyModel as ForeignKey

logger = logging.getLogger(__name__)


class MetadataService:
    """Service for retrieving schema metadata and table summaries"""

    def __init__(self):
        self.db = SessionLocal()
        self.fk_graph_cache = {}  # {database_id: {table: {col: (ref_table, ref_col)}}}
        self.column_tables_cache = {}  # {database_id: {col_name: [table_names]}}

    def get_all_table_names(self, connection_id: int) -> List[str]:
        try:
            table_rows = self.db.query(Table).filter(
                Table.database_id.in_(
                    self.db.query(Database.id).filter(
                        Database.connection_id == connection_id
                    )
                )
            ).all()
            return [t.name for t in table_rows]
        except Exception as e:
            logger.error(f"Error fetching table names: {str(e)}")
            return []

    def get_table_summaries(self, connection_id: int) -> List[Dict[str, str]]:
        """Return list of {name, summary} for all tables in connection."""
        try:
            table_rows = self.db.query(Table).filter(
                Table.database_id.in_(
                    self.db.query(Database.id).filter(
                        Database.connection_id == connection_id
                    )
                )
            ).all()

            summaries: List[Dict[str, str]] = []
            for table in table_rows:
                summary = table.context
                if not summary:
                    summary = self._build_fallback_summary(table)
                summaries.append({"name": table.name, "summary": summary})
            return summaries
        except Exception as e:
            logger.error(f"Error fetching table summaries: {str(e)}")
            return []

    def get_column_schema(self, connection_id: int, table_names: List[str]) -> Optional[str]:
        """
        Return comprehensive schema context with actual FK relationships and column qualification.
        """
        try:
            import json
            
            # Get database ID
            database = self.db.query(Database).filter(
                Database.connection_id == connection_id
            ).first()
            if not database:
                logger.warning(f"No database found for connection {connection_id}")
                return None
            
            # Load FK graph and column tables map
            fk_graph = self._load_fk_graph(database.id)
            col_tables_map = self._build_column_tables_map(database.id)
            
            context_parts: List[str] = []
            
            for table_name in table_names:
                table = self.db.query(Table).filter(
                    Table.database_id == database.id,
                    Table.name == table_name
                ).first()
                if not table:
                    continue
                
                columns = self.db.query(Column).filter(
                    Column.table_id == table.id
                ).order_by(Column.name).all()
                
                # Build schema context
                context_str = f"=== TABLE: {table_name} ===\n"
                context_str += f"Rows: ~{table.sample_count if table.sample_count else '?'}\n\n"
                context_str += "COLUMNS:\n"
                
                # Column details with constraints
                for col in columns:
                    col_info = f"  {table_name}.{col.name} : {col.data_type}"
                    
                    constraints = []
                    if col.is_primary_key:
                        constraints.append("PRIMARY KEY")
                    if not col.is_nullable:
                        constraints.append("NOT NULL")
                    
                    if constraints:
                        col_info += f" [{', '.join(constraints)}]"
                    
                    # Add sample values if available
                    if col.sample_values:
                        try:
                            samples = json.loads(col.sample_values)
                            sample_str = ", ".join([str(s)[:20] for s in samples[:3]])
                            col_info += f" | Examples: {sample_str}"
                        except Exception:
                            pass
                    
                    context_str += col_info + "\n"
                
                # Real FK relationships from database
                if table_name in fk_graph and fk_graph[table_name]:
                    context_str += "\nFOREIGN KEYS (actual database constraints):\n"
                    for col_name, (ref_table, ref_col) in fk_graph[table_name].items():
                        context_str += f"  {table_name}.{col_name} → {ref_table}.{ref_col}\n"
                
                # Multi-hop paths to other selected tables
                context_str += "\nJOIN PATHS TO OTHER SELECTED TABLES:\n"
                for other_table in table_names:
                    if other_table != table_name:
                        path = self._find_join_path(database.id, fk_graph, table_name, other_table)
                        if path and len(path) > 1:
                            join_conditions = self._path_to_join_conditions(fk_graph, path)
                            
                            if len(path) == 2:
                                # Direct join
                                if join_conditions:
                                    condition = join_conditions[0]["condition"]
                                    context_str += f"  To {other_table}: {condition}\n"
                            else:
                                # Multi-hop
                                path_str = " → ".join(path)
                                conditions = " AND ".join([j["condition"] for j in join_conditions])
                                context_str += f"  To {other_table}: {path_str}\n"
                                context_str += f"    ({conditions})\n"
                
                # Column ambiguity detection
                ambiguous_cols = []
                for col in columns:
                    if col.name in col_tables_map and len(col_tables_map[col.name]) > 1:
                        if col.name not in ambiguous_cols:
                            ambiguous_cols.append(col.name)
                
                if ambiguous_cols:
                    context_str += f"\nAMBIGUOUS COLUMNS (exist in multiple tables):\n"
                    context_str += f"  These columns appear in multiple tables - always use table qualification:\n"
                    for col_name in ambiguous_cols:
                        tables = col_tables_map[col_name]
                        if table_name in tables:
                            context_str += f"    → {table_name}.{col_name} (in this context)\n"
                
                context_parts.append(context_str)
            
            if not context_parts:
                return None

            context = "\n" + ("=" * 80 + "\n").join(context_parts)

            # Global FK relationships (for LLM guidance)
            fk_lines = []
            for tbl, cols in fk_graph.items():
                for col_name, (ref_table, ref_col) in cols.items():
                    fk_lines.append(f"  {tbl}.{col_name} → {ref_table}.{ref_col}")

            if fk_lines:
                context += "\n\nGLOBAL FOREIGN KEY RELATIONSHIPS:\n" + "\n".join(sorted(fk_lines))

            return context
        
        except Exception as e:
            logger.error(f"Error building schema context: {str(e)}", exc_info=True)
            return None

    def _build_fallback_summary(self, table: Table) -> str:
        try:
            columns = self.db.query(Column).filter(
                Column.table_id == table.id
            ).all()
            col_summary = ", ".join([f"{c.name} ({c.data_type})" for c in columns])
            return f"Table: {table.name}. Columns: {col_summary}."
        except Exception:
            return f"Table: {table.name}."

    def _load_fk_graph(self, database_id: int) -> Dict[str, Dict[str, Tuple[str, str]]]:
        """
        Load FK relationships from database into memory.
        Returns: {table_name: {column_name: (referenced_table, referenced_column)}}
        """
        if database_id in self.fk_graph_cache:
            return self.fk_graph_cache[database_id]
        
        fk_graph = defaultdict(dict)
        try:
            fk_records = self.db.query(ForeignKey).filter(
                ForeignKey.database_id == database_id
            ).all()
            
            for fk in fk_records:
                fk_graph[fk.table_name][fk.column_name] = (
                    fk.referenced_table,
                    fk.referenced_column
                )
            
            self.fk_graph_cache[database_id] = dict(fk_graph)
            logger.info(f"Loaded FK graph for database {database_id}: {len(fk_records)} relationships")
            return self.fk_graph_cache[database_id]
        except Exception as e:
            logger.warning(f"Could not load FK graph: {e}")
            self.fk_graph_cache[database_id] = {}
            return {}

    def _build_column_tables_map(self, database_id: int) -> Dict[str, List[str]]:
        """
        Build map of column names to tables for ambiguity detection.
        Returns: {column_name: [table_names]}
        """
        if database_id in self.column_tables_cache:
            return self.column_tables_cache[database_id]
        
        col_tables = defaultdict(list)
        try:
            all_columns = self.db.query(Column).join(Table).filter(
                Table.database_id == database_id
            ).all()
            
            for col in all_columns:
                col_tables[col.name].append(col.table.name)
            
            self.column_tables_cache[database_id] = dict(col_tables)
            return self.column_tables_cache[database_id]
        except Exception as e:
            logger.warning(f"Could not build column tables map: {e}")
            self.column_tables_cache[database_id] = {}
            return {}

    def _find_join_path(
        self,
        database_id: int,
        fk_graph: Dict[str, Dict[str, Tuple[str, str]]],
        from_table: str,
        to_table: str,
        max_hops: int = 4
    ) -> Optional[List[str]]:
        """
        Find shortest path between two tables using BFS on FK relationships.
        """
        if from_table not in fk_graph and to_table not in fk_graph:
            return None if from_table == to_table else [from_table, to_table]
        
        # Build adjacency list (both directions)
        graph = defaultdict(set)
        for table, cols in fk_graph.items():
            for col, (ref_table, ref_col) in cols.items():
                graph[table].add(ref_table)
                graph[ref_table].add(table)
        
        # Get all table names for nodes that don't have FKs
        all_tables = self.db.query(Table).filter(
            Table.database_id == database_id
        ).all()
        for table in all_tables:
            # Ensure all tables are in graph
            if table.name not in graph:
                graph[table.name] = set()
        
        # BFS
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
            
            for neighbor in graph.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        
        return None

    def _path_to_join_conditions(
        self,
        fk_graph: Dict[str, Dict[str, Tuple[str, str]]],
        path: List[str]
    ) -> List[Dict[str, str]]:
        """
        Convert a table path to JOIN conditions.
        Returns list of {from_table, to_table, condition, from_col, to_col}
        """
        join_conditions = []
        
        for i in range(len(path) - 1):
            from_table = path[i]
            to_table = path[i + 1]
            condition = None
            from_col = None
            to_col = None
            
            # Check forward FK relationship
            if from_table in fk_graph:
                for col, (ref_table, ref_col) in fk_graph[from_table].items():
                    if ref_table == to_table:
                        from_col = col
                        to_col = ref_col
                        condition = f"{from_table}.{col} = {to_table}.{ref_col}"
                        break
            
            # Check reverse FK relationship
            if not condition and to_table in fk_graph:
                for col, (ref_table, ref_col) in fk_graph[to_table].items():
                    if ref_table == from_table:
                        from_col = ref_col
                        to_col = col
                        condition = f"{to_table}.{col} = {from_table}.{ref_col}"
                        break
            
            if condition:
                join_conditions.append({
                    "from_table": from_table,
                    "to_table": to_table,
                    "condition": condition,
                    "from_col": from_col,
                    "to_col": to_col
                })
        
        return join_conditions

    def close(self):
        if self.db:
            self.db.close()

    def __del__(self):
        self.close()
