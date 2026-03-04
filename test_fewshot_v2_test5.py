"""
Test v2 approach for Test 5: "Find customers whose first invoice value is less than their last invoice value"

Per-customer comparison:
- "first invoice" = invoice with MIN(invoice_date) for that customer -> get that row's total
- "last invoice" = invoice with MAX(invoice_date) for that customer -> get that row's total
- Compare: first < last (spending went UP over time)

Key challenge: TWO correlated subqueries (first AND last), both keyed on date not amount
"""
import httpx
import time

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "mistral"

# === SYSTEM PROMPT ===
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
14. For per-entity comparisons (e.g. first vs last FOR EACH customer), use correlated subqueries with ORDER BY date ASC/DESC LIMIT 1"""

# === SCHEMA CONTEXT ===
schema_context = """
=== TABLE: invoice ===
Rows: ~412

COLUMNS:
  invoice.billing_address : VARCHAR(70)
  invoice.billing_city : VARCHAR(40)
  invoice.billing_country : VARCHAR(40)
  invoice.billing_postal_code : VARCHAR(10)
  invoice.billing_state : VARCHAR(40)
  invoice.customer_id : INTEGER [NOT NULL]
  invoice.invoice_date : TIMESTAMP [NOT NULL]
  invoice.invoice_id : INTEGER [PRIMARY KEY, NOT NULL]
  invoice.total : NUMERIC(10, 2) [NOT NULL]

FOREIGN KEYS (actual database constraints):
  invoice.customer_id -> customer.customer_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To customer: invoice.customer_id = customer.customer_id

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
  invoice.customer_id -> customer.customer_id
"""

# === FEW-SHOT EXAMPLES — semantically close to "first vs last per customer" ===
FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Compare FIRST vs LAST value for each entity (two date-based lookups)

IMPORTANT VOCABULARY:
- "first invoice/order" = the one with the EARLIEST date -> ORDER BY date ASC LIMIT 1
- "last invoice/order" = the one with the MOST RECENT date -> ORDER BY date DESC LIMIT 1
- "first" and "last" always refer to DATE ordering, never amount ordering
- Use TWO correlated subqueries: one for first (ASC), one for last (DESC)

Schema:
  orders.order_id, orders.customer_id, orders.amount, orders.order_date
  customers.customer_id, customers.name

Question: Find customers whose first order amount is less than their last order amount.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    (
        SELECT orders.amount
        FROM orders
        WHERE orders.customer_id = customers.customer_id
        ORDER BY orders.order_date ASC
        LIMIT 1
    ) AS first_order_amount,
    (
        SELECT orders.amount
        FROM orders
        WHERE orders.customer_id = customers.customer_id
        ORDER BY orders.order_date DESC
        LIMIT 1
    ) AS last_order_amount
FROM customers
WHERE (
    SELECT orders.amount
    FROM orders
    WHERE orders.customer_id = customers.customer_id
    ORDER BY orders.order_date ASC
    LIMIT 1
) < (
    SELECT orders.amount
    FROM orders
    WHERE orders.customer_id = customers.customer_id
    ORDER BY orders.order_date DESC
    LIMIT 1
);

WHY THIS WORKS:
- "first order" found via ORDER BY order_date ASC LIMIT 1 (earliest date)
- "last order" found via ORDER BY order_date DESC LIMIT 1 (most recent date)
- Each correlated subquery ties to outer customer via WHERE orders.customer_id = customers.customer_id
- WHERE clause compares first < last (no GROUP BY needed — each subquery returns one scalar)
- No CTE needed — correlated subqueries handle everything cleanly
- No GROUP BY or HAVING needed because we are comparing two scalar subqueries per customer

EXAMPLE 2: Find the latest value per entity (single date-based lookup)

Schema:
  orders.order_id, orders.customer_id, orders.amount, orders.order_date
  customers.customer_id, customers.name

Question: Find customers whose latest order amount exceeds 100.

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
    ) AS latest_order_amount
FROM customers
WHERE (
    SELECT orders.amount
    FROM orders
    WHERE orders.customer_id = customers.customer_id
    ORDER BY orders.order_date DESC
    LIMIT 1
) > 100;
"""

# === USER QUESTION (Test 5) ===
user_question = "Find customers whose first invoice value is less than their last invoice value."

# === BUILD FULL USER PROMPT ===
user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "first invoice" = earliest by DATE -> ORDER BY invoice.invoice_date ASC LIMIT 1
- "last invoice" = most recent by DATE -> ORDER BY invoice.invoice_date DESC LIMIT 1
- Compare first < last using WHERE with two correlated subqueries (not HAVING)
- Copy the exact TWO-subquery pattern from Example 1 above
- Each subquery must filter by: WHERE invoice.customer_id = customer.customer_id

SQL:"""

# === TOKEN ESTIMATION ===
total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5

print("=" * 70)
print("TEST v2 — Test 5: First invoice < last invoice (per-customer)")
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

# === VALIDATION ===
upper = raw_output.upper()
upper_nospace = upper.replace(" ", "").replace("\n", "")

print("=" * 70)
print("VALIDATION CHECKS:")
print("=" * 70)

checks = {
    "Starts with SELECT (no preamble)": upper.strip().startswith("SELECT"),
    "No WITH/CTE used": not upper.strip().startswith("WITH"),
    "Uses invoice.invoice_date": "INVOICE_DATE" in upper or "INVOICE.INVOICE_DATE" in upper_nospace,
    "ORDER BY date ASC (first)": "ASC" in upper and ("INVOICE_DATE" in upper),
    "ORDER BY date DESC (last)": "DESC" in upper and ("INVOICE_DATE" in upper),
    "LIMIT 1 appears (at least 2x)": upper.count("LIMIT 1") >= 2 or upper_nospace.count("LIMIT1") >= 2,
    "Has WHERE (not HAVING) for compare": "WHERE" in upper,
    "Two+ correlated subqueries (3+ SELECTs)": upper.count("SELECT") >= 3,
    "Uses customer table": "CUSTOMER" in upper,
    "Uses invoice table": "INVOICE" in upper,
    "invoice.total referenced": "INVOICE.TOTAL" in upper_nospace or "INVOICE.TOTAL" in upper,
    "Compares first < last (< operator)": "<" in raw_output,
    "customer_id correlation in subqueries": upper.count("CUSTOMER_ID") >= 3,
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
    print("VERDICT: ALL CHECKS PASSED — Few-shot v2 worked for Test 5!")
else:
    failed = [k for k, v in checks.items() if not v]
    print(f"VERDICT: {len(failed)} check(s) failed: {', '.join(failed)}")
print("=" * 70)

# === EXECUTE ON DB ===
print()
print("Attempting to execute on Chinook database...")

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
