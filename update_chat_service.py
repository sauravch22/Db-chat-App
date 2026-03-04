#!/usr/bin/env python3
"""Update chat_service.py to use reasoning mode"""

with open('/Users/sauravchakraborty/DbChat/app/services/chat_service.py', 'r') as f:
    content = f.read()

# Find and replace the SQL generation section
old_code = '''            logger.info("Generating SQL with Ollama")
            sample_info = "Sample tables available with realistic data patterns"
            sql = await self.ollama.generate_sql(
                user_prompt=user_prompt,
                schema_context=schema_context,
                sample_info=sample_info
            )

            # Sanitize: replace MySQL-style backticks with PostgreSQL double-quotes
            sql = sql.replace('`', '"')

            logger.info(f"Generated SQL: {sql}")'''

new_code = '''            logger.info("Generating SQL with Ollama")
            sample_info = "Sample tables available with realistic data patterns"
            
            # Use reasoning mode if enabled (Phase 3 enhancement)
            from app.config import settings
            use_reasoning = settings.USE_REASONING_MODE
            
            reasoning = ""
            if use_reasoning:
                logger.info("Using two-step reasoning mode")
                reasoning, sql = await self.ollama.generate_sql_with_reasoning(
                    user_prompt=user_prompt,
                    schema_context=schema_context,
                    sample_info=sample_info
                )
                logger.info(f"Reasoning: {reasoning[:200]}...")
            else:
                logger.info("Using direct SQL generation")
                sql = await self.ollama.generate_sql(
                    user_prompt=user_prompt,
                    schema_context=schema_context,
                    sample_info=sample_info
                )

            # Sanitize: replace MySQL-style backticks with PostgreSQL double-quotes
            sql = sql.replace('`', '"')

            logger.info(f"Generated SQL: {sql}")'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open('/Users/sauravchakraborty/DbChat/app/services/chat_service.py', 'w') as f:
        f.write(content)
    print("✓ Successfully updated chat_service.py to use reasoning mode")
else:
    print("ERROR: Could not find target code to replace")
    print("Old code not found in file")
