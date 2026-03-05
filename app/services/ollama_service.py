"""LLM Service — uses remote OpenAI-compatible API for generation,
local Ollama for embeddings only."""

import httpx
import json
import logging
from app.config import Settings

logger = logging.getLogger(__name__)

settings = Settings()


class OllamaService:
    """Service for interacting with remote LLM (chat completions) and local Ollama (embeddings)"""
    
    def __init__(self):
        # Remote LLM (Qwen3-Coder-Next via ngrok)
        self.llm_api_url = settings.LLM_API_URL
        self.llm_model = settings.LLM_MODEL_NAME
        self.llm_timeout = settings.LLM_TIMEOUT_SEC
        self.llm_max_tokens = settings.LLM_MAX_TOKENS
        # Local Ollama (embeddings only)
        self.base_url = settings.OLLAMA_URL
        self.embedding_model = settings.OLLAMA_EMBEDDING_MODEL
    
    def _clean_sql_output(self, sql: str) -> str:
        """Clean raw LLM output into valid SQL, preserving WITH/CTE clauses."""
        # Strip markdown code fences
        sql = sql.replace("```sql", "").replace("```", "").strip()

        # Find the real SQL start: WITH (CTE) or SELECT
        upper = sql.upper()
        with_pos = upper.find("WITH")
        select_pos = upper.find("SELECT")

        # Pick whichever comes first as the true SQL start
        candidates = []
        if with_pos >= 0:
            candidates.append(with_pos)
        if select_pos >= 0:
            candidates.append(select_pos)

        if candidates:
            sql_start = min(candidates)
            if sql_start > 0:
                sql = sql[sql_start:]

        # Strip trailing explanation after the last semicolon
        if ";" in sql:
            sql = sql[:sql.index(";") + 1]

        # Remove trailing quotes that LLM sometimes adds
        sql = sql.rstrip('"').rstrip("'").strip()
        return sql

    async def _call_chat_completions(self, system: str, user: str, temperature: float = 0.0, max_tokens: int = None) -> str:
        """Call the remote OpenAI-compatible chat completions API."""
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens or self.llm_max_tokens,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.llm_api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.llm_timeout,
            )
        if response.status_code != 200:
            logger.error(f"LLM API error (status {response.status_code}): {response.text[:300]}")
            raise Exception(f"LLM API returned status code {response.status_code}")
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        usage = data.get("usage", {})
        logger.debug(f"LLM tokens: prompt={usage.get('prompt_tokens','?')}, completion={usage.get('completion_tokens','?')}")
        return content

    async def generate_sql(
        self,
        user_prompt: str,
        schema_context: str,
        sample_info: str
    ) -> str:
        """Generate SQL query from natural language"""
        
        # Extract exact table names from the schema context to enforce as hard constraints
        exact_tables = []
        for line in schema_context.splitlines():
            stripped = line.strip()
            if stripped.startswith("Table:"):
                exact_tables.append(stripped.split("Table:", 1)[1].strip())
            elif stripped.startswith("=== TABLE:"):
                exact_tables.append(stripped.split("=== TABLE:", 1)[1].strip("= "))
        table_list_str = ", ".join(exact_tables) if exact_tables else "(see schema)"

        system_prompt = f"""You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter, do NOT pluralize, singularize, or change them in any way): {table_list_str}
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. If a JOIN PATH or GLOBAL FOREIGN KEY RELATIONSHIPS are provided, use those exact join conditions.
9. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
10. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
11. Do not wrap the query in markdown code fences
12. If you JOIN a subquery, the join key columns MUST be included in that subquery SELECT list
13. Never reference columns from a subquery alias unless that column is explicitly selected by it
14. For comparisons like "total per entity" vs "average", compute per-entity aggregates in a subquery, then compare to AVG of those aggregates"""

        full_prompt = f"""Schema:
{schema_context}

User Question: {user_prompt}

SQL query:"""
        
        try:
            logger.debug(f"SQL generation: model={self.llm_model}, url={self.llm_api_url}")
            raw = await self._call_chat_completions(system_prompt, full_prompt)
            sql = self._clean_sql_output(raw)
            return sql
        
        except Exception as e:
            logger.error(f"Error generating SQL: {str(e)}")
            raise


    async def generate_sql_with_reasoning(
        self,
        user_prompt: str,
        schema_context: str,
        sample_info: str = None
    ) -> tuple:
        """
        Two-step SQL generation: Reason first, then generate
        Returns: (reasoning, sql)
        """
        
        # Extract table names from schema
        exact_tables = []
        for line in schema_context.splitlines():
            stripped = line.strip()
            if stripped.startswith("Table:"):
                exact_tables.append(stripped.split("Table:", 1)[1].strip())
            elif stripped.startswith("=== TABLE:"):
                exact_tables.append(stripped.split("=== TABLE:", 1)[1].strip("= "))
        table_list_str = ", ".join(exact_tables) if exact_tables else "(see schema)"
        
        # STEP 1: Force LLM to reason about query structure
        reasoning_system = """You are a SQL query planner. Your job is to analyze the question and schema, then plan the query structure BEFORE writing any SQL code.
        
Think step-by-step and be specific about table names and column names from the schema."""
        
        reasoning_prompt = f"""Schema (these are the ONLY tables and columns that exist):
{schema_context}

User Question: {user_prompt}

Analyze this question step-by-step. Answer these questions:

1. TABLES & JOINS: What tables are needed? How do they join?
   - Look at GLOBAL FOREIGN KEY RELATIONSHIPS section
   - List the exact join conditions using table.column format

2. OUTPUT COLUMNS: What columns should be in the SELECT clause?
   - Use exact column names from the COLUMNS section
   - Use table.column format

3. AGGREGATION: Is aggregation needed (COUNT, SUM, AVG, MAX, MIN)?
   - If yes, what column(s) and what function(s)?
   - What should the GROUP BY be?

4. COMPARISON PATTERN: Is this comparing individual values to an aggregate (average, total, etc.)?
   - If YES, this requires: compute per-group values FIRST, then compare to aggregate of those values
   - Example: "customers spending more than average" needs:
     * Subquery: compute total per customer
     * Main query: compare to AVG of those totals
   
5. FILTERING: What goes in WHERE vs HAVING?
   - WHERE: filters before grouping
   - HAVING: filters after grouping (on aggregates)

Your analysis (be specific with table.column names):"""

        try:
            logger.debug(f"Step 1 - Reasoning: model={self.llm_model}")
            
            # Step 1: Get reasoning
            reasoning = await self._call_chat_completions(reasoning_system, reasoning_prompt, max_tokens=1024)
            logger.info(f"LLM Reasoning (first 300 chars): {reasoning[:300]}...")
            
            # STEP 2: Generate SQL using the reasoning
            sql_system = f"""You are a PostgreSQL SQL expert. Generate SQL based on the query analysis provided.

STRICT RULES:
1. Output ONLY the SQL query — no explanation
2. Use ONLY tables and columns from the schema: {table_list_str}
3. Always use table.column format (table-qualified names)
4. Follow the structure identified in your analysis
5. If analysis identified "comparison to average/total across groups", use a scalar subquery
6. Use standard PostgreSQL syntax
7. Do NOT use CTE / WITH — use subqueries instead
8. If JOINing a subquery, the join key MUST be in that subquery's SELECT list"""

            sql_prompt = f"""Schema:
{schema_context}

User Question: {user_prompt}

Your analysis of this query:
{reasoning}

Based on your analysis above, write the SQL query that answers the question.
Follow the structure and approach you identified.

SQL query:"""

            raw = await self._call_chat_completions(sql_system, sql_prompt)
            sql = self._clean_sql_output(raw)
            return reasoning, sql
        
        except Exception as e:
            logger.error(f"Error in reasoning-based SQL generation: {str(e)}")
            # Fallback to direct generation
            return "", await self.generate_sql(user_prompt, schema_context, sample_info)

    async def explain_sql(
        self,
        sql: str,
        user_prompt: str,
        schema_context: str,
        columns: list = None,
        row_count: int = None
    ) -> str:
        """Generate a plain-English explanation of a SQL query for non-technical users."""
        system = """You are a SQL teacher explaining a query to a business user
who does NOT know SQL. Break down the query into sections:

1. **What this query does** — one-sentence summary
2. **Tables used** — list each table and what data it holds
3. **How tables connect** — explain each JOIN in plain English
4. **Filters applied** — explain WHERE conditions in plain English
5. **Calculations** — explain any SUM, COUNT, AVG, GROUP BY
6. **Sorting & Limits** — explain ORDER BY and LIMIT if present

Use bullet points. No SQL syntax in your explanation — only plain English.
Keep it concise — max 200 words."""

        prompt = f"""User's original question: {user_prompt}

SQL query that was generated:
{sql}

Database schema used:
{schema_context}

{f"Result: {row_count} rows returned with columns: {', '.join(columns)}" if columns else ""}

Explain this query in plain English:"""

        try:
            explanation = await self._call_chat_completions(
                system, prompt, temperature=0.3, max_tokens=512
            )
            return explanation
        except Exception as e:
            logger.error(f"Error explaining SQL: {str(e)}")
            return "Unable to generate explanation at this time."

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
            raw = await self._call_chat_completions(system_prompt, prompt, max_tokens=256)
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
        """Classify user prompt intent. Returns one of: 'catalog' or 'data'."""
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
            logger.debug(f"Classify intent: model={self.llm_model}, url={self.llm_api_url}")
            out = await self._call_chat_completions(system, text, max_tokens=10)
            out = out.strip().lower()
            if "catalog" in out:
                return "catalog"
            return "data"

        except Exception as e:
            logger.error(f"Error classifying intent: {str(e)}")
            return "data"
    
    async def health_check(self) -> bool:
        """Check if remote LLM API and local Ollama (embeddings) are reachable"""
        
        try:
            async with httpx.AsyncClient() as client:
                # Check remote LLM endpoint
                llm_resp = await client.post(
                    self.llm_api_url,
                    json={
                        "model": self.llm_model,
                        "messages": [{"role": "user", "content": "SELECT 1"}],
                        "max_tokens": 5,
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=30.0,
                )
                llm_ok = llm_resp.status_code == 200
                
                # Check local Ollama for embeddings
                ollama_resp = await client.get(
                    f"{self.base_url}/api/tags",
                    timeout=30.0,
                )
                ollama_ok = ollama_resp.status_code == 200
                
                if not llm_ok:
                    logger.warning(f"Remote LLM endpoint not reachable: {self.llm_api_url}")
                if not ollama_ok:
                    logger.warning(f"Local Ollama not reachable: {self.base_url}")
                
                return llm_ok and ollama_ok
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return False
