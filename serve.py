"""Alternative entrypoint to run the app while main.py is being fixed."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.config import Settings
from app.api.routes import chat, admin, health, auth, activity, dashboard

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


@app.get("/")
async def root():
    return {"message": "DbChat API", "version": "1.0.0", "docs": "/docs"}
