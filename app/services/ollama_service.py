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
            logger.debug(f"SQL generation: model={self.llm_model}, base_url={self.base_url}")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.llm_model,
                        "prompt": full_prompt,
                        "system": system_prompt,
                        "stream": False,
                        "temperature": 0.0,
                        "options": {
                            "num_ctx": settings.OLLAMA_SQL_NUM_CTX,
                        },
                    },
                    timeout=settings.OLLAMA_GENERATE_TIMEOUT_SEC
                )
                
                logger.debug(f"SQL generation response status: {response.status_code}")
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
                    # CRITICAL FIX: Remove trailing quotes that LLM sometimes adds
                    sql = sql.rstrip('"').rstrip("'").strip()
                    return sql
                else:
                    logger.error(f"Ollama error (status {response.status_code}): {response.text}")
                    raise Exception(f"Ollama returned status code {response.status_code}")
        
        except Exception as e:
            logger.error(f"Error generating SQL: {str(e)}")
            raise

    async def identify_tables(self, user_prompt: str, table_summaries: list) -> list:
        """Identify relevant tables from provided summaries. Returns list of exact table names."""
        if not table_summaries:
            return []

        summaries_text = "\n".join(
            [f"- {t['name']}: {t['summary']}" for t in table_summaries]
        )

        system_prompt = (
            "You are a database table selector. "
            "Given a user question and a list of table summaries, return a JSON array "
            "of the exact table names that are required to answer the question. "
            "ONLY use names from the provided list. Return JSON only."
        )

        prompt = (
            f"User Question: {user_prompt}\n\n"
            f"Available Tables:\n{summaries_text}\n\n"
            "Return JSON array of table names (e.g., [\"invoice\", \"customer\"])."
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.llm_model,
                        "prompt": prompt,
                        "system": system_prompt,
                        "stream": False,
                        "temperature": 0.0,
                        "options": {
                            "num_ctx": settings.OLLAMA_SQL_NUM_CTX,
                        },
                    },
                    timeout=settings.OLLAMA_GENERATE_TIMEOUT_SEC
                )

                if response.status_code != 200:
                    logger.error(f"Ollama identify_tables error (status {response.status_code}): {response.text}")
                    return []

                result = response.json()
                raw = result.get("response", "").strip()
                raw = raw.replace("```json", "").replace("```", "").strip()

                # Try direct JSON parse
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(t) for t in parsed]
                except json.JSONDecodeError:
                    pass

                # Fallback: extract JSON array from text
                start = raw.find("[")
                end = raw.rfind("]")
                if start != -1 and end != -1 and end > start:
                    try:
                        parsed = json.loads(raw[start:end + 1])
                        if isinstance(parsed, list):
                            return [str(t) for t in parsed]
                    except json.JSONDecodeError:
                        return []

                return []
        except Exception as e:
            logger.error(f"Error identifying tables: {str(e)}")
            return []

    async def verify_intent_similarity(self, prompt_embedding: list, table_summary_text: str) -> float:
        """Compute cosine similarity between prompt embedding and selected table summary embedding."""
        if not table_summary_text:
            return 1.0
        try:
            summary_embedding = await self.embed_text(table_summary_text)
            return self._cosine_similarity(prompt_embedding, summary_embedding)
        except Exception as e:
            logger.error(f"Error verifying intent similarity: {str(e)}")
            return 0.0

    def _cosine_similarity(self, a: list, b: list) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
    
    async def embed_text(self, text: str) -> list:
        """Generate embedding for text"""
        
        try:
            payload = {
                "model": self.embedding_model,
                "input": text,
                "options": {
                    "num_ctx": settings.OLLAMA_EMBED_NUM_CTX,
                },
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json=payload,
                    timeout=settings.OLLAMA_EMBED_TIMEOUT_SEC
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("embeddings", [[]])[0]
                else:
                    logger.error(f"Ollama embedding error (status {response.status_code}): {response.text}")
                    raise Exception(f"Ollama returned status code {response.status_code}")
        
        except Exception as e:
            logger.error(f"Error embedding text: {str(e)}")
            raise

    async def classify_intent(self, text: str) -> str:
        """Classify user prompt intent using Ollama. Returns one of: 'catalog' or 'data'."""
        system = (
            "You are a query classifier. Classify the user prompt into exactly one of two categories:\n"
            "\n"
            "catalog: The user is asking about DATABASE STRUCTURE or SYSTEM METADATA.\n"
            "  Examples: 'show me the schema of artist table', 'give the schema of invoice',\n"
            "  'describe the track table', 'what columns does album have?',\n"
            "  'what indexes exist on invoice?', 'list all tables', 'show slow queries',\n"
            "  'how many open connections are there?'\n"
            "\n"
            "data: The user wants to RETRIEVE, COUNT, FILTER or AGGREGATE actual data rows.\n"
            "  Examples: 'give all artists', 'how many albums are there?', 'show me all tracks',\n"
            "  'list all customers', 'give me all rows from artist', 'show all employees'\n"
            "\n"
            "PRIORITY RULE 1: If the prompt contains words like 'schema', 'describe', 'definition',\n"
            "  'indexes', 'indices', 'columns of', 'structure of', 'ddl' — it is ALWAYS 'catalog'\n"
            "  regardless of the leading verb (give/show/list/get).\n"
            "PRIORITY RULE 2: If asking about actual records/rows/data values — it is ALWAYS 'data'.\n"
            "Respond with a single word only: catalog or data."
        )

        try:
            logger.debug(f"Classify intent: model={self.llm_model}, base_url={self.base_url}")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.llm_model,
                        "prompt": text,
                        "system": system,
                        "stream": False,
                        "temperature": 0.0,
                        "options": {
                            "num_ctx": settings.OLLAMA_SQL_NUM_CTX,
                        },
                    },
                    timeout=settings.OLLAMA_CLASSIFY_TIMEOUT_SEC
                )

                logger.debug(f"Classify response status: {response.status_code}")
                if response.status_code == 200:
                    result = response.json()
                    out = result.get("response", "").strip().lower()
                    if "catalog" in out:
                        return "catalog"
                    return "data"
                else:
                    logger.error(f"Ollama classify error (status {response.status_code}): {response.text}")
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
                    timeout=120.0
                )
                return response.status_code == 200
        except:
            return False
