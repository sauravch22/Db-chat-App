"""
Direct test: Send system prompt (14 rules) + schema + 2 few-shot examples + question to Mistral 7B
See if it avoids CTE and generates correct SQL
"""
import httpx
import json
import time

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "mistral"

# === SYSTEM PROMPT (exact 14 rules from ollama_service.py) ===
system_prompt = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter, do NOT pluralize, singularize, or change them in any way): invoice, customer
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. If a JOIN PATH or GLOBAL FOREIGN KEY RELATIONSHIPS are provided, use those exact join conditions.
9. For comparisons to averages or totals, use a subquery or CTE; do NOT nest aggregates directly.
10. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
11. Do not wrap the query in markdown code fences
12. If you JOIN a subquery/CTE, the join key columns MUST be included in that subquery/CTE SELECT list
13. Never reference columns from a subquery/CTE alias unless that column is explicitly selected by it
14. For comparisons like "total per entity" vs "average", compute per-entity aggregates in a CTE/subquery, then compare to AVG of those aggregates"""

# === SCHEMA CONTEXT (exact from logs) ===
schema_context = """
=== TABLE: invoice ===
Rows: ~412

COLUMNS:
  invoice.billing_address : VARCHAR(70) | Examples: 202 Hoxton Street, Rua dos Campeoes Eur, 3,Raj Bhavan Road
  invoice.billing_city : VARCHAR(40) | Examples: Porto, Budapest, Reno
  invoice.billing_country : VARCHAR(40) | Examples: Argentina, Spain, Italy
  invoice.billing_postal_code : VARCHAR(10) | Examples: K2P 1L7, X1A 1N6, 110017
  invoice.billing_state : VARCHAR(40) | Examples: SP, RM, CA
  invoice.customer_id : INTEGER [NOT NULL]
  invoice.invoice_date : TIMESTAMP [NOT NULL]
  invoice.invoice_id : INTEGER [PRIMARY KEY, NOT NULL]
  invoice.total : NUMERIC(10, 2) [NOT NULL]

FOREIGN KEYS (actual database constraints):
  invoice.customer_id -> customer.customer_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To customer: invoice.customer_id = customer.customer_id

AMBIGUOUS COLUMNS (exist in multiple tables):
    -> invoice.customer_id (in this context)
    -> invoice.invoice_id (in this context)
================================================================================
=== TABLE: customer ===
Rows: ~59

COLUMNS:
  customer.address : VARCHAR(70) | Examples: 202 Hoxton Street, 3,Raj Bhavan Road, Rua dos Campeoes Eur
  customer.city : VARCHAR(40) | Examples: Budapest, Porto, Reno
  customer.company : VARCHAR(80) | Examples: Apple Inc., Telus, Embraer - Empresa Br
  customer.country : VARCHAR(40) | Examples: Argentina, Spain, Italy
  customer.customer_id : INTEGER [PRIMARY KEY, NOT NULL]
  customer.email : VARCHAR(60) [NOT NULL] | Examples: ladislav_kovacs@appl, johngordon22@yahoo.c, enrique_munoz@yahoo.
  customer.fax : VARCHAR(24) | Examples: +1 (780) 434-5565, +1 (408) 996-1011, +55 (21) 2271-7070
  customer.first_name : VARCHAR(40) [NOT NULL] | Examples: Martha, Edward, Victor
  customer.last_name : VARCHAR(20) [NOT NULL] | Examples: Sampaio, Munoz, Wojcik
  customer.phone : VARCHAR(24) | Examples: +1 (617) 522-1333, +91 0124 39883988, +55 (21) 2271-7000
  customer.postal_code : VARCHAR(10) | Examples: K2P 1L7, X1A 1N6, 110017
  customer.state : VARCHAR(40) | Examples: SP, RM, CA
  customer.support_rep_id : INTEGER

FOREIGN KEYS (actual database constraints):
  customer.support_rep_id -> employee.employee_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To invoice: invoice.customer_id = customer.customer_id

GLOBAL FOREIGN KEY RELATIONSHIPS:
  album.artist_id -> artist.artist_id
  customer.support_rep_id -> employee.employee_id
  employee.reports_to -> employee.employee_id
  invoice.customer_id -> customer.customer_id
  invoice_line.invoice_id -> invoice.invoice_id
  invoice_line.track_id -> track.track_id
  playlist_track.playlist_id -> playlist.playlist_id
  playlist_track.track_id -> track.track_id
  track.album_id -> album.album_id
  track.genre_id -> genre.genre_id
  track.media_type_id -> media_type.media_type_id
"""

# === 2 FEW-SHOT EXAMPLES ===
few_shot = """
--- EXAMPLE 1 (simple join) ---
Question: List all tracks with their genre name
SQL:
SELECT track.name, genre.name AS genre_name
FROM track
JOIN genre ON track.genre_id = genre.genre_id;

--- EXAMPLE 2 (entities whose SUM exceeds the average SUM across all entities — NO CTE) ---
Question: Show genres where the total number of tracks exceeds the average track count per genre
SQL:
SELECT genre.name, COUNT(track.track_id) AS track_count
FROM genre
JOIN track ON track.genre_id = genre.genre_id
GROUP BY genre.genre_id, genre.name
HAVING COUNT(track.track_id) > (
    SELECT AVG(genre_track_count) FROM (
        SELECT COUNT(track.track_id) AS genre_track_count
        FROM track
        GROUP BY track.genre_id
    ) AS per_genre
);
"""

# === USER QUESTION ===
user_question = "Show customers who spent more than the average total spending"

# === BUILD FULL USER PROMPT ===
user_prompt = f"""Schema:
{schema_context}

{few_shot}
Now answer this question using the same style as the examples above (use subqueries, NOT WITH/CTE):

User Question: {user_question}

SQL query:"""

# === TOKEN ESTIMATION ===
total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5

print("=" * 70)
print("SENDING TO MISTRAL 7B: System (14 rules) + Schema + 2 Examples + Question")
print("=" * 70)
print(f"System prompt:    {len(system_prompt):,} chars")
print(f"User prompt:      {len(user_prompt):,} chars")
print(f"Total input:      {total_chars:,} chars  (~{est_tokens:.0f} tokens)")
print(f"Context window:   4,096 tokens")
print(f"Headroom:         ~{4096 - est_tokens - 150:.0f} tokens for output")
print("=" * 70)
print()

# === CALL OLLAMA ===
print("Calling Mistral 7B via Ollama...")
start = time.time()

with httpx.Client(timeout=120.0) as client:
    response = client.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": MODEL,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
            "temperature": 0.0,
            "options": {
                "num_ctx": 4096,
            },
        },
    )

elapsed = time.time() - start
result = response.json()
raw_output = result.get("response", "").strip()

print(f"Response time: {elapsed:.1f}s")
print(f"Eval count:    {result.get('eval_count', '?')} tokens generated")
print(f"Prompt tokens: {result.get('prompt_eval_count', '?')} tokens")
print()

print("=" * 70)
print("RAW MODEL OUTPUT:")
print("=" * 70)
print(raw_output)
print()

# === ANALYSIS ===
print("=" * 70)
print("ANALYSIS:")
print("=" * 70)

has_with = "WITH" in raw_output.upper() or "with " in raw_output.lower()
has_cte = "AS (" in raw_output and has_with
has_subquery = "SELECT" in raw_output.upper() and raw_output.upper().count("SELECT") > 1
has_having = "HAVING" in raw_output.upper()
has_select = raw_output.upper().strip().startswith("SELECT") or raw_output.upper().strip().startswith("WITH")
starts_clean = not any(raw_output.startswith(x) for x in ["Here", "The ", "This ", "Below", "I "])

print(f"  Starts with SQL (no preamble): {'YES' if starts_clean else 'NO'}")
print(f"  Uses WITH/CTE:                 {'YES (bad)' if has_cte else 'NO (good)'}")
print(f"  Uses nested subquery:          {'YES (good)' if has_subquery else 'NO'}")
print(f"  Uses HAVING:                   {'YES' if has_having else 'NO'}")
print(f"  Starts with SELECT/WITH:       {'YES' if has_select else 'NO'}")
print()

if has_cte:
    print("VERDICT: FEW-SHOT DID NOT PREVENT CTE. Model ignored the examples.")
elif has_subquery and not has_cte:
    print("VERDICT: FEW-SHOT WORKED! Model used subquery pattern instead of CTE.")
else:
    print("VERDICT: Unclear pattern. Review the SQL above.")
