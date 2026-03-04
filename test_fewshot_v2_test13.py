"""
Test v2 approach for Test 13: "Find countries whose total revenue is higher than the average revenue per country"

Single-table aggregate comparison:
- "total revenue per country" = SUM(invoice.total) GROUP BY invoice.billing_country
- "average revenue per country" = AVG of those SUMs -> nested subquery
"""
import httpx
import time

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "mistral"

system_prompt = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): invoice
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
9. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
10. Do not wrap the query in markdown code fences
11. For comparisons like "per-group SUM" vs "average of those SUMs", compute per-group sums with GROUP BY + HAVING, and compare to AVG of those sums in a nested subquery"""

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
"""

FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find groups whose total value exceeds the average total across all groups

IMPORTANT VOCABULARY:
- "total revenue per country" = SUM(amount) GROUP BY country -> use SUM()
- "average revenue per country" = AVG of per-country SUMs -> use AVG() on pre-grouped SUMs
- These require TWO levels: first SUM per group, then AVG of those sums in a subquery

Schema:
  orders.order_id, orders.region, orders.amount

Question: Find regions whose total order amount is higher than the average regional total.

SQL:
SELECT
    orders.region,
    SUM(orders.amount) AS total_amount
FROM orders
GROUP BY orders.region
HAVING SUM(orders.amount) > (
    SELECT AVG(region_total)
    FROM (
        SELECT SUM(orders.amount) AS region_total
        FROM orders
        GROUP BY orders.region
    ) sub
)
ORDER BY total_amount DESC;

WHY THIS WORKS:
- SUM per region in outer GROUP BY
- Inner subquery computes SUM per region independently
- AVG wraps those sums — computes the average group total
- HAVING filters after grouping — only keeps above-average groups
- Single table, no JOINs needed — just GROUP BY the grouping column
- No CTE needed — nested subquery in HAVING is clean

EXAMPLE 2: Count per group vs average count

Schema:
  students.student_id, students.department

Question: Find departments with more students than the average department.

SQL:
SELECT
    students.department,
    COUNT(students.student_id) AS student_count
FROM students
GROUP BY students.department
HAVING COUNT(students.student_id) > (
    SELECT AVG(dept_count)
    FROM (
        SELECT COUNT(students.student_id) AS dept_count
        FROM students
        GROUP BY students.department
    ) sub
)
ORDER BY student_count DESC;
"""

user_question = "Find countries whose total revenue is higher than the average revenue per country."

user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "country" = invoice.billing_country (NOT a separate country table)
- "total revenue" per country = SUM(invoice.total) GROUP BY invoice.billing_country
- "average revenue per country" = AVG of those per-country SUMs -> nested subquery
- Single table query — only invoice table needed, no JOINs
- Copy the exact HAVING pattern from Example 1: HAVING SUM(...) > (SELECT AVG(total) FROM (SELECT SUM(...) GROUP BY ...) sub)

SQL:"""

total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5

print("=" * 70)
print("TEST v2 — Test 13: Country revenue > avg revenue per country")
print("=" * 70)
print(f"Total input:      {total_chars:,} chars  (~{est_tokens:.0f} tokens)")
print(f"Headroom:         ~{4096 - est_tokens - 150:.0f} tokens for output")
print("=" * 70)
print()

print("Calling Mistral 7B...")
start = time.time()

with httpx.Client(timeout=120.0) as client:
    response = client.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": MODEL, "prompt": user_prompt, "system": system_prompt,
            "stream": False, "temperature": 0.0, "options": {"num_ctx": 4096},
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

upper = raw_output.upper()
upper_nospace = upper.replace(" ", "").replace("\n", "")

print("=" * 70)
print("VALIDATION CHECKS:")
print("=" * 70)

checks = {
    "Starts with SELECT (no preamble)": upper.strip().startswith("SELECT"),
    "No WITH/CTE used": not upper.strip().startswith("WITH"),
    "Uses invoice.billing_country": "BILLING_COUNTRY" in upper,
    "Uses SUM(invoice.total)": "SUM(" in upper and "TOTAL" in upper,
    "Has GROUP BY billing_country": "GROUP BY" in upper and "BILLING_COUNTRY" in upper,
    "Has HAVING clause": "HAVING" in upper,
    "HAVING uses SUM()": "HAVING" in upper and "SUM(" in upper,
    "Has nested subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "Inner subquery has SUM": upper.count("SUM(") >= 2,
    "Inner subquery has GROUP BY": upper.count("GROUP BY") >= 2,
    "AVG() wrapping inner sums": "AVG(" in upper,
    "Uses invoice table": "INVOICE" in upper,
    "> operator": ">" in raw_output,
}

all_pass = True
for check, passed in checks.items():
    status = "PASS" if passed else "FAIL"
    if not passed: all_pass = False
    print(f"  [{status}] {check}")

print()
print("=" * 70)
if all_pass:
    print("VERDICT: ALL CHECKS PASSED — Few-shot v2 worked for Test 13!")
else:
    failed = [k for k, v in checks.items() if not v]
    print(f"VERDICT: {len(failed)} check(s) failed: {', '.join(failed)}")
print("=" * 70)

print()
print("Attempting to execute on Chinook database...")
sql = raw_output.replace("```sql", "").replace("```", "").strip()
if sql.upper().startswith("SELECT") or sql.upper().startswith("WITH"):
    try:
        exec_resp = httpx.post("http://localhost:8000/api/chat/execute",
            json={"connection_id": 3, "sql": sql}, timeout=30.0)
        exec_data = exec_resp.json()
        if exec_data.get("success"):
            row_count = exec_data.get('row_count', 0)
            print(f"  EXECUTION: SUCCESS — {row_count} rows returned")
            for row in (exec_data.get("data") or [])[:8]:
                print(f"    {row}")
            print()
            if 0 < row_count <= 24:
                print(f"  SANITY: Row count {row_count} is reasonable (~24 billing countries)")
            elif row_count == 0:
                print("  SANITY: WARNING — 0 rows")
        else:
            print(f"  EXECUTION: FAILED — {exec_data.get('error', 'unknown')[:300]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
else:
    print("  Skipped — output doesn't look like SQL")
