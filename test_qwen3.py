"""
Test Qwen3-Coder-Next via ngrok endpoint on all 8 test queries.
Validates returned SQL against local Chinook DB.
"""
import httpx
import time
import json

QWEN3_URL = "https://517d6b5cb913.ngrok.app/v1/chat/completions"
EXECUTE_URL = "http://localhost:8000/api/chat/execute"
CONNECTION_ID = 3

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

TEST_QUERIES = [
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
        "id": 3, "difficulty": "MEDIUM",
        "question": "Show the top 5 customers by total spending.",
        "expected_rows": (5, 5),
        "reference_sql": "SELECT customer.customer_id, customer.first_name, customer.last_name, SUM(invoice.total) AS total_spending FROM customer JOIN invoice ON customer.customer_id = invoice.customer_id GROUP BY customer.customer_id, customer.first_name, customer.last_name ORDER BY total_spending DESC LIMIT 5",
        "must_have_tables": ["customer", "invoice"],
        "must_have_columns": ["total"],
        "must_not_have": ["invoice_line"],
    },
    {
        "id": 4, "difficulty": "MEDIUM",
        "question": "Find all albums that have more than 20 tracks.",
        "expected_rows": (17, 17),
        "reference_sql": "SELECT album.album_id, album.title FROM album JOIN track ON album.album_id = track.album_id GROUP BY album.album_id, album.title HAVING COUNT(track.track_id) > 20",
        "must_have_tables": ["album", "track"],
        "must_have_columns": ["album_id"],
        "must_not_have": [],
    },
    {
        "id": 5, "difficulty": "HARD",
        "question": "Find customers whose total spending is higher than the average customer spending.",
        "expected_rows": (10, 40),
        "reference_sql": "SELECT customer.customer_id, customer.first_name, customer.last_name, SUM(invoice.total) AS total_spending FROM customer JOIN invoice ON customer.customer_id = invoice.customer_id GROUP BY customer.customer_id, customer.first_name, customer.last_name HAVING SUM(invoice.total) > (SELECT AVG(cust_total) FROM (SELECT SUM(invoice.total) AS cust_total FROM invoice GROUP BY invoice.customer_id) sub)",
        "must_have_tables": ["customer", "invoice"],
        "must_have_columns": ["customer_id"],
        "must_not_have": [],
    },
    {
        "id": 6, "difficulty": "HARD",
        "question": "Find tracks whose sales count is higher than the average sales count of tracks in the same genre.",
        "expected_rows": (50, 1000),
        "reference_sql": "SELECT track.track_id, track.name FROM track JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY track.track_id, track.name, track.genre_id HAVING COUNT(invoice_line.invoice_line_id) > (SELECT AVG(tc) FROM (SELECT track.genre_id AS gid, COUNT(invoice_line.invoice_line_id) AS tc FROM track JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY track.track_id, track.genre_id) sub WHERE sub.gid = track.genre_id)",
        "must_have_tables": ["track", "invoice_line"],
        "must_have_columns": ["track_id"],
        "must_not_have": ["milliseconds"],
    },
    {
        "id": 7, "difficulty": "HARD",
        "question": "Find artists whose total revenue is greater than the average artist revenue.",
        "expected_rows": (20, 150),
        "reference_sql": "SELECT artist.artist_id, artist.name, SUM(invoice_line.unit_price * invoice_line.quantity) AS total_revenue FROM artist JOIN album ON artist.artist_id = album.artist_id JOIN track ON album.album_id = track.album_id JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY artist.artist_id, artist.name HAVING SUM(invoice_line.unit_price * invoice_line.quantity) > (SELECT AVG(ar) FROM (SELECT SUM(invoice_line.unit_price * invoice_line.quantity) AS ar FROM artist JOIN album ON artist.artist_id = album.artist_id JOIN track ON album.album_id = track.album_id JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY artist.artist_id) sub)",
        "must_have_tables": ["artist", "album", "track", "invoice_line"],
        "must_have_columns": ["artist_id", "name"],
        "must_not_have": [],
    },
    {
        "id": 8, "difficulty": "HARD",
        "question": "Find albums whose total duration is greater than the average album duration.",
        "expected_rows": (30, 200),
        "reference_sql": "SELECT album.album_id, album.title, SUM(track.milliseconds) AS total_duration FROM album JOIN track ON album.album_id = track.album_id GROUP BY album.album_id, album.title HAVING SUM(track.milliseconds) > (SELECT AVG(album_dur) FROM (SELECT SUM(track.milliseconds) AS album_dur FROM track GROUP BY track.album_id) sub)",
        "must_have_tables": ["album", "track"],
        "must_have_columns": ["album_id", "milliseconds"],
        "must_not_have": ["duration"],
    },
]


def call_qwen3(question: str) -> dict:
    """Call Qwen3-Coder-Next via ngrok OpenAI-compatible API."""
    user_content = f"### Database Schema\n\n{DDL_SCHEMA}\n\n### Task\n{question}\n\n### SQL\n"

    payload = {
        "model": "Qwen/Qwen3-Coder-Next",
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
    if with_pos >= 0: candidates.append(with_pos)
    if select_pos >= 0: candidates.append(select_pos)
    if candidates:
        start = min(candidates)
        if start > 0:
            raw = raw[start:]
    if ";" in raw:
        raw = raw[:raw.index(";") + 1]
    return raw.strip().rstrip('"').rstrip("'").strip()


def execute_sql(sql: str) -> dict:
    """Execute SQL on Chinook via the API."""
    try:
        resp = httpx.post(EXECUTE_URL, json={"connection_id": CONNECTION_ID, "sql": sql}, timeout=30.0)
        return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_semantic(sql: str, test: dict, row_count: int) -> dict:
    """Semantic validation."""
    upper = sql.upper()
    issues = []
    scores = {}

    # Row count range
    exp_min, exp_max = test.get("expected_rows", (0, 999999))
    rows_ok = exp_min <= row_count <= exp_max
    scores["rows_in_range"] = rows_ok
    if not rows_ok:
        issues.append(f"Row count {row_count} outside expected [{exp_min}–{exp_max}]")

    # Required tables
    for tbl in test.get("must_have_tables", []):
        present = tbl.upper() in upper
        scores[f"has_table_{tbl}"] = present
        if not present:
            issues.append(f"Missing required table: {tbl}")

    # Required columns
    for col in test.get("must_have_columns", []):
        present = col.upper() in upper
        scores[f"has_col_{col}"] = present
        if not present:
            issues.append(f"Missing required column: {col}")

    # Anti-patterns
    for bad in test.get("must_not_have", []):
        if bad.upper() in upper:
            scores[f"no_{bad}"] = False
            issues.append(f"Contains anti-pattern: '{bad}'")
        else:
            scores[f"no_{bad}"] = True

    # Join correctness
    if "ARTIST_ID = TRACK_ID" in upper or "TRACK_ID = ARTIST_ID" in upper:
        issues.append("Wrong join: artist_id = track_id")
        scores["no_join_errors"] = False
    else:
        scores["no_join_errors"] = True

    # Cross-validate with reference SQL
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


def main():
    print("=" * 80)
    print("  QWEN3-CODER-NEXT — Full Test Suite (8 queries)")
    print(f"  Endpoint: {QWEN3_URL}")
    print("=" * 80)

    # Verify execute endpoint
    test_exec = execute_sql("SELECT 1")
    if not test_exec.get("success"):
        print(f"❌ Execute endpoint not working: {test_exec.get('error', '?')}")
        return
    print("✅ Execute endpoint working\n")

    results = []

    for test in TEST_QUERIES:
        qid = test["id"]
        diff = test["difficulty"]
        q = test["question"]

        print(f"\n{'─' * 78}")
        print(f"  TEST {qid} [{diff}]: {q}")
        print(f"{'─' * 78}")

        # Call Qwen3
        try:
            result = call_qwen3(q)
        except Exception as e:
            print(f"  ❌ API ERROR: {e}")
            results.append({"id": qid, "difficulty": diff, "exec": False, "semantic_pass": False, "error": str(e)})
            continue

        sql = clean_sql(result["response"])
        print(f"  Tokens: {result['prompt_tokens']}→{result['output_tokens']} | Time: {result['elapsed']:.1f}s")
        print(f"  SQL: {sql[:150]}")
        if len(sql) > 150:
            print(f"       {sql[150:]}")

        # Execute locally
        exec_result = execute_sql(sql)
        exec_ok = exec_result.get("success", False)
        row_count = exec_result.get("row_count", 0) if exec_ok else 0
        exec_error = exec_result.get("error", "")[:200] if not exec_ok else ""

        print(f"  Exec: {'✅ SUCCESS' if exec_ok else '❌ FAILED'} | Rows: {row_count}", end="")
        if exec_error:
            print(f" | Error: {exec_error}")
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
            "issues": sem["issues"] if sem else [exec_error],
            "tokens_in": result["prompt_tokens"],
            "tokens_out": result["output_tokens"],
            "time": result["elapsed"],
        })

    # ── SUMMARY ──
    print(f"\n\n{'#' * 80}")
    print(f"  SUMMARY — Qwen3-Coder-Next (DDL format)")
    print(f"{'#' * 80}")

    print(f"\n  {'#':>2} {'Diff':>6} │ {'Exec':^6} │ {'Semantic':^10} │ {'Rows':>6} │ Notes")
    print(f"  {'─'*2}─{'─'*6}─┼─{'─'*6}─┼─{'─'*10}─┼─{'─'*6}─┼─{'─'*30}")

    for r in results:
        exec_icon = "✅" if r["exec"] else "❌"
        sem_icon = "✅" if r["semantic_pass"] else "❌"
        notes = "; ".join(r.get("issues", []))[:50] if r.get("issues") else ""
        rows = r.get("rows", 0)
        print(f"  {r['id']:>2} {r['difficulty']:>6} │  {exec_icon}   │  {sem_icon} {r.get('semantic_score', 'N/A'):>7} │ {rows:>5} │ {notes}")

    n = len(results)
    exec_pass = sum(1 for r in results if r["exec"])
    sem_pass = sum(1 for r in results if r["semantic_pass"])
    hard_tests = [r for r in results if r["difficulty"] == "HARD"]
    hard_sem = sum(1 for r in hard_tests if r["semantic_pass"])

    print(f"\n  EXECUTION: {exec_pass}/{n} ({exec_pass*100//n}%)")
    print(f"  SEMANTIC:  {sem_pass}/{n} ({sem_pass*100//n}%)")
    print(f"  HARD only: {hard_sem}/{len(hard_tests)} ({hard_sem*100//len(hard_tests) if hard_tests else 0}%)")

    print(f"\n  ── COMPARISON WITH LOCAL MODELS (DDL format) ──")
    print(f"  {'Model':<25} │ {'Exec':>6} │ {'Semantic':>8} │ {'HARD':>6}")
    print(f"  {'─'*25}─┼─{'─'*6}─┼─{'─'*8}─┼─{'─'*6}")
    print(f"  {'Mistral 7B (local)':<25} │ {'7/8':>6} │ {'3/8':>8} │ {'1/4':>6}")
    print(f"  {'SQLCoder (local)':<25} │ {'8/8':>6} │ {'4/8':>8} │ {'0/4':>6}")
    print(f"  {'Qwen3-Coder-Next (API)':<25} │ {f'{exec_pass}/{n}':>6} │ {f'{sem_pass}/{n}':>8} │ {f'{hard_sem}/{len(hard_tests)}':>6}")

    # Print full SQL for HARD queries
    print(f"\n\n{'=' * 80}")
    print("  HARD QUERY SQL DETAIL")
    print(f"{'=' * 80}")
    for r in results:
        if r["difficulty"] != "HARD":
            continue
        exec_mark = '✅' if r['exec'] else '❌'
        sem_mark = '✅' if r['semantic_pass'] else '❌'
        print(f"\n  Test {r['id']}: {r['question']}")
        print(f"  [exec:{exec_mark} sem:{sem_mark}]")
        print(f"  {r.get('sql', 'N/A')}")
        if r.get("issues"):
            for iss in r["issues"]:
                print(f"    ⚠ {iss}")


if __name__ == "__main__":
    main()
