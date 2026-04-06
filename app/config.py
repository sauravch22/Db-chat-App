"""Configuration management for DbChat"""

import secrets
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Database
    DB_HOST: str = Field(default="postgres", alias="DB_HOST")
    DB_PORT: int = Field(default=5432, alias="DB_PORT")
    DB_NAME: str = Field(default="dbchat_metadata", alias="DB_NAME")
    DB_USER: str = Field(default="dbchat", alias="DB_USER")
    DB_PASSWORD: str = Field(default="dbchat_secure_password", alias="DB_PASSWORD")
    
    # Redis
    REDIS_URL: str = Field(default="redis://redis:6379", alias="REDIS_URL")
    
    # Qdrant Vector DB
    QDRANT_URL: str = Field(default="http://qdrant:6333", alias="QDRANT_URL")
    QDRANT_API_KEY: str = Field(default="your_qdrant_api_key_here", alias="QDRANT_API_KEY")
    QDRANT_COLLECTION: str = Field(default="dbchat_embeddings", alias="QDRANT_COLLECTION")
    
    # LLM provider: ollama_local | openai | anthropic | custom
    LLM_PROVIDER: str = Field(default="ollama_local", alias="LLM_PROVIDER")
    LLM_API_URL: str = Field(default="http://localhost:11434", alias="LLM_API_URL")
    LLM_MODEL_NAME: str = Field(default="mistral", alias="LLM_MODEL_NAME")
    LLM_API_KEY: str = Field(default="", alias="LLM_API_KEY")
    LLM_TIMEOUT_SEC: float = Field(default=120.0, alias="LLM_TIMEOUT_SEC")
    LLM_MAX_TOKENS: int = Field(default=512, alias="LLM_MAX_TOKENS")
    
    # Ollama (local — used for embeddings only)
    OLLAMA_URL: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    OLLAMA_LLM_MODEL: str = Field(default="mistral", alias="OLLAMA_LLM_MODEL")
    OLLAMA_EMBEDDING_MODEL: str = Field(default="nomic-embed-text", alias="OLLAMA_EMBEDDING_MODEL")
    
    # Ollama Context and Timeout Settings
    OLLAMA_SQL_NUM_CTX: int = Field(default=4096, alias="OLLAMA_SQL_NUM_CTX")
    OLLAMA_EMBED_NUM_CTX: int = Field(default=2048, alias="OLLAMA_EMBED_NUM_CTX")
    OLLAMA_CLASSIFY_NUM_CTX: int = Field(default=4096, alias="OLLAMA_CLASSIFY_NUM_CTX")
    OLLAMA_GENERATE_TIMEOUT_SEC: float = Field(default=60.0, alias="OLLAMA_GENERATE_TIMEOUT_SEC")
    OLLAMA_EMBED_TIMEOUT_SEC: float = Field(default=30.0, alias="OLLAMA_EMBED_TIMEOUT_SEC")
    OLLAMA_CLASSIFY_TIMEOUT_SEC: float = Field(default=30.0, alias="OLLAMA_CLASSIFY_TIMEOUT_SEC")
    
    # Security
    JWT_SECRET: str = Field(default="", alias="JWT_SECRET")
    ADMIN_DEFAULT_PASSWORD: str = Field(default="", alias="ADMIN_DEFAULT_PASSWORD")
    ALLOWED_ORIGINS: str = Field(default="http://localhost:3000", alias="ALLOWED_ORIGINS")

    # Application
    APP_ENV: str = Field(default="development", alias="APP_ENV")
    DEBUG: bool = Field(default=False, alias="DEBUG")
    LOG_LEVEL: str = Field(default="INFO", alias="LOG_LEVEL")
    
    # API
    API_HOST: str = Field(default="0.0.0.0", alias="API_HOST")
    API_PORT: int = Field(default=8000, alias="API_PORT")
    
    # SQL Generation - Reasoning Mode (Phase 3 Enhancement)
    # Enabled for Mistral - helps with reasoning steps before SQL generation
    USE_REASONING_MODE: bool = Field(default=True, alias="USE_REASONING_MODE")

    # ── Per-task model routing ──
    # Each role can override the default provider/model.
    # Format: LLM_ROLE_<ROLE>_PROVIDER, LLM_ROLE_<ROLE>_MODEL, LLM_ROLE_<ROLE>_API_URL, LLM_ROLE_<ROLE>_API_KEY
    # Roles: classify, sql_generate, reasoning, summarize, nosql, explain, general
    LLM_ROLE_CLASSIFY_PROVIDER: str = Field(default="", alias="LLM_ROLE_CLASSIFY_PROVIDER")
    LLM_ROLE_CLASSIFY_MODEL: str = Field(default="", alias="LLM_ROLE_CLASSIFY_MODEL")
    LLM_ROLE_CLASSIFY_API_URL: str = Field(default="", alias="LLM_ROLE_CLASSIFY_API_URL")
    LLM_ROLE_CLASSIFY_API_KEY: str = Field(default="", alias="LLM_ROLE_CLASSIFY_API_KEY")

    LLM_ROLE_SQL_GENERATE_PROVIDER: str = Field(default="", alias="LLM_ROLE_SQL_GENERATE_PROVIDER")
    LLM_ROLE_SQL_GENERATE_MODEL: str = Field(default="", alias="LLM_ROLE_SQL_GENERATE_MODEL")
    LLM_ROLE_SQL_GENERATE_API_URL: str = Field(default="", alias="LLM_ROLE_SQL_GENERATE_API_URL")
    LLM_ROLE_SQL_GENERATE_API_KEY: str = Field(default="", alias="LLM_ROLE_SQL_GENERATE_API_KEY")

    LLM_ROLE_REASONING_PROVIDER: str = Field(default="", alias="LLM_ROLE_REASONING_PROVIDER")
    LLM_ROLE_REASONING_MODEL: str = Field(default="", alias="LLM_ROLE_REASONING_MODEL")
    LLM_ROLE_REASONING_API_URL: str = Field(default="", alias="LLM_ROLE_REASONING_API_URL")
    LLM_ROLE_REASONING_API_KEY: str = Field(default="", alias="LLM_ROLE_REASONING_API_KEY")

    LLM_ROLE_SUMMARIZE_PROVIDER: str = Field(default="", alias="LLM_ROLE_SUMMARIZE_PROVIDER")
    LLM_ROLE_SUMMARIZE_MODEL: str = Field(default="", alias="LLM_ROLE_SUMMARIZE_MODEL")
    LLM_ROLE_SUMMARIZE_API_URL: str = Field(default="", alias="LLM_ROLE_SUMMARIZE_API_URL")
    LLM_ROLE_SUMMARIZE_API_KEY: str = Field(default="", alias="LLM_ROLE_SUMMARIZE_API_KEY")

    LLM_ROLE_NOSQL_PROVIDER: str = Field(default="", alias="LLM_ROLE_NOSQL_PROVIDER")
    LLM_ROLE_NOSQL_MODEL: str = Field(default="", alias="LLM_ROLE_NOSQL_MODEL")
    LLM_ROLE_NOSQL_API_URL: str = Field(default="", alias="LLM_ROLE_NOSQL_API_URL")
    LLM_ROLE_NOSQL_API_KEY: str = Field(default="", alias="LLM_ROLE_NOSQL_API_KEY")

    LLM_ROLE_EXPLAIN_PROVIDER: str = Field(default="", alias="LLM_ROLE_EXPLAIN_PROVIDER")
    LLM_ROLE_EXPLAIN_MODEL: str = Field(default="", alias="LLM_ROLE_EXPLAIN_MODEL")
    LLM_ROLE_EXPLAIN_API_URL: str = Field(default="", alias="LLM_ROLE_EXPLAIN_API_URL")
    LLM_ROLE_EXPLAIN_API_KEY: str = Field(default="", alias="LLM_ROLE_EXPLAIN_API_KEY")

    LLM_ROLE_GENERAL_PROVIDER: str = Field(default="", alias="LLM_ROLE_GENERAL_PROVIDER")
    LLM_ROLE_GENERAL_MODEL: str = Field(default="", alias="LLM_ROLE_GENERAL_MODEL")
    LLM_ROLE_GENERAL_API_URL: str = Field(default="", alias="LLM_ROLE_GENERAL_API_URL")
    LLM_ROLE_GENERAL_API_KEY: str = Field(default="", alias="LLM_ROLE_GENERAL_API_KEY")

    model_config = {
        "env_file": ".env",
        "case_sensitive": True
    }
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.JWT_SECRET:
            import logging
            logging.getLogger(__name__).warning(
                "JWT_SECRET not set — generating a random secret. "
                "Set JWT_SECRET in .env for stable tokens across restarts."
            )
            object.__setattr__(self, "JWT_SECRET", secrets.token_urlsafe(48))
        if not self.ADMIN_DEFAULT_PASSWORD:
            object.__setattr__(self, "ADMIN_DEFAULT_PASSWORD", secrets.token_urlsafe(16))

    @property
    def DATABASE_URL(self) -> str:
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD)
        return f"postgresql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
