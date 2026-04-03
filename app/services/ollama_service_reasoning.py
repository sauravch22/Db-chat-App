"""Two-step reasoning SQL generation method - to be merged into ollama_service.py"""

# ADD THIS METHOD TO OllamaService class after generate_sql()

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
     * CTE/subquery: compute total per customer
     * Main query: compare to AVG of those totals
   
5. FILTERING: What goes in WHERE vs HAVING?
   - WHERE: filters before grouping
   - HAVING: filters after grouping (on aggregates)

Your analysis (be specific with table.column names):"""

    try:
        logger.debug(f"Step 1 - Reasoning: model={self.llm_model}")
        
        async with httpx.AsyncClient() as client:
            # Step 1: Get reasoning
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.llm_model,
                    "prompt": reasoning_prompt,
                    "system": reasoning_system,
                    "stream": False,
                    "temperature": 0.0,
                    "options": {
                        "num_ctx": settings.OLLAMA_SQL_NUM_CTX,
                    },
                },
                timeout=settings.OLLAMA_GENERATE_TIMEOUT_SEC
            )
            
            if response.status_code != 200:
                logger.error(f"Reasoning step failed (status {response.status_code}): {response.text}")
                # Fallback to direct generation
                return "", await self.generate_sql(user_prompt, schema_context, sample_info)
            
            reasoning = response.json().get("response", "").strip()
            logger.info(f"LLM Reasoning (first 300 chars): {reasoning[:300]}...")
            
            # STEP 2: Generate SQL using the reasoning
            sql_system = f"""You are a PostgreSQL SQL expert. Generate SQL based on the query analysis provided.

STRICT RULES:
1. Output ONLY the SQL query — no explanation
2. Use ONLY tables and columns from the schema: {table_list_str}
3. Always use table.column format (table-qualified names)
4. Follow the structure identified in your analysis
5. If analysis identified "comparison to average/total across groups", use CTE or scalar subquery
6. Use standard PostgreSQL syntax
7. If JOINing a subquery, the join key MUST be in that subquery's SELECT list"""

            sql_prompt = f"""Schema:
{schema_context}

User Question: {user_prompt}

Your analysis of this query:
{reasoning}

Based on your analysis above, write the SQL query that answers the question.
Follow the structure and approach you identified.

SQL query:"""

            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.llm_model,
                    "prompt": sql_prompt,
                    "system": sql_system,
                    "stream": False,
                    "temperature": 0.0,
                    "options": {
                        "num_ctx": settings.OLLAMA_SQL_NUM_CTX,
                    },
                },
                timeout=settings.OLLAMA_GENERATE_TIMEOUT_SEC
            )
            
            logger.debug(f"Step 2 - SQL generation response status: {response.status_code}")
            if response.status_code == 200:
                result = response.json()
                sql = result.get("response", "").strip()
                
                # Clean up SQL (same as generate_sql)
                sql = sql.replace("```sql", "").replace("```", "").strip()
                upper = sql.upper()
                select_pos = upper.find("SELECT")
                if select_pos > 0:
                    sql = sql[select_pos:]
                if ";" in sql:
                    sql = sql[:sql.index(";") + 1]
                sql = sql.rstrip('"').rstrip("'").strip()
                
                return reasoning, sql
            else:
                logger.error(f"SQL generation failed (status {response.status_code}): {response.text}")
                # Fallback to direct generation
                return reasoning, await self.generate_sql(user_prompt, schema_context, sample_info)
    
    except Exception as e:
        logger.error(f"Error in reasoning-based SQL generation: {str(e)}")
        # Fallback to direct generation
        return "", await self.generate_sql(user_prompt, schema_context, sample_info)
