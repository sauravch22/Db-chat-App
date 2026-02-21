"""DbChat - Clean entrypoint"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.config import Settings
from app.api.routes import chat, admin, health

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DbChat application...")
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
app.include_router(chat.router, tags=["Chat"])
app.include_router(admin.router, tags=["Admin"])


@app.get("/")
async def root():
    return {"message": "DbChat API", "version": "1.0.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT, reload=settings.DEBUG)
"""DbChat - Minimal, cleaned entrypoint"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.config import Settings
from app.api.routes import chat, admin, health

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DbChat application...")
    yield
    logger.info("Shutting down DbChat application...")


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(admin.router)


@app.get("/")
async def root():
    return {"message": "DbChat API", "version": "1.0.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT, reload=settings.DEBUG)
DbChat - Minimal entrypoint (fixed)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.config import Settings
from app.api.routes import chat, admin, health

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting DbChat application...")
    yield
    logger.info("Shutting down DbChat application...")


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(admin.router)

@app.get("/")
async def root():
    return {"message": "DbChat API", "version": "1.0.0", "docs": "/docs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT, reload=settings.DEBUG)
    """Startup and shutdown events"""
