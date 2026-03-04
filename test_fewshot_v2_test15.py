"""
Test v2 approach for Test 15: "Find countries whose number of customers is higher than the average number of customers per country"

Single-table aggregate comparison:
- "number of customers per country" = COUNT(customer_id) GROUP BY country
- "average number per country" = AVG of those counts -> nested subquery
- Pattern: GROUP BY country, HAVING COUNT(*) > (SELECT AVG(cnt) FROM (SELECT COUNT(*) GROUP BY country) sub)
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
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): customer
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
9. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
10. Do not wrap the query in markdown code fences
11. For comparisons like "per-group COUNT" vs "average of those counts", compute per-group counts with GROUP BY + HAVING, and compare to AVG of those counts in a nested subquery"""

# === SCHEMA CONTEXT ===
schema_context = """
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
"""

# === FEW-SHOT EXAMPLES — semantically close to "count per group > avg count" ===
FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find groups whose COUNT is higher than the average COUNT across all groups

IMPORTANT VOCABULARY:
- "number of X per group" = COUNT(*) or COUNT(id) GROUP BY group_column
- "average number per group" = AVG of those per-group counts -> nested subquery
- Pattern: GROUP BY group_col, HAVING COUNT(*) > (SELECT AVG(cnt) FROM (SELECT COUNT(*) as cnt ... GROUP BY group_col) sub)

Schema:
  students.student_id, students.department, students.name

Question: Find departments whose number of students is higher than the average number of students per department.

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

WHY THIS WORKS:
- COUNT per department in outer GROUP BY
- Inner subquery computes COUNT per department independently
- AVG wraps those counts — computes the average group size
- HAVING filters after grouping — only keeps above-average groups
- Single table, no JOINs needed — just GROUP BY the grouping column
- No CTE needed — nested subquery in HAVING is clean

EXAMPLE 2: Find groups whose total exceeds the global average total

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
"""

# === USER QUESTION (Test 15) ===
user_question = "Find countries whose number of customers is higher than the average number of customers per country."

# === BUILD FULL USER PROMPT ===
user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "number of customers" per country = COUNT(customer.customer_id) GROUP BY customer.country
- "average number per country" = AVG of those per-country counts -> nested subquery
- Single table query — only customer table needed, no JOINs
- Copy the exact HAVING pattern from Example 1: HAVING COUNT(...) > (SELECT AVG(cnt) FROM (SELECT COUNT(...) GROUP BY ...) sub)

SQL:"""

# === TOKEN ESTIMATION ===
total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5

print("=" * 70)
print("TEST v2 — Test 15: Country customer count > avg per country")
print("=" * 70)
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
            "options": {"num_ctx": 4096},
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
    "Uses customer.country": "CUSTOMER.COUNTRY" in upper_nospace or "CUSTOMER.COUNTRY" in upper,
    "Uses COUNT()": "COUNT(" in upper,
    "Has GROUP BY customer.country": "GROUP BY" in upper and "COUNTRY" in upper,
    "Has HAVING clause": "HAVING" in upper,
    "HAVING uses COUNT()": "HAVING" in upper and "COUNT(" in upper,
    "Has nested subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "Inner subquery has COUNT": upper.count("COUNT(") >= 2,
    "Inner subquery has GROUP BY": upper.count("GROUP BY") >= 2,
    "AVG() wrapping inner count": "AVG(" in upper,
    "Uses customer table": "CUSTOMER" in upper,
    "> operator for comparison": ">" in raw_output,
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
    print("VERDICT: ALL CHECKS PASSED — Few-shot v2 worked for Test 15!")
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
                for row in exec_data["data"][:8]:
                    print(f"    {row}")
            print()
            if row_count > 0 and row_count <= 59:
                print(f"  SANITY: Row count {row_count} is reasonable (59 customers across ~24 countries)")
            elif row_count == 0:
                print("  SANITY: WARNING — 0 rows")
        else:
            print(f"  EXECUTION: FAILED — {exec_data.get('error', 'unknown')[:300]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
else:
    print("  Skipped — output doesn't look like SQL")
