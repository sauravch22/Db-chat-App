"""Schema Explorer API – visual schema map with tables, columns, and FK relationships."""

import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query as QParam
from pydantic import BaseModel
import logging

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import Connection, Database, Table, Column, ForeignKeyModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/schema", tags=["Schema Explorer"])


class ColumnInfo(BaseModel):
    id: int
    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool
    sample_values: Optional[str] = None


class TableInfo(BaseModel):
    id: int
    name: str
    column_count: int
    row_count: Optional[int] = None
    summary: Optional[str] = None
    columns: List[ColumnInfo] = []


class ForeignKeyInfo(BaseModel):
    id: int
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    constraint_name: Optional[str] = None


class SchemaResponse(BaseModel):
    connection_id: int
    database_name: str
    tables: List[TableInfo]
    foreign_keys: List[ForeignKeyInfo]
    table_count: int


@router.get("/explorer/{connection_id}", response_model=SchemaResponse)
async def get_schema(
    connection_id: int,
    user: dict = Depends(get_current_user),
):
    """Get full schema for a connection including tables, columns, and FK relationships."""
    if not has_db_permission(user, connection_id, "prompt_query"):
        raise HTTPException(status_code=403, detail="Permission required")
    
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == connection_id).first()
        if not conn:
            raise HTTPException(404, "Connection not found")
        
        databases = db.query(Database).filter(Database.connection_id == connection_id).all()
        if not databases:
            return SchemaResponse(connection_id=connection_id, database_name="", tables=[], foreign_keys=[], table_count=0)
        
        db_obj = databases[0]
        tables = db.query(Table).filter(Table.database_id.in_([d.id for d in databases])).all()
        
        table_infos = []
        for t in tables:
            cols = db.query(Column).filter(Column.table_id == t.id).all()
            table_infos.append(TableInfo(
                id=t.id,
                name=t.name,
                column_count=len(cols),
                row_count=t.sample_count,
                summary=t.summary or t.context,
                columns=[ColumnInfo(
                    id=c.id, name=c.name, data_type=c.data_type,
                    is_nullable=c.is_nullable if c.is_nullable is not None else True,
                    is_primary_key=c.is_primary_key if c.is_primary_key is not None else False,
                    sample_values=c.sample_values,
                ) for c in cols]
            ))
        
        fks = db.query(ForeignKeyModel).filter(
            ForeignKeyModel.database_id.in_([d.id for d in databases])
        ).all()
        
        fk_infos = [ForeignKeyInfo(
            id=fk.id,
            source_table=fk.table_name,
            source_column=fk.column_name,
            target_table=fk.referenced_table,
            target_column=fk.referenced_column,
            constraint_name=fk.constraint_name,
        ) for fk in fks]
        
        return SchemaResponse(
            connection_id=connection_id,
            database_name=db_obj.name,
            tables=table_infos,
            foreign_keys=fk_infos,
            table_count=len(table_infos),
        )
    finally:
        db.close()


@router.get("/table/{table_id}")
async def get_table_detail(table_id: int, user: dict = Depends(get_current_user)):
    """Get detailed info for a single table."""
    db = SessionLocal()
    try:
        table = db.query(Table).filter(Table.id == table_id).first()
        if not table:
            raise HTTPException(404, "Table not found")
        
        database = db.query(Database).filter(Database.id == table.database_id).first()
        if not database or not has_db_permission(user, database.connection_id, "prompt_query"):
            raise HTTPException(403, "Permission required")
        
        cols = db.query(Column).filter(Column.table_id == table.id).all()
        
        # Get FK relationships involving this table
        fks_out = db.query(ForeignKeyModel).filter(
            ForeignKeyModel.database_id == database.id,
            ForeignKeyModel.table_name == table.name
        ).all()
        fks_in = db.query(ForeignKeyModel).filter(
            ForeignKeyModel.database_id == database.id,
            ForeignKeyModel.referenced_table == table.name
        ).all()
        
        return {
            "table": TableInfo(
                id=table.id, name=table.name, column_count=len(cols),
                row_count=table.sample_count, summary=table.summary or table.context,
                columns=[ColumnInfo(
                    id=c.id, name=c.name, data_type=c.data_type,
                    is_nullable=c.is_nullable if c.is_nullable is not None else True,
                    is_primary_key=c.is_primary_key if c.is_primary_key is not None else False,
                    sample_values=c.sample_values,
                ) for c in cols]
            ),
            "outgoing_fks": [{"source_col": fk.column_name, "target_table": fk.referenced_table, "target_col": fk.referenced_column} for fk in fks_out],
            "incoming_fks": [{"source_table": fk.table_name, "source_col": fk.column_name, "target_col": fk.referenced_column} for fk in fks_in],
        }
    finally:
        db.close()
