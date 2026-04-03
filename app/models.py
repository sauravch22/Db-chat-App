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
    Per-database permission table.
    connection_id = NULL  →  global permission (can onboard new databases)
    connection_id = X     →  permission scoped to connection X
    Valid permission values: db_onboard, db_reindex, prompt_query
    """
    __tablename__ = "user_permissions"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    permission = SA_Column(String(50), nullable=False)  # db_onboard | db_reindex | prompt_query
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=True)
    created_at = SA_Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="permissions")
    connection = relationship("Connection")


# ============================================================================
# ACTIVITY LOG
# ============================================================================

class ActivityLog(Base):
    """
    Comprehensive activity log – every significant action is recorded here.

    Actions follow the pattern:  <resource>.<verb>
    ─────────────────────────────────────────────────
    auth.login              – User logged in
    auth.login_failed       – Bad credentials
    auth.signup             – New account created
    auth.token_refresh      – /me endpoint hit

    chat.query              – Natural language chat query
    chat.query_failed       – Chat query failed
    chat.execute            – Direct SQL execution
    chat.execute_failed     – Direct SQL execution failed

    admin.register_db       – New database registered
    admin.list_databases    – Databases listed
    admin.reindex           – Reindex triggered
    admin.view_audit        – Audit log viewed
    admin.view_summaries    – Table summaries viewed
    admin.update_summary    – Table summary edited
    admin.refresh_embeddings – Data embeddings refreshed

    perm.view_users         – User list viewed (global)
    perm.view_db_users      – User list for DB viewed
    perm.update             – Permission changed for user on DB
    perm.denied             – Permission denied (any route)
    """
    __tablename__ = "activity_logs"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username = SA_Column(String(100), nullable=True)          # denormalized for fast reads
    action = SA_Column(String(80), nullable=False, index=True)  # e.g. "chat.query"
    resource_type = SA_Column(String(50), nullable=True)       # e.g. "connection", "user", "table"
    resource_id = SA_Column(Integer, nullable=True)            # PK of the affected resource
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="SET NULL"), nullable=True)
    status = SA_Column(String(20), nullable=False, default="success")  # success | failed | denied
    detail = SA_Column(Text, nullable=True)                    # JSON blob with extra context
    ip_address = SA_Column(String(45), nullable=True)          # IPv4 or IPv6
    user_agent = SA_Column(String(512), nullable=True)
    duration_ms = SA_Column(Integer, nullable=True)            # how long the operation took
    created_at = SA_Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", foreign_keys=[user_id])
    connection = relationship("Connection", foreign_keys=[connection_id])


# ============================================================================
# CHAT HISTORY  –  persistent per-user chat messages
# ============================================================================

class ChatHistory(Base):
    """
    Stores every chat interaction so users see their own previous prompts
    and results when they log back in.
    Rows/columns are stored as JSON text (limited to first 50 rows).
    """
    __tablename__ = "chat_history"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True)
    prompt = SA_Column(Text, nullable=False)
    answer = SA_Column(Text, nullable=True)
    sql = SA_Column(Text, nullable=True)
    columns = SA_Column(Text, nullable=True)           # JSON array of column names
    rows = SA_Column(Text, nullable=True)               # JSON array of row dicts (max 50)
    row_count = SA_Column(Integer, nullable=True)
    execution_time_ms = SA_Column(Integer, nullable=True)
    selected_tables = SA_Column(Text, nullable=True)    # JSON array of table names
    status = SA_Column(String(20), nullable=False, default="success")  # success | error
    error_message = SA_Column(Text, nullable=True)
    thread_id = SA_Column(String(36), nullable=True, index=True)    # groups messages into a thread
    thread_title = SA_Column(String(255), nullable=True)             # auto-generated from first prompt
    tags = SA_Column(Text, nullable=True)  # JSON array of tag strings
    is_shared = SA_Column(Boolean, default=False)
    created_at = SA_Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", foreign_keys=[user_id])
    connection = relationship("Connection", foreign_keys=[connection_id])


# ============================================================================
# DASHBOARDS  –  pinned query/chart cards for quick re-run
# ============================================================================

class Dashboard(Base):
    """
    A named collection of pinned queries/charts owned by a single user.
    One user can have many dashboards; each dashboard holds many pins.
    """
    __tablename__ = "dashboards"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = SA_Column(String(255), nullable=False)
    description = SA_Column(Text, nullable=True)
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    pins = relationship("DashboardPin", back_populates="dashboard", cascade="all, delete",
                        order_by="DashboardPin.position")


class DashboardPin(Base):
    """
    A single pinned query+chart on a dashboard.

    Stores the original prompt, the generated SQL, and the chart configuration
    so the dashboard can re-execute the SQL for live data and re-render the
    exact same chart type without calling the viz-service again.
    """
    __tablename__ = "dashboard_pins"

    id = SA_Column(Integer, primary_key=True)
    dashboard_id = SA_Column(Integer, SA_ForeignKey("dashboards.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    pin_name = SA_Column(String(255), nullable=False)           # user-given label
    prompt = SA_Column(Text, nullable=False)                     # original NL prompt
    sql = SA_Column(Text, nullable=False)                        # generated SQL to re-run
    chart_type = SA_Column(String(50), nullable=False)           # bar | line | pie | scatter | area | table
    chart_config = SA_Column(Text, nullable=True)                # JSON – full viz-service rec config
    position = SA_Column(Integer, default=0)                     # ordering within dashboard
    last_run_at = SA_Column(DateTime, nullable=True)             # when SQL was last executed
    created_at = SA_Column(DateTime, default=datetime.utcnow)

    dashboard = relationship("Dashboard", back_populates="pins")
    connection = relationship("Connection")


# ============================================================================
# SAVED QUERIES  –  user-bookmarked queries for quick re-run
# ============================================================================

class SavedQuery(Base):
    """
    A bookmarked query that a user wants to keep for quick re-use.
    Stores the original prompt, generated SQL, and the connection it targets.
    """
    __tablename__ = "saved_queries"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True)
    name = SA_Column(String(255), nullable=False)
    prompt = SA_Column(Text, nullable=True)
    sql = SA_Column(Text, nullable=False)
    description = SA_Column(Text, nullable=True)
    folder = SA_Column(String(100), nullable=True)
    is_favorite = SA_Column(Boolean, default=False)
    run_count = SA_Column(Integer, default=0)
    last_run_at = SA_Column(DateTime, nullable=True)
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    annotations = relationship("QueryAnnotation", back_populates="saved_query", cascade="all, delete")
    user = relationship("User", foreign_keys=[user_id])
    connection = relationship("Connection", foreign_keys=[connection_id])


# ============================================================================
# QUERY ANNOTATIONS  –  notes/tags on results  (Feature 5)
# ============================================================================

class QueryAnnotation(Base):
    __tablename__ = "query_annotations"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    chat_history_id = SA_Column(Integer, SA_ForeignKey("chat_history.id", ondelete="CASCADE"), nullable=True)
    saved_query_id = SA_Column(Integer, SA_ForeignKey("saved_queries.id", ondelete="CASCADE"), nullable=True)
    note = SA_Column(Text, nullable=False)
    tags = SA_Column(Text, nullable=True)
    is_shared = SA_Column(Boolean, default=False)
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    connection = relationship("Connection", foreign_keys=[connection_id])
    saved_query = relationship("SavedQuery", back_populates="annotations")


# ============================================================================
# SCHEDULED QUERIES  –  recurring query execution  (Feature 6)
# ============================================================================

class ScheduledQuery(Base):
    __tablename__ = "scheduled_queries"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    saved_query_id = SA_Column(Integer, SA_ForeignKey("saved_queries.id", ondelete="CASCADE"), nullable=False)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    name = SA_Column(String(255), nullable=False)
    cron_expression = SA_Column(String(100), nullable=False)
    is_active = SA_Column(Boolean, default=True)
    alert_condition = SA_Column(Text, nullable=True)
    alert_email = SA_Column(String(255), nullable=True)
    last_run_at = SA_Column(DateTime, nullable=True)
    last_run_status = SA_Column(String(20), nullable=True)
    last_run_result = SA_Column(Text, nullable=True)
    last_run_row_count = SA_Column(Integer, nullable=True)
    next_run_at = SA_Column(DateTime, nullable=True)
    run_count = SA_Column(Integer, default=0)
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    saved_query = relationship("SavedQuery")
    connection = relationship("Connection", foreign_keys=[connection_id])


# ============================================================================
# WRITE-BACK REQUESTS  –  controlled data modifications  (Feature 7)
# ============================================================================

class WriteBackRequest(Base):
    __tablename__ = "writeback_requests"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    sql = SA_Column(Text, nullable=False)
    operation_type = SA_Column(String(20), nullable=False)
    target_table = SA_Column(String(255), nullable=False)
    affected_rows_estimate = SA_Column(Integer, nullable=True)
    status = SA_Column(String(20), nullable=False, default="pending")
    approved_by = SA_Column(Integer, SA_ForeignKey("users.id"), nullable=True)
    approved_at = SA_Column(DateTime, nullable=True)
    executed_at = SA_Column(DateTime, nullable=True)
    execution_result = SA_Column(Text, nullable=True)
    rows_affected = SA_Column(Integer, nullable=True)
    rollback_sql = SA_Column(Text, nullable=True)
    reason = SA_Column(Text, nullable=True)
    created_at = SA_Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    approver = relationship("User", foreign_keys=[approved_by])
    connection = relationship("Connection", foreign_keys=[connection_id])


# ============================================================================
# QUERY TEMPLATES  –  pre-built BI query patterns  (Sprint 4)
# ============================================================================

class QueryTemplate(Base):
    """A reusable query template with placeholder variables."""
    __tablename__ = "query_templates"

    id = SA_Column(Integer, primary_key=True)
    name = SA_Column(String(255), nullable=False)
    description = SA_Column(Text, nullable=True)
    category = SA_Column(String(100), nullable=False, index=True)
    db_type = SA_Column(String(50), nullable=True)
    sql_template = SA_Column(Text, nullable=False)
    variables = SA_Column(Text, nullable=True)  # JSON: [{"name":"table","label":"Table name","default":"orders"}]
    is_builtin = SA_Column(Boolean, default=True)
    created_by = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    use_count = SA_Column(Integer, default=0)
    created_at = SA_Column(DateTime, default=datetime.utcnow)
    updated_at = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================================
# TRAINING PAIRS  –  RAG / few-shot query examples
# ============================================================================


class TrainingPair(Base):
    """Stored question ↔ query pairs for retrieval-augmented generation."""
    __tablename__ = "training_pairs"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True)
    question = SA_Column(Text, nullable=False)
    query = SA_Column(Text, nullable=False)
    query_type = SA_Column(String(50), nullable=False, default="sql")
    is_verified = SA_Column(Boolean, default=False)
    upvotes = SA_Column(Integer, default=0)
    created_at = SA_Column(DateTime, default=datetime.utcnow)


# ============================================================================
# GENERATED API ENDPOINTS  –  saved query as REST slug
# ============================================================================


class GeneratedEndpoint(Base):
    """User-defined public API backed by a saved SELECT query."""
    __tablename__ = "generated_endpoints"

    id = SA_Column(Integer, primary_key=True)
    user_id = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    saved_query_id = SA_Column(Integer, SA_ForeignKey("saved_queries.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True)
    path_slug = SA_Column(String(255), nullable=False, unique=True, index=True)
    method = SA_Column(String(10), nullable=False, default="GET")
    api_key = SA_Column(String(64), nullable=False, index=True)
    description = SA_Column(Text, nullable=True)
    rate_limit = SA_Column(Integer, default=100)
    is_active = SA_Column(Boolean, default=True)
    call_count = SA_Column(Integer, default=0)
    created_at = SA_Column(DateTime, default=datetime.utcnow)
