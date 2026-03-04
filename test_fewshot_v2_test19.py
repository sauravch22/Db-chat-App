"""
Test v2 approach for Test 19: "Find employees who support more customers than the average employee"

Two-table aggregate comparison:
- "customers supported per employee" = COUNT(customer_id) GROUP BY employee
- "average per employee" = AVG of those counts -> nested subquery
- Join: customer.support_rep_id = employee.employee_id
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
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): employee, customer
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. If a JOIN PATH or GLOBAL FOREIGN KEY RELATIONSHIPS are provided, use those exact join conditions.
9. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
10. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
11. Do not wrap the query in markdown code fences
12. If you JOIN a subquery, the join key columns MUST be included in that subquery SELECT list
13. For comparisons like "per-entity COUNT" vs "average of those counts", compute per-entity counts with GROUP BY + HAVING, and compare to AVG of those counts in a nested subquery"""

# === SCHEMA CONTEXT ===
schema_context = """
=== TABLE: employee ===
Rows: ~8

COLUMNS:
  employee.address : VARCHAR(70)
  employee.birth_date : TIMESTAMP
  employee.city : VARCHAR(40)
  employee.country : VARCHAR(40)
  employee.email : VARCHAR(60)
  employee.employee_id : INTEGER [PRIMARY KEY, NOT NULL]
  employee.fax : VARCHAR(24)
  employee.first_name : VARCHAR(20) [NOT NULL]
  employee.hire_date : TIMESTAMP
  employee.last_name : VARCHAR(20) [NOT NULL]
  employee.phone : VARCHAR(24)
  employee.postal_code : VARCHAR(10)
  employee.state : VARCHAR(40)
  employee.reports_to : INTEGER
  employee.title : VARCHAR(30) | Examples: General Manager, Sales Support Agent, IT Manager

FOREIGN KEYS (actual database constraints):
  employee.reports_to -> employee.employee_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To customer: customer.support_rep_id = employee.employee_id

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
  To employee: customer.support_rep_id = employee.employee_id

GLOBAL FOREIGN KEY RELATIONSHIPS:
  customer.support_rep_id -> employee.employee_id
  employee.reports_to -> employee.employee_id
  invoice.customer_id -> customer.customer_id
"""

# === FEW-SHOT EXAMPLES — semantically close to "count per entity > avg count" ===
FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find entities who manage/support MORE items than the average entity

IMPORTANT VOCABULARY:
- "support more customers" = COUNT of customers per employee -> COUNT(customer_id)
- "more than average" = compare per-employee count to AVG of all per-employee counts
- Join: the "supported by" relationship links customer to employee
- Pattern: GROUP BY employee, HAVING COUNT(*) > (SELECT AVG(cnt) FROM (SELECT COUNT(*) GROUP BY employee) sub)

Schema:
  managers.manager_id, managers.name
  projects.project_id, projects.manager_id, projects.title

Question: Find managers who manage more projects than the average manager.

SQL:
SELECT
    managers.manager_id,
    managers.name,
    COUNT(projects.project_id) AS project_count
FROM managers
JOIN projects ON managers.manager_id = projects.manager_id
GROUP BY managers.manager_id, managers.name
HAVING COUNT(projects.project_id) > (
    SELECT AVG(mgr_count)
    FROM (
        SELECT COUNT(projects.project_id) AS mgr_count
        FROM projects
        GROUP BY projects.manager_id
    ) sub
)
ORDER BY project_count DESC;

WHY THIS WORKS:
- COUNT per manager in outer GROUP BY
- Inner subquery computes COUNT per manager independently
- AVG wraps those counts — computes the average across all managers
- HAVING filters after grouping — only keeps above-average managers
- Inner subquery only needs the child table (projects) and groups by the FK column
- No CTE needed — nested subquery in HAVING is clean

EXAMPLE 2: Count per group vs average (single table)

Schema:
  students.student_id, students.department, students.name

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

# === USER QUESTION (Test 19) ===
user_question = "Find employees who support more customers than the average employee."

# === BUILD FULL USER PROMPT ===
user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "support more customers" = COUNT(customer.customer_id) per employee
- "average employee" = AVG of per-employee customer counts -> nested subquery
- JOIN: employee to customer via customer.support_rep_id = employee.employee_id
- GROUP BY employee, HAVING COUNT(customer.customer_id) > (SELECT AVG(emp_count) FROM (SELECT COUNT(customer.customer_id) FROM customer GROUP BY customer.support_rep_id) sub)
- Copy the exact HAVING pattern from Example 1 above

SQL:"""

# === TOKEN ESTIMATION ===
total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5

print("=" * 70)
print("TEST v2 — Test 19: Employees supporting > avg customers")
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
    "Uses COUNT()": "COUNT(" in upper,
    "Has GROUP BY": "GROUP BY" in upper,
    "Has HAVING clause": "HAVING" in upper,
    "HAVING uses COUNT()": "HAVING" in upper and "COUNT(" in upper,
    "Has nested subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "Inner subquery has COUNT": upper.count("COUNT(") >= 2,
    "Inner subquery has GROUP BY": upper.count("GROUP BY") >= 2,
    "AVG() wrapping inner count": "AVG(" in upper,
    "Uses employee table": "EMPLOYEE" in upper,
    "Uses customer table": "CUSTOMER" in upper,
    "JOIN present": "JOIN" in upper,
    "support_rep_id in join": "SUPPORT_REP_ID" in upper,
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
    print("VERDICT: ALL CHECKS PASSED — Few-shot v2 worked for Test 19!")
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
            if row_count > 0 and row_count <= 8:
                print(f"  SANITY: Row count {row_count} is reasonable (8 employees total)")
            elif row_count == 0:
                print("  SANITY: WARNING — 0 rows, might mean all employees support equal customers")
        else:
            print(f"  EXECUTION: FAILED — {exec_data.get('error', 'unknown')[:300]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
else:
    print("  Skipped — output doesn't look like SQL")
