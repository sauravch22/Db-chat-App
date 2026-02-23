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
        
        # Extract exact table names from the schema context to enforce as hard constraints
        exact_tables = [
            line.split("Table:", 1)[1].strip()
            for line in schema_context.splitlines()
            if line.startswith("Table:")
        ]
        table_list_str = ", ".join(exact_tables) if exact_tables else "(see schema)"

        system_prompt = f"""You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter, do NOT pluralize, singularize, or change them in any way): {table_list_str}
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
7. Do not wrap the query in markdown code fences"""

        full_prompt = f"""Schema:
{schema_context}

User Question: {user_prompt}

SQL query:"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.llm_model,
                        "prompt": full_prompt,
                        "system": system_prompt,
                        "stream": False,
                        "temperature": 0.0,
                    },
                    timeout=60.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    sql = result.get("response", "").strip()
                    # Strip markdown code fences
                    sql = sql.replace("```sql", "").replace("```", "").strip()
                    # If LLM added explanation text before SELECT, extract from SELECT onwards
                    upper = sql.upper()
                    select_pos = upper.find("SELECT")
                    if select_pos > 0:
                        sql = sql[select_pos:]
                    # Strip trailing explanation after the semicolon
                    if ";" in sql:
                        sql = sql[:sql.index(";") + 1]
                    return sql.strip()
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
            "You are a query classifier. Classify the user prompt into exactly one of two categories:\n"
            "\n"
            "catalog: The user is asking about DATABASE STRUCTURE or SYSTEM METADATA only.\n"
            "  Examples: 'show me the schema of artist table', 'what indexes exist on invoice?',\n"
            "  'how many open connections are there?', 'list all tables', 'show slow queries'\n"
            "\n"
            "data: The user wants to RETRIEVE, COUNT, FILTER or AGGREGATE actual data rows.\n"
            "  Examples: 'give all artists', 'how many albums are there?', 'show me all tracks',\n"
            "  'list all customers', 'give me all rows from artist', 'show all employees'\n"
            "\n"
            "IMPORTANT: Any prompt that asks to 'give', 'show', 'list', 'get', 'fetch', 'find' or "
            "'count' actual records is ALWAYS 'data', even if it mentions a table name.\n"
            "Respond with a single word only: catalog or data."
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
