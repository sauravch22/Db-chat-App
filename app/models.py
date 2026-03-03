"""Database models for metadata storage"""

from sqlalchemy import Column as SA_Column, Integer, String, Text, Boolean, DateTime, ForeignKey as SA_ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Connection(Base):
    """Database connection configuration"""
    __tablename__ = "connections"
    
    id = SA_Column(Integer, primary_key=True)
    name = SA_Column(String(255), unique=True, nullable=False)
    host = SA_Column(String(255), nullable=False)
    port = SA_Column(Integer, nullable=False)
    username = SA_Column(String(255), nullable=False)
    password = SA_Column(Text, nullable=False)
    password_encrypted = SA_Column(Text)
    database = SA_Column(String(255), nullable=False)
    database_type = SA_Column(String(50), nullable=False)
    is_active = SA_Column(Boolean, default=True)
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    databases = relationship("Database", back_populates="connection", cascade="all, delete")
    queries = relationship("Query", back_populates="connection", cascade="all, delete")


class Database(Base):
    """Database metadata"""
    __tablename__ = "databases"
    
    id = SA_Column(Integer, primary_key=True)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    name = SA_Column(String(255), nullable=False)
    row_count = SA_Column(Integer, default=0)
    last_indexed = SA_Column(DateTime)
    last_indexed_at = SA_Column(DateTime)
    schema_hash = SA_Column(String(64))
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    connection = relationship("Connection", back_populates="databases")
    tables = relationship("Table", back_populates="database", cascade="all, delete")


class Table(Base):
    """Table metadata"""
    __tablename__ = "tables"
    
    id = SA_Column(Integer, primary_key=True)
    database_id = SA_Column(Integer, SA_ForeignKey("databases.id", ondelete="CASCADE"), nullable=False)
    name = SA_Column(String(255), nullable=False)
    context = SA_Column(Text)
    embedding_id = SA_Column(String(255))
    sample_count = SA_Column(Integer, default=0)
    is_indexed = SA_Column(Boolean, default=False)
    last_indexed_at = SA_Column(DateTime)
    summary = SA_Column(Text)  # v2: Natural language table summary
    summary_generated_at = SA_Column(DateTime)  # v2: When summary was generated
    summary_human_override = SA_Column(Boolean, default=False)  # v2: True if human edited summary
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    database = relationship("Database", back_populates="tables")
    columns = relationship("Column", back_populates="table", cascade="all, delete")
    samples = relationship("Sample", back_populates="table", cascade="all, delete")


class Column(Base):
    """Column metadata"""
    __tablename__ = "columns"
    
    id = SA_Column(Integer, primary_key=True)
    table_id = SA_Column(Integer, SA_ForeignKey("tables.id", ondelete="CASCADE"), nullable=False)
    name = SA_Column(String(255), nullable=False)
    data_type = SA_Column(String(100), nullable=False)
    is_nullable = SA_Column(Boolean, default=True)
    context = SA_Column(Text)
    embedding_id = SA_Column(String(255))
    sample_values = SA_Column(Text)
    is_primary_key = SA_Column(Boolean, default=False)
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    table = relationship("Table", back_populates="columns")


class Sample(Base):
    """Sample data for tables"""
    __tablename__ = "samples"
    
    id = SA_Column(Integer, primary_key=True)
    table_id = SA_Column(Integer, SA_ForeignKey("tables.id", ondelete="CASCADE"), nullable=False)
    sample_data = SA_Column(Text, nullable=False)  # Store as JSON string
    embedding_id = SA_Column(String(255))
    generated_at = SA_Column(DateTime, default=datetime.utcnow)
    
    table = relationship("Table", back_populates="samples")


class Query(Base):
    """Query audit log"""
    __tablename__ = "queries"
    
    id = SA_Column(Integer, primary_key=True)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id"), nullable=False)
    user_prompt = SA_Column(Text, nullable=False)
    generated_sql = SA_Column(Text)
    result_status = SA_Column(String(50))
    error_message = SA_Column(Text)
    execution_time_ms = SA_Column(Integer)
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    
    connection = relationship("Connection", back_populates="queries")


class DataEmbeddingRefreshLog(Base):
    """Track data embedding refresh status per column"""
    __tablename__ = "data_embedding_refresh_log"
    
    id = SA_Column(Integer, primary_key=True)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    table_id = SA_Column(Integer, SA_ForeignKey("tables.id", ondelete="CASCADE"), nullable=False)
    column_id = SA_Column(Integer, SA_ForeignKey("columns.id", ondelete="CASCADE"), nullable=False)
    last_sampled_at = SA_Column(DateTime)  # When data was last sampled
    sample_count = SA_Column(Integer, default=0)  # Number of distinct values sampled
    refresh_status = SA_Column(String(50), default="pending")  # pending, in_progress, completed, failed
    error_message = SA_Column(Text)  # Error details if failed
    next_refresh_at = SA_Column(DateTime)  # Scheduled refresh time
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    connection = relationship("Connection")
    table = relationship("Table")
    column = relationship("Column")


class ForeignKeyModel(Base):
    """Foreign key relationship metadata"""
    __tablename__ = "foreign_keys"
    
    id = SA_Column(Integer, primary_key=True)
    database_id = SA_Column(Integer, SA_ForeignKey("databases.id", ondelete="CASCADE"), nullable=False)
    table_name = SA_Column(String(255), nullable=False)  # Source table
    column_name = SA_Column(String(255), nullable=False)  # Source column
    referenced_table = SA_Column(String(255), nullable=False)  # Target table
    referenced_column = SA_Column(String(255), nullable=False)  # Target column
    constraint_name = SA_Column(String(255))  # FK constraint name from database
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    database = relationship("Database")


# ============================================================================
# AUTH MODELS
# ============================================================================

class User(Base):
    """Application user"""
    __tablename__ = "users"

    id = SA_Column(Integer, primary_key=True)
    username = SA_Column(String(100), unique=True, nullable=False, index=True)
    password_hash = SA_Column(Text, nullable=False)
    is_active = SA_Column(Boolean, default=True)
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    permissions = relationship("UserPermission", back_populates="user", cascade="all, delete")


class UserPermission(Base):
    """
    Many-to-many-style permission table.
    Valid permission values: db_onboard, db_reindex, prompt_query
    """
    __tablename__ = "user_permissions"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    permission = SA_Column(String(50), nullable=False)  # db_onboard | db_reindex | prompt_query
    created_at = SA_Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="permissions")
