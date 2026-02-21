"""Ollama LLM Service"""

import httpx
import json
import logging
from app.config import Settings

logger = logging.getLogger(__name__)

settings = Settings()


class OllamaService:
    """Service for interacting with Ollama LLM"""
    
    def __init__(self):
        self.base_url = settings.OLLAMA_URL
        self.llm_model = settings.OLLAMA_LLM_MODEL
        self.embedding_model = settings.OLLAMA_EMBEDDING_MODEL
    
    async def generate_sql(
        self,
        user_prompt: str,
        schema_context: str,
        sample_info: str
    ) -> str:
        """Generate SQL query from natural language"""
        
        system_prompt = """You are a SQL expert. Generate a single SQL query to answer the user question.

IMPORTANT RULES:
1. Only use SELECT statements
2. Return ONLY the SQL query, no explanation
3. Use the provided table schema
4. Generate valid SQL that can execute immediately
5. Do NOT make assumptions about column names not provided"""
        
        full_prompt = f"""
{schema_context}

Sample data patterns:
{sample_info}

User Question: {user_prompt}

Generate the SQL query:
"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.llm_model,
                        "prompt": full_prompt,
                        "system": system_prompt,
                        "stream": False,
                        "temperature": 0.7,
                    },
                    timeout=60.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    sql = result.get("response", "").strip()
                    # Remove markdown code blocks if present
                    sql = sql.replace("```sql\n", "").replace("```", "").strip()
                    return sql
                else:
                    logger.error(f"Ollama error: {response.text}")
                    raise Exception(f"Ollama returned status code {response.status_code}")
        
        except Exception as e:
            logger.error(f"Error generating SQL: {str(e)}")
            raise
    
    async def embed_text(self, text: str) -> list:
        """Generate embedding for text"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={
                        "model": self.embedding_model,
                        "input": text,
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("embeddings", [[]])[0]
                else:
                    logger.error(f"Ollama embedding error: {response.text}")
                    raise Exception(f"Ollama returned status code {response.status_code}")
        
        except Exception as e:
            logger.error(f"Error embedding text: {str(e)}")
            raise

    async def classify_intent(self, text: str) -> str:
        """Classify user prompt intent using Ollama. Returns one of: 'catalog' or 'data'."""
        system = (
            "You are a classifier that decides whether the user's prompt is a catalog/introspection request "
            "(about schema, indexes, connections, slow queries, table lists) or a data query that should be "
            "converted to an executable SQL against the user's database. Respond with a single word: 'catalog' or 'data'."
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.llm_model,
                        "prompt": text,
                        "system": system,
                        "stream": False,
                        "temperature": 0.0,
                    },
                    timeout=15.0
                )

                if response.status_code == 200:
                    result = response.json()
                    out = result.get("response", "").strip().lower()
                    if "catalog" in out:
                        return "catalog"
                    return "data"
                else:
                    logger.error(f"Ollama classify error: {response.text}")
                    return "data"

        except Exception as e:
            logger.error(f"Error classifying intent: {str(e)}")
            return "data"
    
    async def health_check(self) -> bool:
        """Check if Ollama is running"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/tags",
                    timeout=5.0
                )
                return response.status_code == 200
        except:
            return False
