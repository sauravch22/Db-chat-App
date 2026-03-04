"""
Test v2: Refined few-shot with vocabulary mapping + WHY THIS WORKS + checklist
"""
import httpx
import json
import time

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "mistral"

# === SYSTEM PROMPT (14 rules) ===
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
9. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly.
10. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
11. Do not wrap the query in markdown code fences
12. If you JOIN a subquery, the join key columns MUST be included in that subquery SELECT list
13. Never reference columns from a subquery alias unless that column is explicitly selected by it
14. For comparisons like "total per entity" vs "average", compute per-entity aggregates with GROUP BY, then compare via HAVING to AVG of those aggregates in a subquery"""

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

# === REFINED FEW-SHOT EXAMPLES (v2) ===
FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find who spent more than the average spending

IMPORTANT VOCABULARY:
- "total spending" = SUM of all amounts -> use SUM()
- "average spending" = AVG of per-entity totals -> use AVG() on pre-grouped SUMs
- These require TWO levels: first SUM per entity, then AVG of those sums

Schema:
  orders.order_id, orders.customer_id, orders.amount
  customers.customer_id, customers.name, customers.email

Question: Find customers whose total spending is higher than the average customer spending.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    customers.email,
    SUM(orders.amount) AS total_spending
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY
    customers.customer_id,
    customers.name,
    customers.email
HAVING SUM(orders.amount) > (
    SELECT AVG(customer_total)
    FROM (
        SELECT SUM(orders.amount) AS customer_total
        FROM orders
        GROUP BY orders.customer_id
    ) sub
)
ORDER BY total_spending DESC;

WHY THIS WORKS:
- SUM(orders.amount) per customer in outer GROUP BY
- Inner subquery computes SUM per customer independently
- AVG runs over those sums — executes ONCE, not per row
- HAVING filters after grouping — correct for aggregate comparisons
- orders.amount is NEVER used raw in HAVING — always inside SUM()

EXAMPLE 2: Simple join with filter

Schema:
  orders.order_id, orders.customer_id, orders.amount, orders.order_date
  customers.customer_id, customers.name, customers.email

Question: List all customers with their total number of orders.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    COUNT(orders.order_id) AS order_count
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
ORDER BY order_count DESC;
"""

# === USER QUESTION ===
user_question = "Show customers who spent more than the average total spending"

# === BUILD FULL USER PROMPT ===
user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- If question asks for "total spending/revenue/amount" -> use SUM(), not AVG()
- If comparing to "average" -> use AVG() over pre-grouped SUMs in subquery
- Never use raw column in HAVING — always wrap in aggregate: SUM(), COUNT(), etc.
- Copy the exact HAVING pattern from Example 1 above

SQL:"""

# === TOKEN ESTIMATION ===
total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5

print("=" * 70)
print("TEST v2: Refined few-shot with vocab mapping + checklist")
print("=" * 70)
print(f"System prompt:    {len(system_prompt):,} chars")
print(f"User prompt:      {len(user_prompt):,} chars")
print(f"Total input:      {total_chars:,} chars  (~{est_tokens:.0f} tokens)")
print(f"Context window:   4,096 tokens")
print(f"Headroom:         ~{4096 - est_tokens - 150:.0f} tokens for output")
print("=" * 70)
print()

# === CALL OLLAMA ===
print("Calling Mistral 7B...")
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

print(f"Response time:    {elapsed:.1f}s")
print(f"Prompt tokens:    {result.get('prompt_eval_count', '?')}")
print(f"Output tokens:    {result.get('eval_count', '?')}")
print()

print("=" * 70)
print("RAW MODEL OUTPUT:")
print("=" * 70)
print(raw_output)
print()

# === DETAILED ANALYSIS ===
upper = raw_output.upper()

print("=" * 70)
print("VALIDATION CHECKS:")
print("=" * 70)

checks = {
    "Starts with SELECT (no preamble)": upper.strip().startswith("SELECT"),
    "No WITH/CTE used": "WITH " not in upper.split("SELECT")[0] if "SELECT" in upper else False,
    "Uses SUM(invoice.total)": "SUM(INVOICE.TOTAL)" in upper or "SUM( INVOICE.TOTAL)" in upper,
    "Has HAVING clause": "HAVING" in upper,
    "HAVING uses SUM (not raw col)": "HAVING SUM(" in upper.replace(" ", "").replace("\n", "") or "HAVING SUM(" in upper,
    "Has nested subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "Inner subquery has SUM": upper.count("SUM") >= 2,
    "Inner subquery has GROUP BY": upper.count("GROUP BY") >= 2,
    "AVG(customer_total) or similar": "AVG(" in upper and upper.count("AVG(") >= 1,
    "Uses customer table": "CUSTOMER" in upper,
    "Uses invoice table": "INVOICE" in upper,
    "JOIN present": "JOIN" in upper,
    "ORDER BY present": "ORDER BY" in upper,
}

all_pass = True
for check, passed in checks.items():
    status = "PASS" if passed else "FAIL"
    if not passed:
        all_pass = False
    print(f"  [{status}] {check}")

print()
print("=" * 70)
if all_pass:
    print("VERDICT: ALL CHECKS PASSED — Few-shot v2 worked correctly!")
else:
    failed = [k for k, v in checks.items() if not v]
    print(f"VERDICT: {len(failed)} check(s) failed: {', '.join(failed)}")
print("=" * 70)

# === TRY EXECUTING ON ACTUAL DB ===
print()
print("Attempting to execute on Chinook database...")

# Clean SQL for execution
sql = raw_output.replace("```sql", "").replace("```", "").strip()
if sql.upper().startswith("SELECT") or sql.upper().startswith("WITH"):
    try:
        exec_resp = httpx.post(
            "http://localhost:8000/api/chat/execute",
            json={"connection_id": 3, "sql": sql},
            timeout=30.0,
        )
        exec_data = exec_resp.json()
        if exec_data.get("success"):
            print(f"  EXECUTION: SUCCESS — {exec_data.get('row_count', 0)} rows returned")
            if exec_data.get("data"):
                for row in exec_data["data"][:5]:
                    print(f"    {row}")
        else:
            print(f"  EXECUTION: FAILED — {exec_data.get('error', 'unknown')[:200]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
else:
    print("  Skipped — output doesn't look like SQL")
