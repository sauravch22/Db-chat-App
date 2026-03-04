"""
Analyze: What Mistral 7B receives today vs with few-shot examples
"""

# =====================================================
# PART 1: The EXACT schema context from the logs
# =====================================================
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
  customer.address : VARCHAR(70)
  customer.city : VARCHAR(40)
  customer.company : VARCHAR(80)
  customer.country : VARCHAR(40)
  customer.customer_id : INTEGER [PRIMARY KEY, NOT NULL]
  customer.email : VARCHAR(60) [NOT NULL]
  customer.fax : VARCHAR(24)
  customer.first_name : VARCHAR(40) [NOT NULL]
  customer.last_name : VARCHAR(20) [NOT NULL]
  customer.phone : VARCHAR(24)
  customer.postal_code : VARCHAR(10)
  customer.state : VARCHAR(40)
  customer.support_rep_id : INTEGER

FOREIGN KEYS (actual database constraints):
  customer.support_rep_id -> employee.employee_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To invoice: invoice.customer_id = customer.customer_id

GLOBAL FOREIGN KEY RELATIONSHIPS:
  album.artist_id -> artist.artist_id
  customer.support_rep_id -> employee.employee_id
  invoice.customer_id -> customer.customer_id
  invoice_line.invoice_id -> invoice.invoice_id
  invoice_line.track_id -> track.track_id
  track.album_id -> album.album_id
  track.genre_id -> genre.genre_id
  track.media_type_id -> media_type.media_type_id
"""

# =====================================================
# PART 2: Current system prompt (from ollama_service.py)
# =====================================================
system_prompt_current = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query -- no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements -- never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE: invoice, customer
5. Use ONLY column names listed in the schema below
6. Always use table-qualified column names (table.column)
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN
8. Use JOIN PATH or GLOBAL FOREIGN KEY RELATIONSHIPS for join conditions
9. For comparisons to averages or totals, use a subquery or CTE; do NOT nest aggregates directly
10. Use standard PostgreSQL syntax
11. Do not wrap the query in markdown code fences
12. If you JOIN a subquery/CTE, the join key columns MUST be included in that subquery SELECT list
13. Never reference columns from a subquery/CTE alias unless that column is explicitly selected by it
14. For comparisons like "total per entity" vs "average", compute per-entity aggregates in a CTE/subquery, then compare to AVG of those aggregates"""

user_prompt_current = f"""Schema:
{schema_context}

User Question: Show customers who spent more than the average total spending

SQL query:"""

# =====================================================
# PART 3: FEW-SHOT version of the prompt
# =====================================================
few_shot_block = """
--- EXAMPLE 1 (simple join) ---
Question: List all tracks with their genre name
SQL:
SELECT track.name, genre.name AS genre_name
FROM track
JOIN genre ON track.genre_id = genre.genre_id;

--- EXAMPLE 2 (aggregate comparison using subquery -- NO CTE) ---
Question: Show artists who have more albums than the average number of albums per artist
SQL:
SELECT artist.name, COUNT(album.album_id) AS album_count
FROM artist
JOIN album ON album.artist_id = artist.artist_id
GROUP BY artist.artist_id, artist.name
HAVING COUNT(album.album_id) > (
    SELECT AVG(cnt) FROM (
        SELECT COUNT(album.album_id) AS cnt
        FROM album
        GROUP BY album.artist_id
    ) AS avg_albums
);
"""

user_prompt_fewshot = f"""Schema:
{schema_context}

{few_shot_block}
Now answer this question using the same style as the examples above (use subqueries, NOT WITH/CTE):

User Question: Show customers who spent more than the average total spending

SQL query:"""

# =====================================================
# PART 4: Token counting
# =====================================================
def count_tokens_approx(text):
    """Mistral uses SentencePiece BPE. Rough ratio: 1 token ~ 3.5 chars for code/SQL"""
    return len(text) / 3.5

sys_tokens = count_tokens_approx(system_prompt_current)
user_tokens_current = count_tokens_approx(user_prompt_current)
user_tokens_fewshot = count_tokens_approx(user_prompt_fewshot)
fewshot_added = count_tokens_approx(few_shot_block)

print("=" * 65)
print("TOKEN BUDGET ANALYSIS FOR MISTRAL 7B")
print("=" * 65)

print(f"\n{'Component':<35} {'Chars':>8} {'~Tokens':>8}")
print("-" * 55)
print(f"{'System prompt':<35} {len(system_prompt_current):>8,} {sys_tokens:>8.0f}")
print(f"{'User prompt (NO few-shot)':<35} {len(user_prompt_current):>8,} {user_tokens_current:>8.0f}")
print(f"{'User prompt (WITH few-shot)':<35} {len(user_prompt_fewshot):>8,} {user_tokens_fewshot:>8.0f}")
print(f"{'Few-shot examples alone':<35} {len(few_shot_block):>8,} {fewshot_added:>8.0f}")
print("-" * 55)

total_current = sys_tokens + user_tokens_current
total_fewshot = sys_tokens + user_tokens_fewshot
output_budget = 150  # SQL output is typically ~50-150 tokens

print(f"\n{'TOTALS':<35} {'Current':>8} {'Few-shot':>8}")
print("-" * 55)
print(f"{'Input tokens':<35} {total_current:>8.0f} {total_fewshot:>8.0f}")
print(f"{'Output budget':<35} {output_budget:>8} {output_budget:>8}")
print(f"{'Total needed':<35} {total_current + output_budget:>8.0f} {total_fewshot + output_budget:>8.0f}")
print()

print("CONTEXT WINDOW FIT:")
for ctx_size in [4096, 8192, 16384, 32768]:
    headroom_cur = ctx_size - total_current - output_budget
    headroom_fs = ctx_size - total_fewshot - output_budget
    status_cur = "OK" if headroom_cur > 0 else "OVERFLOW"
    status_fs = "OK" if headroom_fs > 0 else "OVERFLOW"
    print(f"  {ctx_size:>6} ctx: current={status_cur} ({headroom_cur:+.0f}), few-shot={status_fs} ({headroom_fs:+.0f})")

print()
print("=" * 65)
print("WHAT MISTRAL GENERATED (BROKEN CTE):")
print("=" * 65)
broken_sql = """SELECT customer.customer_id, SUM(invoice.total) AS total_spent
  FROM invoice
  JOIN customer ON invoice.customer_id = customer.customer_id
  GROUP BY customer.customer_id
), avg_total_spending AS (
  SELECT AVG(total_spent) AS average_total_spent FROM customer_totals
)
SELECT customer.first_name, customer.last_name, customer.email
FROM customer
JOIN customer_totals ON customer.customer_id = customer_totals.customer_id
JOIN avg_total_spending ON 1=1
WHERE customer_totals.total_spent > (SELECT average_total_spent FROM avg_total_spending);"""
print(broken_sql)
print()
print("PROBLEM: Missing 'WITH customer_totals AS (' prefix -- model started")
print("         the CTE body but forgot/omitted the WITH keyword, OR the")
print("         post-processing stripped it (find('SELECT') cuts WITH).")

print()
print("=" * 65)
print("CORRECT SQL (subquery style -- what few-shot teaches):")
print("=" * 65)
correct_sql = """SELECT customer.first_name, customer.last_name, SUM(invoice.total) AS total_spent
FROM customer
JOIN invoice ON invoice.customer_id = customer.customer_id
GROUP BY customer.customer_id, customer.first_name, customer.last_name
HAVING SUM(invoice.total) > (
    SELECT AVG(customer_total) FROM (
        SELECT SUM(invoice.total) AS customer_total
        FROM invoice
        GROUP BY invoice.customer_id
    ) AS avg_spending
);"""
print(correct_sql)

print()
print("=" * 65)
print("THE PROPOSED FEW-SHOT PROMPT (full text):")
print("=" * 65)
print()
print("=== SYSTEM ===")
print(system_prompt_current)
print()
print("=== USER ===")
print(user_prompt_fewshot)
