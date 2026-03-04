"""
Qwen3-Coder-Next — 20-query test suite via ngrok endpoint.
Sends DDL-format prompts to the hosted LLM, executes returned SQL locally,
and runs semantic validation against the Chinook PostgreSQL database.

Usage:
    python3 test_qwen3_20.py
    python3 test_qwen3_20.py https://YOUR_NGROK_URL.ngrok.app
"""
import httpx
import time
import sys
import json

# ── Configuration ────────────────────────────────────────────────────────────
QWEN3_URL = sys.argv[1].rstrip("/") + "/v1/chat/completions" if len(sys.argv) > 1 else "https://517d6b5cb913.ngrok.app/v1/chat/completions"
EXECUTE_URL = "http://localhost:8000/api/chat/execute"
CONNECTION_ID = 3
MODEL_NAME = "Qwen/Qwen3-Coder-Next"

# ── Schema (DDL format) ─────────────────────────────────────────────────────
DDL_SCHEMA = """CREATE TABLE artist (
    artist_id INTEGER PRIMARY KEY NOT NULL,
    name VARCHAR(120)
);

CREATE TABLE album (
    album_id INTEGER PRIMARY KEY NOT NULL,
    title VARCHAR(160) NOT NULL,
    artist_id INTEGER NOT NULL,
    FOREIGN KEY (artist_id) REFERENCES artist(artist_id)
);

CREATE TABLE genre (
    genre_id INTEGER PRIMARY KEY NOT NULL,
    name VARCHAR(120)
);

CREATE TABLE media_type (
    media_type_id INTEGER PRIMARY KEY NOT NULL,
    name VARCHAR(120)
);

CREATE TABLE track (
    track_id INTEGER PRIMARY KEY NOT NULL,
    name VARCHAR(200) NOT NULL,
    album_id INTEGER,
    media_type_id INTEGER NOT NULL,
    genre_id INTEGER,
    composer VARCHAR(220),
    milliseconds INTEGER NOT NULL,
    bytes INTEGER,
    unit_price NUMERIC(10, 2) NOT NULL,
    FOREIGN KEY (album_id) REFERENCES album(album_id),
    FOREIGN KEY (genre_id) REFERENCES genre(genre_id),
    FOREIGN KEY (media_type_id) REFERENCES media_type(media_type_id)
);

CREATE TABLE employee (
    employee_id INTEGER PRIMARY KEY NOT NULL,
    last_name VARCHAR(20) NOT NULL,
    first_name VARCHAR(20) NOT NULL,
    title VARCHAR(30),
    reports_to INTEGER,
    birth_date TIMESTAMP,
    hire_date TIMESTAMP,
    address VARCHAR(70),
    city VARCHAR(40),
    state VARCHAR(40),
    country VARCHAR(40),
    postal_code VARCHAR(10),
    phone VARCHAR(24),
    fax VARCHAR(24),
    email VARCHAR(60),
    FOREIGN KEY (reports_to) REFERENCES employee(employee_id)
);

CREATE TABLE customer (
    customer_id INTEGER PRIMARY KEY NOT NULL,
    first_name VARCHAR(40) NOT NULL,
    last_name VARCHAR(20) NOT NULL,
    company VARCHAR(80),
    address VARCHAR(70),
    city VARCHAR(40),
    state VARCHAR(40),
    country VARCHAR(40),
    postal_code VARCHAR(10),
    phone VARCHAR(24),
    fax VARCHAR(24),
    email VARCHAR(60) NOT NULL,
    support_rep_id INTEGER,
    FOREIGN KEY (support_rep_id) REFERENCES employee(employee_id)
);

CREATE TABLE invoice (
    invoice_id INTEGER PRIMARY KEY NOT NULL,
    customer_id INTEGER NOT NULL,
    invoice_date TIMESTAMP NOT NULL,
    total NUMERIC(10, 2) NOT NULL,
    billing_address VARCHAR(70),
    billing_city VARCHAR(40),
    billing_country VARCHAR(40),
    billing_postal_code VARCHAR(10),
    billing_state VARCHAR(40),
    FOREIGN KEY (customer_id) REFERENCES customer(customer_id)
);

CREATE TABLE invoice_line (
    invoice_line_id INTEGER PRIMARY KEY NOT NULL,
    invoice_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,
    quantity INTEGER NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES invoice(invoice_id),
    FOREIGN KEY (track_id) REFERENCES track(track_id)
);"""

SYSTEM_PROMPT = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. Use ONLY table/column names from the CREATE TABLE statements — do not guess or invent names
5. Always use table-qualified column names (table.column)
6. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
7. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
8. Do not wrap the query in markdown code fences"""

# ── 20 Test Queries ─────────────────────────────────────────────────────────
# Difficulty mix: 6 EASY, 6 MEDIUM, 8 HARD
TEST_QUERIES = [
    # ── EASY (single table or simple join) ──────────────────────────────────
    {
        "id": 1, "difficulty": "EASY",
        "question": "List all customers with their full name and email.",
        "expected_rows": (59, 59),
        "reference_sql": "SELECT customer.first_name, customer.last_name, customer.email FROM customer",
        "must_have_tables": ["customer"],
        "must_have_columns": ["first_name", "last_name", "email"],
        "must_not_have": [],
    },
    {
        "id": 2, "difficulty": "EASY",
        "question": "How many tracks are in each genre? Show genre name and count.",
        "expected_rows": (25, 25),
        "reference_sql": "SELECT genre.name, COUNT(track.track_id) FROM track JOIN genre ON track.genre_id = genre.genre_id GROUP BY genre.name",
        "must_have_tables": ["track", "genre"],
        "must_have_columns": ["name", "count"],
        "must_not_have": [],
    },
    {
        "id": 3, "difficulty": "EASY",
        "question": "List all tracks that are longer than 5 minutes.",
        "expected_rows": (1000, 1200),
        "reference_sql": "SELECT track.track_id, track.name, track.milliseconds FROM track WHERE track.milliseconds > 300000",
        "must_have_tables": ["track"],
        "must_have_columns": ["track_id", "name"],
        "must_not_have": [],
    },
    {
        "id": 4, "difficulty": "EASY",
        "question": "Show all customers from the USA.",
        "expected_rows": (13, 13),
        "reference_sql": "SELECT customer.customer_id, customer.first_name, customer.last_name FROM customer WHERE customer.country = 'USA'",
        "must_have_tables": ["customer"],
        "must_have_columns": ["first_name", "last_name"],
        "must_not_have": [],
    },
    {
        "id": 5, "difficulty": "EASY",
        "question": "How many tracks are in the Rock genre?",
        "expected_rows": (1, 1),
        "reference_sql": "SELECT COUNT(*) FROM track JOIN genre ON track.genre_id = genre.genre_id WHERE genre.name = 'Rock'",
        "must_have_tables": ["track", "genre"],
        "must_have_columns": [],
        "must_not_have": [],
    },
    {
        "id": 6, "difficulty": "EASY",
        "question": "List all employees and their job titles.",
        "expected_rows": (8, 8),
        "reference_sql": "SELECT employee.first_name, employee.last_name, employee.title FROM employee",
        "must_have_tables": ["employee"],
        "must_have_columns": ["first_name", "last_name", "title"],
        "must_not_have": [],
    },
    # ── MEDIUM (joins, grouping, HAVING, ORDER BY + LIMIT) ─────────────────
    {
        "id": 7, "difficulty": "MEDIUM",
        "question": "Show the top 5 customers by total spending.",
        "expected_rows": (5, 5),
        "reference_sql": "SELECT customer.customer_id, customer.first_name, customer.last_name, SUM(invoice.total) AS total_spending FROM customer JOIN invoice ON customer.customer_id = invoice.customer_id GROUP BY customer.customer_id, customer.first_name, customer.last_name ORDER BY total_spending DESC LIMIT 5",
        "must_have_tables": ["customer", "invoice"],
        "must_have_columns": ["total"],
        "must_not_have": [],
    },
    {
        "id": 8, "difficulty": "MEDIUM",
        "question": "Find all albums that have more than 20 tracks.",
        "expected_rows": (17, 17),
        "reference_sql": "SELECT album.album_id, album.title FROM album JOIN track ON album.album_id = track.album_id GROUP BY album.album_id, album.title HAVING COUNT(track.track_id) > 20",
        "must_have_tables": ["album", "track"],
        "must_have_columns": ["album_id"],
        "must_not_have": [],
    },
    {
        "id": 9, "difficulty": "MEDIUM",
        "question": "Show each employee and the number of customers they support.",
        "expected_rows": (3, 8),
        "reference_sql": "SELECT employee.first_name, employee.last_name, COUNT(customer.customer_id) AS customer_count FROM employee JOIN customer ON employee.employee_id = customer.support_rep_id GROUP BY employee.employee_id, employee.first_name, employee.last_name",
        "must_have_tables": ["employee", "customer"],
        "must_have_columns": ["first_name", "last_name"],
        "must_not_have": [],
    },
    {
        "id": 10, "difficulty": "MEDIUM",
        "question": "Show the total revenue for each genre, ordered by revenue descending.",
        "expected_rows": (25, 25),
        "reference_sql": "SELECT genre.name, SUM(invoice_line.unit_price * invoice_line.quantity) AS revenue FROM genre JOIN track ON genre.genre_id = track.genre_id JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY genre.name ORDER BY revenue DESC",
        "must_have_tables": ["genre", "track", "invoice_line"],
        "must_have_columns": ["name"],
        "must_not_have": [],
    },
    {
        "id": 11, "difficulty": "MEDIUM",
        "question": "Find employees who report to a manager. Show employee name and manager name.",
        "expected_rows": (6, 7),
        "reference_sql": "SELECT e.first_name, e.last_name, m.first_name AS manager_first, m.last_name AS manager_last FROM employee e JOIN employee m ON e.reports_to = m.employee_id",
        "must_have_tables": ["employee"],
        "must_have_columns": ["first_name", "last_name"],
        "must_not_have": [],
    },
    {
        "id": 12, "difficulty": "MEDIUM",
        "question": "Show the top 10 artists by number of albums.",
        "expected_rows": (10, 10),
        "reference_sql": "SELECT artist.name, COUNT(album.album_id) AS album_count FROM artist JOIN album ON artist.artist_id = album.artist_id GROUP BY artist.artist_id, artist.name ORDER BY album_count DESC LIMIT 10",
        "must_have_tables": ["artist", "album"],
        "must_have_columns": ["name"],
        "must_not_have": [],
    },
    # ── HARD (nested subqueries, compare-to-average, correlated, multi-join) ─
    {
        "id": 13, "difficulty": "HARD",
        "question": "Find customers whose total spending is higher than the average customer spending.",
        "expected_rows": (10, 40),
        "reference_sql": "SELECT customer.customer_id, customer.first_name, customer.last_name, SUM(invoice.total) AS total_spending FROM customer JOIN invoice ON customer.customer_id = invoice.customer_id GROUP BY customer.customer_id, customer.first_name, customer.last_name HAVING SUM(invoice.total) > (SELECT AVG(cust_total) FROM (SELECT SUM(invoice.total) AS cust_total FROM invoice GROUP BY invoice.customer_id) sub)",
        "must_have_tables": ["customer", "invoice"],
        "must_have_columns": ["customer_id"],
        "must_not_have": [],
    },
    {
        "id": 14, "difficulty": "HARD",
        "question": "Find tracks whose sales count is higher than the average sales count of tracks in the same genre.",
        "expected_rows": (50, 1000),
        "reference_sql": "SELECT track.track_id, track.name FROM track JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY track.track_id, track.name, track.genre_id HAVING COUNT(invoice_line.invoice_line_id) > (SELECT AVG(tc) FROM (SELECT track.genre_id AS gid, COUNT(invoice_line.invoice_line_id) AS tc FROM track JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY track.track_id, track.genre_id) sub WHERE sub.gid = track.genre_id)",
        "must_have_tables": ["track", "invoice_line"],
        "must_have_columns": ["track_id"],
        "must_not_have": ["milliseconds"],
    },
    {
        "id": 15, "difficulty": "HARD",
        "question": "Find artists whose total revenue is greater than the average artist revenue.",
        "expected_rows": (20, 150),
        "reference_sql": "SELECT artist.artist_id, artist.name, SUM(invoice_line.unit_price * invoice_line.quantity) AS total_revenue FROM artist JOIN album ON artist.artist_id = album.artist_id JOIN track ON album.album_id = track.album_id JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY artist.artist_id, artist.name HAVING SUM(invoice_line.unit_price * invoice_line.quantity) > (SELECT AVG(ar) FROM (SELECT SUM(invoice_line.unit_price * invoice_line.quantity) AS ar FROM artist JOIN album ON artist.artist_id = album.artist_id JOIN track ON album.album_id = track.album_id JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY artist.artist_id) sub)",
        "must_have_tables": ["artist", "album", "track", "invoice_line"],
        "must_have_columns": ["artist_id", "name"],
        "must_not_have": [],
    },
    {
        "id": 16, "difficulty": "HARD",
        "question": "Find albums whose total duration is greater than the average album duration.",
        "expected_rows": (30, 200),
        "reference_sql": "SELECT album.album_id, album.title, SUM(track.milliseconds) AS total_duration FROM album JOIN track ON album.album_id = track.album_id GROUP BY album.album_id, album.title HAVING SUM(track.milliseconds) > (SELECT AVG(album_dur) FROM (SELECT SUM(track.milliseconds) AS album_dur FROM track GROUP BY track.album_id) sub)",
        "must_have_tables": ["album", "track"],
        "must_have_columns": ["album_id", "milliseconds"],
        "must_not_have": [],
    },
    {
        "id": 17, "difficulty": "HARD",
        "question": "Find countries where total invoice amount is above the average country total.",
        "expected_rows": (5, 15),
        "reference_sql": "SELECT invoice.billing_country, SUM(invoice.total) AS country_total FROM invoice GROUP BY invoice.billing_country HAVING SUM(invoice.total) > (SELECT AVG(ct) FROM (SELECT SUM(total) AS ct FROM invoice GROUP BY billing_country) sub)",
        "must_have_tables": ["invoice"],
        "must_have_columns": ["billing_country", "total"],
        "must_not_have": [],
    },
    {
        "id": 18, "difficulty": "HARD",
        "question": "Find genres that have more tracks than the average number of tracks per genre.",
        "expected_rows": (3, 12),
        "reference_sql": "SELECT genre.name, COUNT(track.track_id) AS track_count FROM genre JOIN track ON genre.genre_id = track.genre_id GROUP BY genre.genre_id, genre.name HAVING COUNT(track.track_id) > (SELECT AVG(gc) FROM (SELECT COUNT(track_id) AS gc FROM track WHERE genre_id IS NOT NULL GROUP BY genre_id) sub)",
        "must_have_tables": ["genre", "track"],
        "must_have_columns": ["name"],
        "must_not_have": [],
    },
    {
        "id": 19, "difficulty": "HARD",
        "question": "Which customers have made more purchases (invoices) than the average number of invoices per customer?",
        "expected_rows": (10, 40),
        "reference_sql": "SELECT customer.customer_id, customer.first_name, customer.last_name, COUNT(invoice.invoice_id) AS invoice_count FROM customer JOIN invoice ON customer.customer_id = invoice.customer_id GROUP BY customer.customer_id, customer.first_name, customer.last_name HAVING COUNT(invoice.invoice_id) > (SELECT AVG(ic) FROM (SELECT COUNT(invoice_id) AS ic FROM invoice GROUP BY customer_id) sub)",
        "must_have_tables": ["customer", "invoice"],
        "must_have_columns": ["customer_id"],
        "must_not_have": [],
    },
    {
        "id": 20, "difficulty": "HARD",
        "question": "Find the album with the longest total duration. Show album title and total milliseconds.",
        "expected_rows": (1, 1),
        "reference_sql": "SELECT album.title, SUM(track.milliseconds) AS total_ms FROM album JOIN track ON album.album_id = track.album_id GROUP BY album.album_id, album.title ORDER BY total_ms DESC LIMIT 1",
        "must_have_tables": ["album", "track"],
        "must_have_columns": ["title", "milliseconds"],
        "must_not_have": [],
    },
]


# ── Helper Functions ─────────────────────────────────────────────────────────

def call_qwen3(question: str) -> dict:
    """Call Qwen3-Coder-Next via OpenAI-compatible API."""
    user_content = f"### Database Schema\n\n{DDL_SCHEMA}\n\n### Task\n{question}\n\n### SQL\n"
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
    }
    start = time.time()
    with httpx.Client(timeout=180.0) as client:
        resp = client.post(QWEN3_URL, json=payload, headers={"Content-Type": "application/json"})
    elapsed = time.time() - start
    data = resp.json()
    choice = data.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "").strip()
    usage = data.get("usage", {})
    return {
        "response": content,
        "prompt_tokens": usage.get("prompt_tokens", "?"),
        "output_tokens": usage.get("completion_tokens", "?"),
        "elapsed": elapsed,
    }


def clean_sql(raw: str) -> str:
    """Extract clean SQL from model output."""
    raw = raw.replace("```sql", "").replace("```", "").strip()
    upper = raw.upper()
    with_pos = upper.find("WITH")
    select_pos = upper.find("SELECT")
    candidates = []
    if with_pos >= 0:
        candidates.append(with_pos)
    if select_pos >= 0:
        candidates.append(select_pos)
    if candidates:
        start = min(candidates)
        if start > 0:
            raw = raw[start:]
    if ";" in raw:
        raw = raw[:raw.index(";") + 1]
    return raw.strip().rstrip('"').rstrip("'").strip()


def execute_sql(sql: str) -> dict:
    """Execute SQL on Chinook via the local API."""
    try:
        resp = httpx.post(EXECUTE_URL, json={"connection_id": CONNECTION_ID, "sql": sql}, timeout=30.0)
        return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_semantic(sql: str, test: dict, row_count: int) -> dict:
    """Semantic validation: row range, tables, columns, anti-patterns, reference match."""
    upper = sql.upper()
    issues = []
    scores = {}

    # 1. Row count range
    exp_min, exp_max = test.get("expected_rows", (0, 999999))
    rows_ok = exp_min <= row_count <= exp_max
    scores["rows_in_range"] = rows_ok
    if not rows_ok:
        issues.append(f"Row count {row_count} outside expected [{exp_min}-{exp_max}]")

    # 2. Required tables
    for tbl in test.get("must_have_tables", []):
        present = tbl.upper() in upper
        scores[f"has_table_{tbl}"] = present
        if not present:
            issues.append(f"Missing required table: {tbl}")

    # 3. Required columns
    for col in test.get("must_have_columns", []):
        present = col.upper() in upper
        scores[f"has_col_{col}"] = present
        if not present:
            issues.append(f"Missing required column: {col}")

    # 4. Anti-patterns (check as whole-word where possible)
    for bad in test.get("must_not_have", []):
        # Check if the anti-pattern appears as a column reference (not inside an alias name)
        bad_upper = bad.upper()
        # Simple check: is it in the SQL?
        found = False
        if bad_upper in upper:
            # Filter out alias false positives: if "DURATION" appears only
            # inside words like "TOTAL_DURATION" or "ALBUM_DURATION", skip it
            import re
            # Match as a standalone word (column reference)
            pattern = r'(?<![A-Z_])' + re.escape(bad_upper) + r'(?![A-Z_])'
            if re.search(pattern, upper):
                found = True
        if found:
            scores[f"no_{bad}"] = False
            issues.append(f"Contains anti-pattern: '{bad}'")
        else:
            scores[f"no_{bad}"] = True

    # 5. Join correctness
    join_ok = True
    if "ARTIST_ID = TRACK_ID" in upper or "TRACK_ID = ARTIST_ID" in upper:
        issues.append("Wrong join: artist_id = track_id")
        join_ok = False
    if "INVOICE_LINE.CUSTOMER_ID" in upper:
        issues.append("Wrong column: invoice_line.customer_id doesn't exist")
        join_ok = False
    scores["no_join_errors"] = join_ok

    # 6. Cross-validate with reference SQL
    ref_sql = test.get("reference_sql", "")
    ref_row_count = None
    if ref_sql and row_count > 0:
        ref_result = execute_sql(ref_sql)
        if ref_result.get("success"):
            ref_row_count = ref_result.get("row_count", 0)
            tolerance = max(2, int(ref_row_count * 0.1))
            ref_matches = abs(row_count - ref_row_count) <= tolerance
            scores["matches_reference"] = ref_matches
            if not ref_matches:
                issues.append(f"Row mismatch vs reference: got {row_count}, expected ~{ref_row_count}")

    total = len(scores)
    passed = sum(1 for v in scores.values() if v)
    return {
        "semantic_pass": len(issues) == 0,
        "score": f"{passed}/{total}",
        "issues": issues,
        "ref_row_count": ref_row_count,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print(f"  QWEN3-CODER-NEXT — 20-Query Test Suite")
    print(f"  Endpoint: {QWEN3_URL}")
    print(f"  Model:    {MODEL_NAME}")
    print("=" * 80)

    # Verify execute endpoint
    test_exec = execute_sql("SELECT 1")
    if not test_exec.get("success"):
        print(f"  ❌ Execute endpoint not working: {test_exec.get('error', '?')}")
        return
    print("  ✅ Execute endpoint working")

    # Quick endpoint check
    print(f"  ⏳ Testing LLM endpoint...")
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(QWEN3_URL, json={
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": "SELECT 1"}],
                "max_tokens": 10,
            }, headers={"Content-Type": "application/json"})
            if r.status_code == 200:
                print(f"  ✅ LLM endpoint reachable (status {r.status_code})")
            else:
                print(f"  ⚠️  LLM endpoint returned status {r.status_code}")
                print(f"     {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ Cannot reach LLM endpoint: {e}")
        return

    results = []
    total_start = time.time()

    for test in TEST_QUERIES:
        qid = test["id"]
        diff = test["difficulty"]
        q = test["question"]

        print(f"\n{'─' * 78}")
        print(f"  TEST {qid:>2} [{diff:>6}]: {q}")
        print(f"{'─' * 78}")

        # Call Qwen3
        try:
            result = call_qwen3(q)
        except Exception as e:
            print(f"  ❌ API ERROR: {e}")
            results.append({
                "id": qid, "difficulty": diff, "question": q,
                "exec": False, "semantic_pass": False,
                "error": str(e)[:100], "sql": "", "rows": 0,
                "semantic_score": "N/A", "issues": [str(e)[:100]],
                "tokens_in": "?", "tokens_out": "?", "time": 0,
            })
            continue

        sql = clean_sql(result["response"])
        print(f"  Tokens: {result['prompt_tokens']}→{result['output_tokens']} | Time: {result['elapsed']:.1f}s")
        print(f"  SQL: {sql[:160]}")
        if len(sql) > 160:
            print(f"       {sql[160:320]}")

        # Execute locally
        exec_result = execute_sql(sql)
        exec_ok = exec_result.get("success", False)
        row_count = exec_result.get("row_count", 0) if exec_ok else 0
        exec_error = exec_result.get("error", "")[:200] if not exec_ok else ""

        exec_icon = "✅ SUCCESS" if exec_ok else "❌ FAILED"
        print(f"  Exec: {exec_icon} | Rows: {row_count}", end="")
        if exec_error:
            print(f" | Error: {exec_error[:100]}")
        else:
            print()

        # Semantic validation
        sem = None
        if exec_ok:
            sem = check_semantic(sql, test, row_count)
            icon = "✅" if sem["semantic_pass"] else "⚠️"
            print(f"  Semantic: {icon} {sem['score']}", end="")
            if sem["ref_row_count"] is not None:
                print(f" | Ref rows: {sem['ref_row_count']}")
            else:
                print()
            if sem["issues"]:
                for iss in sem["issues"]:
                    print(f"    ⚠ {iss}")

        results.append({
            "id": qid,
            "difficulty": diff,
            "question": q,
            "sql": sql,
            "exec": exec_ok,
            "rows": row_count,
            "error": exec_error,
            "semantic_pass": sem["semantic_pass"] if sem else False,
            "semantic_score": sem["score"] if sem else "N/A",
            "issues": sem["issues"] if sem else [exec_error or "exec failed"],
            "tokens_in": result["prompt_tokens"],
            "tokens_out": result["output_tokens"],
            "time": result["elapsed"],
        })

    total_elapsed = time.time() - total_start

    # ── SUMMARY TABLE ────────────────────────────────────────────────────────
    print(f"\n\n{'#' * 80}")
    print(f"  SUMMARY — {MODEL_NAME}")
    print(f"  Total time: {total_elapsed:.1f}s")
    print(f"{'#' * 80}")

    print(f"\n  {'#':>2} {'Diff':>6} │ {'Exec':^6} │ {'Semantic':^10} │ {'Rows':>6} │ Notes")
    print(f"  {'─'*2}─{'─'*6}─┼─{'─'*6}─┼─{'─'*10}─┼─{'─'*6}─┼─{'─'*40}")

    for r in results:
        exec_icon = "✅" if r["exec"] else "❌"
        sem_icon = "✅" if r["semantic_pass"] else "❌"
        notes = "; ".join(r.get("issues", []))[:45] if r.get("issues") and not r["semantic_pass"] else ""
        print(f"  {r['id']:>2} {r['difficulty']:>6} │  {exec_icon}   │  {sem_icon} {r.get('semantic_score', 'N/A'):>7} │ {r.get('rows', 0):>5} │ {notes}")

    # ── AGGREGATE SCORES ─────────────────────────────────────────────────────
    n = len(results)
    exec_pass = sum(1 for r in results if r["exec"])
    sem_pass = sum(1 for r in results if r["semantic_pass"])

    easy = [r for r in results if r["difficulty"] == "EASY"]
    med = [r for r in results if r["difficulty"] == "MEDIUM"]
    hard = [r for r in results if r["difficulty"] == "HARD"]

    easy_sem = sum(1 for r in easy if r["semantic_pass"])
    med_sem = sum(1 for r in med if r["semantic_pass"])
    hard_sem = sum(1 for r in hard if r["semantic_pass"])

    print(f"\n  ═══════════════════════════════════════════════════════════")
    print(f"  OVERALL:")
    print(f"    Execution:  {exec_pass}/{n} ({exec_pass*100//n}%)")
    print(f"    Semantic:   {sem_pass}/{n} ({sem_pass*100//n}%)")
    print(f"")
    print(f"  BY DIFFICULTY:")
    print(f"    EASY:   {easy_sem}/{len(easy)}  ({easy_sem*100//len(easy) if easy else 0}%)")
    print(f"    MEDIUM: {med_sem}/{len(med)}  ({med_sem*100//len(med) if med else 0}%)")
    print(f"    HARD:   {hard_sem}/{len(hard)}  ({hard_sem*100//len(hard) if hard else 0}%)")

    print(f"\n  ── COMPARISON WITH LOCAL MODELS (DDL format, 8-query suite) ──")
    print(f"  {'Model':<30} │ {'Exec':>6} │ {'Semantic':>8} │ {'HARD':>6}")
    print(f"  {'─'*30}─┼─{'─'*6}─┼─{'─'*8}─┼─{'─'*6}")
    print(f"  {'Mistral 7B (8q)':<30} │ {'7/8':>6} │ {'3/8':>8} │ {'1/4':>6}")
    print(f"  {'SQLCoder (8q)':<30} │ {'8/8':>6} │ {'4/8':>8} │ {'0/4':>6}")
    print(f"  {'Qwen3-Coder-Next (20q)':<30} │ {f'{exec_pass}/{n}':>6} │ {f'{sem_pass}/{n}':>8} │ {f'{hard_sem}/{len(hard)}':>6}")
    print(f"  ═══════════════════════════════════════════════════════════")

    # ── FAILED TESTS DETAIL ──────────────────────────────────────────────────
    failed = [r for r in results if not r["semantic_pass"]]
    if failed:
        print(f"\n\n{'=' * 80}")
        print(f"  FAILED TESTS — DETAIL")
        print(f"{'=' * 80}")
        for r in failed:
            exec_mark = '✅' if r['exec'] else '❌'
            print(f"\n  Test {r['id']} [{r['difficulty']}]: {r['question']}")
            print(f"  [exec:{exec_mark} sem:❌]")
            print(f"  SQL: {r.get('sql', 'N/A')}")
            if r.get("issues"):
                for iss in r["issues"]:
                    print(f"    ⚠ {iss}")
            if r.get("error"):
                print(f"    Error: {r['error']}")

    # ── ALL HARD QUERY SQL ───────────────────────────────────────────────────
    print(f"\n\n{'=' * 80}")
    print(f"  ALL HARD QUERY SQL")
    print(f"{'=' * 80}")
    for r in results:
        if r["difficulty"] != "HARD":
            continue
        exec_mark = '✅' if r['exec'] else '❌'
        sem_mark = '✅' if r['semantic_pass'] else '❌'
        print(f"\n  Test {r['id']}: {r['question']}")
        print(f"  [exec:{exec_mark} sem:{sem_mark} rows:{r.get('rows',0)}]")
        print(f"  {r.get('sql', 'N/A')}")


if __name__ == "__main__":
    main()
