#!/usr/bin/env python3
# Estimate schema context size

example_context = """Table: artist
Columns: artist_id (integer), name (character varying)

Table: album
Columns: album_id (integer), title (character varying), artist_id (integer)

Table: track
Columns: track_id (integer), name (character varying), album_id (integer), media_type_id (integer), genre_id (integer), composer (character varying ? nullable), milliseconds (integer), bytes (integer ? nullable), unit_price (numeric)

Table: employee
Columns: employee_id (integer), last_name (character varying), first_name (character varying), title (character varying ? nullable), reports_to (integer ? nullable), birth_date (timestamp without time zone ? nullable), hire_date (timestamp without time zone ? nullable), address (character varying ? nullable), city (character varying ? nullable), state (character varying ? nullable), country (character varying ? nullable), postal_code (character varying ? nullable), phone (character varying ? nullable), fax (character varying ? nullable), email (character varying ? nullable)

Table: customer
Columns: customer_id (integer), first_name (character varying), last_name (character varying), company (character varying ? nullable), address (character varying ? nullable), city (character varying ? nullable), state (character varying ? nullable), country (character varying ? nullable), postal_code (character varying ? nullable), phone (character varying ? nullable), fax (character varying ? nullable), email (character varying), support_rep_id (integer ? nullable)"""

system_prompt = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter, do NOT pluralize, singularize, or change them in any way): artist, album, track, employee, customer
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
7. Do not wrap the query in markdown code fences"""

user_prompt = "Give all the artist in the table"

# Rough token estimate: ~4 chars per token
schema_chars = len(example_context)
system_chars = len(system_prompt)
user_chars = len(user_prompt)
total_chars = schema_chars + system_chars + user_chars

estimated_tokens = total_chars // 4

print(f"Schema context: {schema_chars} chars (~{schema_chars // 4} tokens)")
print(f"System prompt: {system_chars} chars (~{system_chars // 4} tokens)")
print(f"User prompt: {user_chars} chars (~{user_chars // 4} tokens)")
print(f"\nTotal input: {total_chars} chars")
print(f"Estimated input tokens: ~{estimated_tokens}")
print(f"\nWith response generation (another ~200-500 tokens), total context usage: ~{estimated_tokens + 300} tokens")
