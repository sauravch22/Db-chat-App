"""ERD diagram API — generates Mermaid ER diagram markup from schema."""

import logging
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.database import SessionLocal
from app.models import Connection, Database, Table, Column, ForeignKeyModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/erd", tags=["ERD Diagrams"])


@router.get("/{connection_id}")
async def get_erd(connection_id: int, user: dict = Depends(get_current_user)):
    """Generate a Mermaid ER diagram for the given connection."""
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == connection_id,
                                            Connection.is_active == True).first()
        if not conn:
            raise HTTPException(404, "Connection not found")

        db_record = db.query(Database).filter(Database.connection_id == connection_id).first()
        if not db_record:
            raise HTTPException(404, "No indexed database found")

        tables = db.query(Table).filter(Table.database_id == db_record.id).all()
        fks = db.query(ForeignKeyModel).filter(ForeignKeyModel.database_id == db_record.id).all()

        lines = ["erDiagram"]
        for table in tables:
            cols = db.query(Column).filter(Column.table_id == table.id).all()
            lines.append(f"    {table.name} {{")
            for col in cols:
                pk_marker = "PK" if col.is_primary_key else ""
                nullable = "" if col.is_nullable else "NOT NULL"
                dtype = (col.data_type or "TEXT").split("(")[0].upper()
                annotation = " ".join(filter(None, [pk_marker, nullable]))
                lines.append(f"        {dtype} {col.name} \"{annotation}\"")
            lines.append("    }")

        for fk in fks:
            lines.append(f"    {fk.table_name} }}o--|| {fk.referenced_table} : \"{fk.column_name}\"")

        mermaid = "\n".join(lines)

        return {
            "mermaid": mermaid,
            "table_count": len(tables),
            "relationship_count": len(fks),
            "connection_name": conn.name,
        }
    finally:
        db.close()
