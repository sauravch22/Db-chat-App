"""Metadata service for schema and table summaries"""

import logging
from typing import List, Dict, Optional

from app.database import SessionLocal
from app.models import Database, Table, Column

logger = logging.getLogger(__name__)


class MetadataService:
    """Service for retrieving schema metadata and table summaries"""

    def __init__(self):
        self.db = SessionLocal()

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
        """Return comprehensive schema context with all constraints and metadata."""
        try:
            import json
            context_parts: List[str] = []
            
            # Get all tables to detect FK relationships
            all_tables = self.db.query(Table).filter(
                Table.database_id.in_(
                    self.db.query(Database.id).filter(
                        Database.connection_id == connection_id
                    )
                )
            ).all()
            all_table_names = {t.name: t.id for t in all_tables}
            
            for table_name in table_names:
                table = self.db.query(Table).filter(
                    Table.database_id.in_(
                        self.db.query(Database.id).filter(
                            Database.connection_id == connection_id
                        )
                    ),
                    Table.name == table_name
                ).first()
                if not table:
                    continue
                    
                columns = self.db.query(Column).filter(
                    Column.table_id == table.id
                ).all()
                
                # Build comprehensive schema
                context_str = f"Table: {table_name}\n"
                context_str += f"Rows: ~{table.sample_count if table.sample_count else '?'}\n\n"
                context_str += "Columns:\n"
                
                # Detailed column information
                col_details = []
                for col in columns:
                    col_info = f"  {col.name}: {col.data_type}"
                    
                    # Add constraints
                    constraints = []
                    
                    # Primary key detection (common pattern: table_id)
                    if col.name == f"{table_name}_id":
                        constraints.append("PRIMARY KEY")
                    
                    # NOT NULL constraint
                    if not col.is_nullable:
                        constraints.append("NOT NULL")
                    
                    if constraints:
                        col_info += f" [{', '.join(constraints)}]"
                    
                    # Add sample values if available (from v2 data-variation sampling)
                    if col.sample_values:
                        try:
                            samples = json.loads(col.sample_values)
                            sample_str = ", ".join([str(s)[:20] for s in samples[:5]])
                            col_info += f" | Sample values: {sample_str}"
                        except:
                            pass
                    
                    col_details.append(col_info)
                
                context_str += "\n".join(col_details)
                
                # Infer FK relationships based on column naming patterns
                fk_relationships = []
                for col in columns:
                    # Check if column name suggests a FK
                    if col.name.endswith('_id') and col.name != f"{table_name}_id":
                        # Extract potential referenced table name
                        potential_fk_table = col.name[:-3]  # Remove '_id'
                        if potential_fk_table in all_table_names:
                            fk_info = f"  {col.name} → {potential_fk_table}({potential_fk_table}_id)"
                            # Add nullable info for FK
                            if col.is_nullable:
                                fk_info += " [OPTIONAL]"
                            fk_relationships.append(fk_info)
                
                # Add FK section
                if fk_relationships:
                    context_str += "\n\nForeign Keys:\n" + "\n".join(fk_relationships)
                
                # Add relationship summary for clarity
                context_str += f"\n\nJoin Guide:\n  To join {table_name} with other tables:\n"
                for col in columns:
                    if col.name.endswith('_id') and col.name != f"{table_name}_id":
                        potential_fk_table = col.name[:-3]
                        if potential_fk_table in all_table_names:
                            context_str += f"  - Use: {table_name}.{col.name} = {potential_fk_table}.{col.name}\n"
                
                context_parts.append(context_str)
            
            return "\n\n" + "=" * 70 + "\n".join(context_parts) if context_parts else None
        except Exception as e:
            logger.error(f"Error building schema context: {str(e)}")
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

    def close(self):
        if self.db:
            self.db.close()

    def __del__(self):
        self.close()
