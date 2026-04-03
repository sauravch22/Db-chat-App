"""Alternative entrypoint to run the app while main.py is being fixed."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.config import Settings
from app.api.routes import (chat, admin, health, auth, activity, dashboard,
                            saved_queries, schema_explorer, query_validation,
                            suggestions, annotations, scheduled, writeback,
                            workbench, lineage, intelligence,
                            llm_settings, summarize, templates, cross_db,
                            nosql, connection_test, file_upload, erd,
                            training, optimizer, data_quality,
                            api_generator, migration, pipeline,
                            collab, embed)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DbChat application...")
    # Auto-create tables on startup
    from app.database import engine
    from app.models import Base
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured (incl. users, user_permissions)")

    # Migration: add connection_id column to user_permissions if missing
    from sqlalchemy import text, inspect as sa_inspect
    with engine.connect() as conn:
        insp = sa_inspect(engine)
        cols = [c["name"] for c in insp.get_columns("user_permissions")]
        if "connection_id" not in cols:
            conn.execute(text(
                "ALTER TABLE user_permissions "
                "ADD COLUMN connection_id INTEGER REFERENCES connections(id) ON DELETE CASCADE"
            ))
            conn.commit()
            logger.info("Migrated: added connection_id column to user_permissions")

    # Migration: add thread_id / thread_title columns to chat_history
    with engine.connect() as conn:
        insp = sa_inspect(engine)
        if "chat_history" in insp.get_table_names():
            cols = [c["name"] for c in insp.get_columns("chat_history")]
            if "thread_id" not in cols:
                conn.execute(text(
                    "ALTER TABLE chat_history ADD COLUMN thread_id VARCHAR(36)"
                ))
                conn.execute(text(
                    "CREATE INDEX ix_chat_history_thread_id ON chat_history(thread_id)"
                ))
                conn.commit()
                logger.info("Migrated: added thread_id column to chat_history")
            if "thread_title" not in cols:
                conn.execute(text(
                    "ALTER TABLE chat_history ADD COLUMN thread_title VARCHAR(255)"
                ))
                conn.commit()
                logger.info("Migrated: added thread_title column to chat_history")

    # Migration: add v2 table summary columns if missing
    with engine.connect() as conn:
        insp = sa_inspect(engine)
        if "tables" in insp.get_table_names():
            cols = [c["name"] for c in insp.get_columns("tables")]
            changed = False
            if "summary" not in cols:
                conn.execute(text("ALTER TABLE tables ADD COLUMN summary TEXT"))
                changed = True
                logger.info("Migrated: added summary column to tables")
            if "summary_generated_at" not in cols:
                conn.execute(text("ALTER TABLE tables ADD COLUMN summary_generated_at TIMESTAMP"))
                changed = True
                logger.info("Migrated: added summary_generated_at column to tables")
            if "summary_human_override" not in cols:
                conn.execute(text("ALTER TABLE tables ADD COLUMN summary_human_override BOOLEAN DEFAULT FALSE"))
                changed = True
                logger.info("Migrated: added summary_human_override column to tables")
            if changed:
                conn.commit()

    # Migration: add is_primary_key column to columns table if missing
    with engine.connect() as conn:
        insp = sa_inspect(engine)
        if "columns" in insp.get_table_names():
            cols = [c["name"] for c in insp.get_columns("columns")]
            if "is_primary_key" not in cols:
                conn.execute(text("ALTER TABLE columns ADD COLUMN is_primary_key BOOLEAN DEFAULT FALSE"))
                conn.execute(text("UPDATE columns SET is_primary_key = FALSE WHERE is_primary_key IS NULL"))
                conn.commit()
                logger.info("Migrated: added is_primary_key column to columns")

    # Migration: add tags + is_shared to chat_history if missing
    with engine.connect() as conn:
        insp = sa_inspect(engine)
        if "chat_history" in insp.get_table_names():
            cols = [c["name"] for c in insp.get_columns("chat_history")]
            changed = False
            if "tags" not in cols:
                conn.execute(text("ALTER TABLE chat_history ADD COLUMN tags TEXT"))
                changed = True
            if "is_shared" not in cols:
                conn.execute(text("ALTER TABLE chat_history ADD COLUMN is_shared BOOLEAN DEFAULT FALSE"))
                changed = True
            if changed:
                conn.commit()
                logger.info("Migrated: added tags/is_shared columns to chat_history")

    # Seed default admin user with global + per-DB permissions
    from app.database import SessionLocal
    from app.services.auth_service import (
        get_user_by_username, create_user,
        set_db_permissions, grant_all_on_connection,
    )
    from app.models import Connection
    db = SessionLocal()
    try:
        admin = get_user_by_username(db, "admin")
        if not admin:
            admin = create_user(db, "admin", "admin123")
            logger.info("Default admin user created (admin / admin123)")

        # Ensure admin has exactly db_onboard as global perm (clean up old rows)
        set_db_permissions(db, admin.id, None, ["db_onboard"])

        # Ensure admin has all permissions on every existing connection
        connections = db.query(Connection).filter(Connection.is_active == True).all()
        for c in connections:
            grant_all_on_connection(db, admin.id, c.id)
        if connections:
            logger.info(f"Admin granted all permissions on {len(connections)} existing connections")
    finally:
        db.close()

    yield
    logger.info("Shutting down DbChat application...")


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, tags=["Auth"])
app.include_router(chat.router, tags=["Chat"])
app.include_router(admin.router, tags=["Admin"])
app.include_router(activity.router, tags=["Activity"])
app.include_router(dashboard.router, tags=["Dashboard"])
app.include_router(saved_queries.router, tags=["Saved Queries"])
app.include_router(schema_explorer.router, tags=["Schema Explorer"])
app.include_router(query_validation.router, tags=["Query Validation"])
app.include_router(suggestions.router, tags=["Suggestions"])
app.include_router(annotations.router, tags=["Annotations"])
app.include_router(scheduled.router, tags=["Scheduled Queries"])
app.include_router(writeback.router, tags=["Write-Back"])
app.include_router(workbench.router, tags=["Workbench"])
app.include_router(lineage.router, tags=["Data Lineage"])
app.include_router(intelligence.router, tags=["Connection Intelligence"])
app.include_router(llm_settings.router, tags=["LLM Settings"])
app.include_router(summarize.router, tags=["Data Summarization"])
app.include_router(templates.router, tags=["Query Templates"])
app.include_router(cross_db.router, tags=["Cross-Database"])
app.include_router(nosql.router, tags=["NoSQL"])
app.include_router(connection_test.router, tags=["Connection Test"])
app.include_router(file_upload.router, tags=["File Upload"])
app.include_router(erd.router, tags=["ERD Diagrams"])
app.include_router(training.router, tags=["Training / RAG"])
app.include_router(optimizer.router, tags=["Query Optimizer"])
app.include_router(data_quality.router, tags=["Data Quality"])
app.include_router(api_generator.router, tags=["API Generator"])
app.include_router(migration.router, tags=["Schema Migration"])
app.include_router(pipeline.router, tags=["Data Pipeline"])
app.include_router(collab.router, tags=["Collaboration"])
app.include_router(embed.router, tags=["Embeddable Widget"])


@app.get("/")
async def root():
    return {"message": "DbChat API", "version": "1.0.0", "docs": "/docs"}
