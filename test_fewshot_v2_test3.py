"""
Test v2 — Test 3: "Find customers who spent more in 2013 compared to 2012"
Year-over-year comparison per customer using conditional aggregation.
"""
import httpx, time

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "mistral"

system_prompt = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): invoice, customer
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. If a JOIN PATH or GLOBAL FOREIGN KEY RELATIONSHIPS are provided, use those exact join conditions.
9. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
10. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
11. Do not wrap the query in markdown code fences
12. For year-over-year comparisons, use SUM(CASE WHEN EXTRACT(YEAR FROM date) = year THEN amount ELSE 0 END) to compute per-year totals in a single GROUP BY
13. Never reference columns from a subquery alias unless that column is explicitly selected by it
14. EXTRACT(YEAR FROM timestamp_column) returns the year as a number — use it for year filtering"""

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

FOREIGN KEYS:
  invoice.customer_id -> customer.customer_id

JOIN PATHS:
  To customer: invoice.customer_id = customer.customer_id

================================================================================
=== TABLE: customer ===
Rows: ~59

COLUMNS:
  customer.customer_id : INTEGER [PRIMARY KEY, NOT NULL]
  customer.first_name : VARCHAR(40) [NOT NULL]
  customer.last_name : VARCHAR(20) [NOT NULL]
  customer.email : VARCHAR(60) [NOT NULL]
  customer.country : VARCHAR(40)
  customer.support_rep_id : INTEGER

FOREIGN KEYS:
  customer.support_rep_id -> employee.employee_id

JOIN PATHS:
  To invoice: invoice.customer_id = customer.customer_id
"""

FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Compare spending in one year vs another year per entity

IMPORTANT VOCABULARY:
- "spent more in 2013 compared to 2012" = SUM of amount in year 2013 > SUM of amount in year 2012
- Use EXTRACT(YEAR FROM date_column) to get the year from a timestamp
- Use SUM(CASE WHEN year = X THEN amount ELSE 0 END) for conditional aggregation per year
- HAVING compares the two year sums

Schema:
  orders.order_id, orders.customer_id, orders.amount, orders.order_date
  customers.customer_id, customers.name

Question: Find customers who spent more in 2023 compared to 2022.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2023 THEN orders.amount ELSE 0 END) AS spending_2023,
    SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2022 THEN orders.amount ELSE 0 END) AS spending_2022
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
WHERE EXTRACT(YEAR FROM orders.order_date) IN (2022, 2023)
GROUP BY customers.customer_id, customers.name
HAVING SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2023 THEN orders.amount ELSE 0 END)
     > SUM(CASE WHEN EXTRACT(YEAR FROM orders.order_date) = 2022 THEN orders.amount ELSE 0 END)
ORDER BY spending_2023 DESC;

WHY THIS WORKS:
- EXTRACT(YEAR FROM date) extracts the year from a timestamp
- SUM(CASE WHEN year = X THEN amount ELSE 0 END) gives per-year total in ONE query
- HAVING compares the two conditional SUMs — no subquery needed
- WHERE filters to only relevant years for efficiency
- No CTE needed — conditional aggregation handles everything

EXAMPLE 2: Simple total per entity

Schema:
  orders.order_id, orders.customer_id, orders.amount
  customers.customer_id, customers.name

Question: Find customers whose total spending exceeds 500.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    SUM(orders.amount) AS total_spending
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
HAVING SUM(orders.amount) > 500
ORDER BY total_spending DESC;
"""

user_question = "Find customers who spent more in 2013 compared to 2012."

user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- Use EXTRACT(YEAR FROM invoice.invoice_date) to get the year
- SUM(CASE WHEN EXTRACT(YEAR FROM invoice.invoice_date) = 2013 THEN invoice.total ELSE 0 END) for 2013 spending
- SUM(CASE WHEN EXTRACT(YEAR FROM invoice.invoice_date) = 2012 THEN invoice.total ELSE 0 END) for 2012 spending
- HAVING compares 2013 sum > 2012 sum
- Copy the exact CASE WHEN pattern from Example 1 above

SQL:"""

total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5
print("=" * 70)
print("TEST v2 — Test 3: 2013 spending > 2012 spending (per-customer)")
print("=" * 70)
print(f"Total input: {total_chars:,} chars (~{est_tokens:.0f} tokens) | Headroom: ~{4096 - est_tokens - 150:.0f} tokens")
print("=" * 70)
print("\nCalling Mistral 7B...")
start = time.time()

with httpx.Client(timeout=120.0) as client:
    response = client.post(f"{OLLAMA_URL}/api/generate", json={
        "model": MODEL, "prompt": user_prompt, "system": system_prompt,
        "stream": False, "temperature": 0.0, "options": {"num_ctx": 4096},
    })

elapsed = time.time() - start
result = response.json()
raw_output = result.get("response", "").strip()
print(f"Response time: {elapsed:.1f}s | Prompt tokens: {result.get('prompt_eval_count', '?')} | Output tokens: {result.get('eval_count', '?')}")
print(f"\n{'='*70}\nRAW MODEL OUTPUT:\n{'='*70}")
print(raw_output)

upper = raw_output.upper()
print(f"\n{'='*70}\nVALIDATION:\n{'='*70}")
checks = {
    "Starts with SELECT": upper.strip().startswith("SELECT"),
    "No WITH/CTE": not upper.strip().startswith("WITH"),
    "Uses EXTRACT(YEAR FROM": "EXTRACT" in upper and "YEAR" in upper,
    "Has CASE WHEN": "CASE WHEN" in upper,
    "Has HAVING": "HAVING" in upper,
    "References 2013": "2013" in raw_output,
    "References 2012": "2012" in raw_output,
    "SUM with CASE": "SUM(" in upper and "CASE" in upper,
    "Uses invoice.total": "TOTAL" in upper,
    "Uses invoice_date": "INVOICE_DATE" in upper,
    "GROUP BY": "GROUP BY" in upper,
    "JOIN": "JOIN" in upper,
}
all_pass = True
for check, passed in checks.items():
    s = "PASS" if passed else "FAIL"
    if not passed: all_pass = False
    print(f"  [{s}] {check}")

print(f"\n{'='*70}")
if all_pass:
    print("VERDICT: ALL CHECKS PASSED")
else:
    print(f"VERDICT: {sum(1 for v in checks.values() if not v)} check(s) failed")
print("=" * 70)

print("\nExecuting on Chinook database...")
sql = raw_output.replace("```sql", "").replace("```", "").strip()
if sql.upper().startswith("SELECT"):
    try:
        r = httpx.post("http://localhost:8000/api/chat/execute", json={"connection_id": 3, "sql": sql}, timeout=30.0)
        d = r.json()
        if d.get("success"):
            print(f"  EXECUTION: SUCCESS — {d.get('row_count', 0)} rows")
            for row in (d.get("data") or [])[:5]:
                print(f"    {row}")
        else:
            print(f"  EXECUTION: FAILED — {d.get('error', 'unknown')[:300]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
