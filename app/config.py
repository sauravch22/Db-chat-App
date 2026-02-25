"""Configuration management for DbChat"""

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
    
    # Ollama LLM (local with Metal GPU acceleration on M5 Mac)
    OLLAMA_URL: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    OLLAMA_LLM_MODEL: str = Field(default="mistral", alias="OLLAMA_LLM_MODEL")
    OLLAMA_EMBEDDING_MODEL: str = Field(default="nomic-embed-text", alias="OLLAMA_EMBEDDING_MODEL")
    
    # Ollama Context and Timeout Settings
    OLLAMA_SQL_NUM_CTX: int = Field(default=4096, alias="OLLAMA_SQL_NUM_CTX")
    OLLAMA_EMBED_NUM_CTX: int = Field(default=2048, alias="OLLAMA_EMBED_NUM_CTX")
    OLLAMA_CLASSIFY_NUM_CTX: int = Field(default=4096, alias="OLLAMA_CLASSIFY_NUM_CTX")
    # Metal GPU acceleration on local Ollama (M5 MacBook) - much faster than CPU-only Docker
    OLLAMA_GENERATE_TIMEOUT_SEC: float = Field(default=60.0, alias="OLLAMA_GENERATE_TIMEOUT_SEC")
    OLLAMA_EMBED_TIMEOUT_SEC: float = Field(default=30.0, alias="OLLAMA_EMBED_TIMEOUT_SEC")
    OLLAMA_CLASSIFY_TIMEOUT_SEC: float = Field(default=30.0, alias="OLLAMA_CLASSIFY_TIMEOUT_SEC")
    
    # Application
    APP_ENV: str = Field(default="development", alias="APP_ENV")
    DEBUG: bool = Field(default=True, alias="DEBUG")
    LOG_LEVEL: str = Field(default="DEBUG", alias="LOG_LEVEL")
    
    # API
    API_HOST: str = Field(default="0.0.0.0", alias="API_HOST")
    API_PORT: int = Field(default=8000, alias="API_PORT")
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": True
    }
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
