"""
Test v2 — Test 14: "Find countries where the highest invoice total is greater than the global average invoice total"
Per-country MAX vs global AVG pattern.
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
11. For "per-entity MAX" vs "global average", use GROUP BY + HAVING MAX(...) > (SELECT AVG(...) FROM table)
12. Never reference columns from a subquery alias unless that column is explicitly selected by it"""

schema_context = """
=== TABLE: invoice ===
Rows: ~412

COLUMNS:
  invoice.customer_id : INTEGER [NOT NULL]
  invoice.invoice_date : TIMESTAMP [NOT NULL]
  invoice.invoice_id : INTEGER [PRIMARY KEY, NOT NULL]
  invoice.total : NUMERIC(10, 2) [NOT NULL]
  invoice.billing_country : VARCHAR(40)

FOREIGN KEYS:
  invoice.customer_id -> customer.customer_id

================================================================================
=== TABLE: customer ===
Rows: ~59

COLUMNS:
  customer.customer_id : INTEGER [PRIMARY KEY, NOT NULL]
  customer.first_name : VARCHAR(40) [NOT NULL]
  customer.last_name : VARCHAR(20) [NOT NULL]
  customer.country : VARCHAR(40)

JOIN PATHS:
  To invoice: invoice.customer_id = customer.customer_id
"""

FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find groups whose MAX value exceeds the global average

IMPORTANT VOCABULARY:
- "highest invoice total per country" = MAX(invoice.total) grouped by country
- "global average invoice total" = AVG(invoice.total) over ALL invoices (no grouping)
- Pattern: GROUP BY country, HAVING MAX(total) > (SELECT AVG(total) FROM table)
- The inner subquery computes ONE scalar value (global average) — no GROUP BY needed

Schema:
  orders.order_id, orders.region_id, orders.amount
  regions.region_id, regions.name

Question: Find regions where the highest order amount is greater than the global average order amount.

SQL:
SELECT
    regions.region_id,
    regions.name,
    MAX(orders.amount) AS highest_order
FROM regions
JOIN orders ON regions.region_id = orders.region_id
GROUP BY regions.region_id, regions.name
HAVING MAX(orders.amount) > (
    SELECT AVG(orders.amount)
    FROM orders
)
ORDER BY highest_order DESC;

WHY THIS WORKS:
- MAX(orders.amount) per region in outer GROUP BY
- Inner subquery computes plain AVG(orders.amount) over ALL orders — one scalar
- No nested subquery needed because the comparison is MAX per group vs simple global AVG
- HAVING filters after grouping
"""

user_question = "Find countries where the highest invoice total is greater than the global average invoice total."

user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "highest invoice total per country" = MAX(invoice.total) grouped by customer.country
- "global average invoice total" = AVG(invoice.total) from ALL invoices (scalar, no GROUP BY)
- JOIN: customer.customer_id = invoice.customer_id
- GROUP BY customer.country
- HAVING MAX(invoice.total) > (SELECT AVG(invoice.total) FROM invoice)
- Copy the exact HAVING pattern from Example 1 above

SQL:"""

total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5
print("=" * 70)
print("TEST v2 — Test 14: Country highest invoice > global avg invoice")
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
    "Has HAVING": "HAVING" in upper,
    "Has subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "AVG in subquery": "AVG(" in upper,
    "GROUP BY": "GROUP BY" in upper,
    "Uses customer.country": "COUNTRY" in upper,
    "Uses invoice table": "INVOICE" in upper,
    "JOIN present": "JOIN" in upper,
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
            for row in (d.get("data") or [])[:10]:
                print(f"    {row}")
        else:
            print(f"  EXECUTION: FAILED — {d.get('error', 'unknown')[:300]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
