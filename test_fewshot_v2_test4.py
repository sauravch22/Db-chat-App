"""
Test v2 — Test 4: "Find customers whose maximum invoice is at least 2 times their minimum invoice"
Per-customer comparison: MAX(total) >= 2 * MIN(total)
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
8. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
9. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
10. Do not wrap the query in markdown code fences
11. For per-entity aggregate comparisons (MAX vs MIN), use GROUP BY with HAVING to compare aggregates
12. Never reference columns from a subquery alias unless that column is explicitly selected by it"""

schema_context = """
=== TABLE: invoice ===
Rows: ~412

COLUMNS:
  invoice.customer_id : INTEGER [NOT NULL]
  invoice.invoice_date : TIMESTAMP [NOT NULL]
  invoice.invoice_id : INTEGER [PRIMARY KEY, NOT NULL]
  invoice.total : NUMERIC(10, 2) [NOT NULL]

FOREIGN KEYS:
  invoice.customer_id -> customer.customer_id

================================================================================
=== TABLE: customer ===
Rows: ~59

COLUMNS:
  customer.customer_id : INTEGER [PRIMARY KEY, NOT NULL]
  customer.first_name : VARCHAR(40) [NOT NULL]
  customer.last_name : VARCHAR(20) [NOT NULL]
  customer.email : VARCHAR(60) [NOT NULL]

JOIN PATHS:
  To invoice: invoice.customer_id = customer.customer_id
"""

FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find entities whose MAX aggregate is at least N times their MIN aggregate

IMPORTANT VOCABULARY:
- "maximum invoice" = MAX(total) per customer
- "minimum invoice" = MIN(total) per customer
- "at least 2 times" = MAX(total) >= 2 * MIN(total)
- GROUP BY customer, HAVING MAX(amount) >= 2 * MIN(amount)

Schema:
  orders.order_id, orders.customer_id, orders.amount
  customers.customer_id, customers.name

Question: Find customers whose maximum order is at least 3 times their minimum order.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    MAX(orders.amount) AS max_order,
    MIN(orders.amount) AS min_order
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
HAVING MAX(orders.amount) >= 3 * MIN(orders.amount)
ORDER BY max_order DESC;

WHY THIS WORKS:
- MAX and MIN computed per customer via GROUP BY
- HAVING compares aggregates directly — no subquery needed for within-entity comparisons
- The multiplier (3 *) applies to MIN to set the threshold
- No CTE needed — simple GROUP BY + HAVING handles it

EXAMPLE 2: Find entities whose total exceeds a fixed threshold

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

user_question = "Find customers whose maximum invoice is at least 2 times their minimum invoice."

user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "maximum invoice" = MAX(invoice.total) per customer
- "minimum invoice" = MIN(invoice.total) per customer
- "at least 2 times" = HAVING MAX(invoice.total) >= 2 * MIN(invoice.total)
- GROUP BY customer, use HAVING for the comparison
- Copy the exact HAVING pattern from Example 1 above

SQL:"""

total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5
print("=" * 70)
print("TEST v2 — Test 4: MAX invoice >= 2x MIN invoice (per-customer)")
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
    "Has MAX(invoice.total)": "MAX(" in upper and "TOTAL" in upper,
    "Has MIN(invoice.total)": "MIN(" in upper and "TOTAL" in upper,
    "Has HAVING": "HAVING" in upper,
    "Has >= 2 * or >= 2*": ">= 2" in raw_output or ">= 2 *" in raw_output or ">=2*" in raw_output.replace(" ",""),
    "GROUP BY": "GROUP BY" in upper,
    "JOIN": "JOIN" in upper,
    "Uses customer table": "CUSTOMER" in upper,
    "Uses invoice table": "INVOICE" in upper,
}
all_pass = True
for check, passed in checks.items():
    s = "PASS" if passed else "FAIL"
    if not passed: all_pass = False
    print(f"  [{s}] {check}")

print(f"\n{'='*70}")
print("VERDICT: ALL CHECKS PASSED" if all_pass else f"VERDICT: {sum(1 for v in checks.values() if not v)} check(s) failed")
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
