"""
Test v2 approach for Test 1: "Find customers whose latest invoice total is higher than their average invoice total"

This is a per-customer comparison:
- "latest invoice total" = MAX(invoice_date) per customer -> get that row's total
- "average invoice total" = AVG(invoice.total) per customer
- Compare within the same customer (not across customers)

Key challenge: Mistral must understand "latest" = most recent by date, not MAX(total)
"""
import httpx
import json
import time

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "mistral"

# === SYSTEM PROMPT (14 rules - same as v2) ===
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
14. For per-entity comparisons (e.g. latest vs average FOR EACH customer), compute each metric in subqueries and join them, OR use correlated subqueries"""

# === SCHEMA CONTEXT (exact from production logs) ===
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

# === FEW-SHOT EXAMPLES — semantically close to "latest vs average per customer" ===
FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find entities where their LATEST/MOST RECENT value exceeds their own AVERAGE

IMPORTANT VOCABULARY:
- "latest invoice" = the invoice with MAX(invoice_date) for that customer -> NOT MAX(total)
- "average invoice total" = AVG(total) per customer -> use AVG()
- "latest" always means most recent by DATE, not highest by amount
- To get the latest row's value: use a correlated subquery with ORDER BY date DESC LIMIT 1, or join to a subquery that picks MAX(date) per entity

Schema:
  orders.order_id, orders.customer_id, orders.amount, orders.order_date
  customers.customer_id, customers.name

Question: Find customers whose latest order amount is higher than their average order amount.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    (
        SELECT orders.amount
        FROM orders
        WHERE orders.customer_id = customers.customer_id
        ORDER BY orders.order_date DESC
        LIMIT 1
    ) AS latest_order_amount,
    AVG(orders.amount) AS avg_order_amount
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
HAVING (
    SELECT orders.amount
    FROM orders
    WHERE orders.customer_id = customers.customer_id
    ORDER BY orders.order_date DESC
    LIMIT 1
) > AVG(orders.amount);

WHY THIS WORKS:
- "latest order" is found via ORDER BY order_date DESC LIMIT 1 (most recent by DATE)
- AVG(orders.amount) computes per-customer average in the GROUP BY
- HAVING compares the latest value against the average — both per customer
- Correlated subquery ties to the outer customer via WHERE orders.customer_id = customers.customer_id
- No CTE needed — subqueries handle everything

EXAMPLE 2: Simple aggregate comparison — total vs global average

Schema:
  orders.order_id, orders.customer_id, orders.amount
  customers.customer_id, customers.name

Question: Find customers whose total spending is higher than the average customer spending.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    SUM(orders.amount) AS total_spending
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
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
- SUM per customer in outer GROUP BY
- Inner subquery computes SUM per customer, AVG wraps those sums
- HAVING filters after grouping
"""

# === USER QUESTION (Test 1 from comparison prompts) ===
user_question = "Find customers whose latest invoice total is higher than their average invoice total."

# === BUILD FULL USER PROMPT ===
user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "latest invoice" means most recent by DATE (invoice.invoice_date) -> use ORDER BY invoice_date DESC LIMIT 1
- "average invoice total" means AVG(invoice.total) per customer
- Compare latest vs average FOR EACH customer (per-customer comparison)
- Use correlated subquery pattern from Example 1 above
- Copy the HAVING pattern from Example 1 — correlated subquery > AVG()

SQL:"""

# === TOKEN ESTIMATION ===
total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5

print("=" * 70)
print("TEST v2 — Test 1: Latest invoice > avg invoice (per-customer)")
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
upper_nospace = upper.replace(" ", "").replace("\n", "")

print("=" * 70)
print("VALIDATION CHECKS:")
print("=" * 70)

checks = {
    "Starts with SELECT (no preamble)": upper.strip().startswith("SELECT"),
    "No WITH/CTE used": "WITH " not in upper.split("SELECT")[0] if "SELECT" in upper else False,
    "Uses invoice.invoice_date (for latest)": "INVOICE_DATE" in upper or "INVOICE.INVOICE_DATE" in upper.replace(" ", ""),
    "ORDER BY date DESC (latest pattern)": "DESC" in upper and ("INVOICE_DATE" in upper or "INVOICE.INVOICE_DATE" in upper.replace(" ", "")),
    "LIMIT 1 (picks single latest)": "LIMIT 1" in upper or "LIMIT1" in upper_nospace,
    "Has AVG(invoice.total) or AVG(total)": "AVG(" in upper and "TOTAL" in upper,
    "Has HAVING clause": "HAVING" in upper,
    "Correlated subquery (customer_id =)": "CUSTOMER_ID" in upper and upper.count("SELECT") >= 2,
    "Uses customer table": "CUSTOMER" in upper,
    "Uses invoice table": "INVOICE" in upper,
    "JOIN present": "JOIN" in upper,
    "Has GROUP BY": "GROUP BY" in upper,
    "No CTE (no WITH at start)": not upper.strip().startswith("WITH"),
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
    print("VERDICT: ALL CHECKS PASSED — Few-shot v2 worked for Test 1!")
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
            row_count = exec_data.get('row_count', 0)
            print(f"  EXECUTION: SUCCESS — {row_count} rows returned")
            if exec_data.get("data"):
                for row in exec_data["data"][:5]:
                    print(f"    {row}")
            print()
            # Sanity check
            if row_count > 0 and row_count <= 59:
                print(f"  SANITY: Row count {row_count} is reasonable (max 59 customers)")
            elif row_count == 0:
                print("  SANITY: WARNING — 0 rows might mean the query is too restrictive")
            else:
                print(f"  SANITY: WARNING — {row_count} rows exceeds customer count (59)")
        else:
            print(f"  EXECUTION: FAILED — {exec_data.get('error', 'unknown')[:300]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
else:
    print("  Skipped — output doesn't look like SQL")
