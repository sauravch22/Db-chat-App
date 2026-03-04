"""
Head-to-head test: DDL schema format vs Human-Readable format
Tests the SAME prompts on Qwen3-Coder-Next (via ngrok endpoint) to see which
schema format produces better SQL.

Usage:
    python3 test_ddl_vs_humanreadable.py
    python3 test_ddl_vs_humanreadable.py https://YOUR_NGROK_URL.ngrok.app

No code changes needed — this calls Ollama directly.
"""
import httpx
import time
import sys
import json
import re

QWEN3_BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "https://517d6b5cb913.ngrok.app"
QWEN3_URL = QWEN3_BASE + "/v1/chat/completions"
MODEL_NAME = "Qwen/Qwen3-Coder-Next"
EXECUTE_URL = "http://localhost:8000/api/chat/execute"
CONNECTION_ID = 3

# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA FORMAT A: Human-Readable (current DbChat format from metadata_service)
# ─────────────────────────────────────────────────────────────────────────────

HUMAN_READABLE_SCHEMA = """
=== TABLE: track ===
Rows: ~3503

COLUMNS:
  track.track_id : INTEGER [PRIMARY KEY, NOT NULL]
  track.name : VARCHAR(200) [NOT NULL]
  track.album_id : INTEGER
  track.media_type_id : INTEGER [NOT NULL]
  track.genre_id : INTEGER
  track.composer : VARCHAR(220)
  track.milliseconds : INTEGER [NOT NULL]
  track.bytes : INTEGER
  track.unit_price : NUMERIC(10, 2) [NOT NULL]

FOREIGN KEYS (actual database constraints):
  track.album_id -> album.album_id
  track.genre_id -> genre.genre_id
  track.media_type_id -> media_type.media_type_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To genre: track.genre_id = genre.genre_id
  To invoice_line: invoice_line.track_id = track.track_id
  To album: track.album_id = album.album_id
  To artist: track.album_id = album.album_id AND album.artist_id = artist.artist_id

================================================================================
=== TABLE: genre ===
Rows: ~25

COLUMNS:
  genre.genre_id : INTEGER [PRIMARY KEY, NOT NULL]
  genre.name : VARCHAR(120)

JOIN PATHS TO OTHER SELECTED TABLES:
  To track: track.genre_id = genre.genre_id

================================================================================
=== TABLE: invoice_line ===
Rows: ~2240

COLUMNS:
  invoice_line.invoice_line_id : INTEGER [PRIMARY KEY, NOT NULL]
  invoice_line.invoice_id : INTEGER [NOT NULL]
  invoice_line.track_id : INTEGER [NOT NULL]
  invoice_line.unit_price : NUMERIC(10, 2) [NOT NULL]
  invoice_line.quantity : INTEGER [NOT NULL]

FOREIGN KEYS (actual database constraints):
  invoice_line.invoice_id -> invoice.invoice_id
  invoice_line.track_id -> track.track_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To track: invoice_line.track_id = track.track_id

================================================================================
=== TABLE: invoice ===
Rows: ~412

COLUMNS:
  invoice.invoice_id : INTEGER [PRIMARY KEY, NOT NULL]
  invoice.customer_id : INTEGER [NOT NULL]
  invoice.invoice_date : TIMESTAMP [NOT NULL]
  invoice.total : NUMERIC(10, 2) [NOT NULL]
  invoice.billing_address : VARCHAR(70)
  invoice.billing_city : VARCHAR(40)
  invoice.billing_country : VARCHAR(40)
  invoice.billing_postal_code : VARCHAR(10)
  invoice.billing_state : VARCHAR(40)

FOREIGN KEYS (actual database constraints):
  invoice.customer_id -> customer.customer_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To invoice_line: invoice_line.invoice_id = invoice.invoice_id

================================================================================
=== TABLE: customer ===
Rows: ~59

COLUMNS:
  customer.customer_id : INTEGER [PRIMARY KEY, NOT NULL]
  customer.first_name : VARCHAR(40) [NOT NULL]
  customer.last_name : VARCHAR(20) [NOT NULL]
  customer.company : VARCHAR(80)
  customer.address : VARCHAR(70)
  customer.city : VARCHAR(40)
  customer.state : VARCHAR(40)
  customer.country : VARCHAR(40)
  customer.postal_code : VARCHAR(10)
  customer.phone : VARCHAR(24)
  customer.fax : VARCHAR(24)
  customer.email : VARCHAR(60) [NOT NULL]
  customer.support_rep_id : INTEGER

FOREIGN KEYS (actual database constraints):
  customer.support_rep_id -> employee.employee_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To invoice: invoice.customer_id = customer.customer_id

================================================================================
=== TABLE: album ===
Rows: ~347

COLUMNS:
  album.album_id : INTEGER [PRIMARY KEY, NOT NULL]
  album.title : VARCHAR(160) [NOT NULL]
  album.artist_id : INTEGER [NOT NULL]

FOREIGN KEYS (actual database constraints):
  album.artist_id -> artist.artist_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To track: track.album_id = album.album_id

================================================================================
=== TABLE: artist ===
Rows: ~275

COLUMNS:
  artist.artist_id : INTEGER [PRIMARY KEY, NOT NULL]
  artist.name : VARCHAR(120)

JOIN PATHS TO OTHER SELECTED TABLES:
  To album: album.artist_id = artist.artist_id

================================================================================
=== TABLE: employee ===
Rows: ~8

COLUMNS:
  employee.employee_id : INTEGER [PRIMARY KEY, NOT NULL]
  employee.last_name : VARCHAR(20) [NOT NULL]
  employee.first_name : VARCHAR(20) [NOT NULL]
  employee.title : VARCHAR(30)
  employee.reports_to : INTEGER
  employee.birth_date : TIMESTAMP
  employee.hire_date : TIMESTAMP
  employee.address : VARCHAR(70)
  employee.city : VARCHAR(40)
  employee.state : VARCHAR(40)
  employee.country : VARCHAR(40)
  employee.postal_code : VARCHAR(10)
  employee.phone : VARCHAR(24)
  employee.fax : VARCHAR(24)
  employee.email : VARCHAR(60)

FOREIGN KEYS (actual database constraints):
  employee.reports_to -> employee.employee_id

GLOBAL FOREIGN KEY RELATIONSHIPS:
  album.artist_id -> artist.artist_id
  customer.support_rep_id -> employee.employee_id
  employee.reports_to -> employee.employee_id
  invoice.customer_id -> customer.customer_id
  invoice_line.invoice_id -> invoice.invoice_id
  invoice_line.track_id -> track.track_id
  track.album_id -> album.album_id
  track.genre_id -> genre.genre_id
  track.media_type_id -> media_type.media_type_id
"""

# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA FORMAT B: DDL (CREATE TABLE statements)
# ─────────────────────────────────────────────────────────────────────────────

DDL_SCHEMA = """
CREATE TABLE artist (
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
);
"""

# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA FORMAT C: DDL Enhanced (inline FK comments + Rules block)
# ─────────────────────────────────────────────────────────────────────────────

DDL_ENHANCED_SCHEMA = """
CREATE TABLE artist (
    artist_id INTEGER PRIMARY KEY NOT NULL,
    name VARCHAR(120)
);

CREATE TABLE album (
    album_id INTEGER PRIMARY KEY NOT NULL,
    title VARCHAR(160) NOT NULL,
    artist_id INTEGER NOT NULL  -- FK → artist.artist_id
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
    album_id INTEGER,            -- FK → album.album_id
    media_type_id INTEGER NOT NULL, -- FK → media_type.media_type_id
    genre_id INTEGER,            -- FK → genre.genre_id
    composer VARCHAR(220),
    milliseconds INTEGER NOT NULL,  -- track duration in ms
    bytes INTEGER,
    unit_price NUMERIC(10, 2) NOT NULL
);

CREATE TABLE employee (
    employee_id INTEGER PRIMARY KEY NOT NULL,
    last_name VARCHAR(20) NOT NULL,
    first_name VARCHAR(20) NOT NULL,
    title VARCHAR(30),
    reports_to INTEGER,          -- FK → employee.employee_id (self-ref)
    birth_date TIMESTAMP,
    hire_date TIMESTAMP,
    address VARCHAR(70),
    city VARCHAR(40),
    state VARCHAR(40),
    country VARCHAR(40),
    postal_code VARCHAR(10),
    phone VARCHAR(24),
    fax VARCHAR(24),
    email VARCHAR(60)
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
    support_rep_id INTEGER       -- FK → employee.employee_id
);

CREATE TABLE invoice (
    invoice_id INTEGER PRIMARY KEY NOT NULL,
    customer_id INTEGER NOT NULL,   -- FK → customer.customer_id
    invoice_date TIMESTAMP NOT NULL,
    total NUMERIC(10, 2) NOT NULL,
    billing_address VARCHAR(70),
    billing_city VARCHAR(40),
    billing_country VARCHAR(40),
    billing_postal_code VARCHAR(10),
    billing_state VARCHAR(40)
);

CREATE TABLE invoice_line (
    invoice_line_id INTEGER PRIMARY KEY NOT NULL,
    invoice_id INTEGER NOT NULL,    -- FK → invoice.invoice_id
    track_id INTEGER NOT NULL,      -- FK → track.track_id
    unit_price NUMERIC(10, 2) NOT NULL,
    quantity INTEGER NOT NULL
);
"""

RULES_BLOCK = """Rules:
- Always use table aliases (e.g., t for track, il for invoice_line)
- Never nest aggregate functions directly (e.g., no AVG(COUNT(...)))
- For "greater than average" patterns: compute per-group aggregates in a subquery, then AVG that in an outer subquery
- Use subqueries instead of CTE/WITH
- Use correct JOIN conditions based on foreign keys shown in schema comments
- Only reference columns that exist in the CREATE TABLE statements
- Always qualify column names with table alias to avoid ambiguity
- Output ONLY the SQL query — no explanation, no markdown fences"""

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPTS (tailored per format)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_HR = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. Use ONLY table/column names from the schema — do not guess or invent names
5. Always use table-qualified column names (table.column)
6. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
7. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
8. Do not wrap the query in markdown code fences"""

SYSTEM_PROMPT_DDL = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. Use ONLY table/column names from the CREATE TABLE statements — do not guess or invent names
5. Always use table-qualified column names (table.column)
6. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
7. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
8. Do not wrap the query in markdown code fences"""

SYSTEM_PROMPT_DDL_ENHANCED = """You are an expert PostgreSQL SQL generator.

Generate ONLY executable PostgreSQL SQL. No explanation, no markdown, no preamble."""



# ─────────────────────────────────────────────────────────────────────────────
# TEST QUERIES (progressively harder)
# ─────────────────────────────────────────────────────────────────────────────

TEST_QUERIES = [
    {
        "id": 1,
        "difficulty": "EASY",
        "question": "List all customers with their full name and email.",
        "tables_needed": ["customer"],
        # Semantic validation: there are exactly 59 customers
        "expected_rows": (59, 59),
        "reference_sql": "SELECT customer.first_name, customer.last_name, customer.email FROM customer",
        "must_have_tables": ["customer"],
        "must_have_columns": ["first_name", "last_name", "email"],
        "must_not_have": [],  # no anti-patterns
    },
    {
        "id": 2,
        "difficulty": "EASY",
        "question": "How many tracks are in each genre? Show genre name and count.",
        "tables_needed": ["track", "genre"],
        "expected_rows": (25, 25),
        "reference_sql": "SELECT genre.name, COUNT(track.track_id) FROM track JOIN genre ON track.genre_id = genre.genre_id GROUP BY genre.name",
        "must_have_tables": ["track", "genre"],
        "must_have_columns": ["name", "count"],
        "must_not_have": [],
    },
    {
        "id": 3,
        "difficulty": "MEDIUM",
        "question": "Show the top 5 customers by total spending.",
        "tables_needed": ["customer", "invoice"],
        "expected_rows": (5, 5),
        "reference_sql": "SELECT customer.customer_id, customer.first_name, customer.last_name, SUM(invoice.total) AS total_spending FROM customer JOIN invoice ON customer.customer_id = invoice.customer_id GROUP BY customer.customer_id, customer.first_name, customer.last_name ORDER BY total_spending DESC LIMIT 5",
        "must_have_tables": ["customer", "invoice"],
        "must_have_columns": ["total"],
        "must_not_have": ["invoice_line"],  # should use invoice.total, not invoice_line
    },
    {
        "id": 4,
        "difficulty": "MEDIUM",
        "question": "Find all albums that have more than 20 tracks.",
        "tables_needed": ["album", "track"],
        "expected_rows": (17, 17),
        "reference_sql": "SELECT album.album_id, album.title FROM album JOIN track ON album.album_id = track.album_id GROUP BY album.album_id, album.title HAVING COUNT(track.track_id) > 20",
        "must_have_tables": ["album", "track"],
        "must_have_columns": ["album_id"],
        "must_not_have": [],
    },
    {
        "id": 5,
        "difficulty": "HARD",
        "question": "Find customers whose total spending is higher than the average customer spending.",
        "tables_needed": ["customer", "invoice"],
        # ~59 customers, roughly half above average → expect 10-40 range
        "expected_rows": (10, 40),
        "reference_sql": "SELECT customer.customer_id, customer.first_name, customer.last_name, SUM(invoice.total) AS total_spending FROM customer JOIN invoice ON customer.customer_id = invoice.customer_id GROUP BY customer.customer_id, customer.first_name, customer.last_name HAVING SUM(invoice.total) > (SELECT AVG(cust_total) FROM (SELECT SUM(invoice.total) AS cust_total FROM invoice GROUP BY invoice.customer_id) sub)",
        "must_have_tables": ["customer", "invoice"],
        "must_have_columns": ["customer_id"],
        "must_not_have": [],
    },
    {
        "id": 6,
        "difficulty": "HARD",
        "question": "Find tracks whose sales count is higher than the average sales count of tracks in the same genre.",
        "tables_needed": ["track", "genre", "invoice_line"],
        # Not all 3503 tracks — should be a filtered subset
        "expected_rows": (50, 1000),
        "reference_sql": "SELECT track.track_id, track.name FROM track JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY track.track_id, track.name, track.genre_id HAVING COUNT(invoice_line.invoice_line_id) > (SELECT AVG(tc) FROM (SELECT track.genre_id AS gid, COUNT(invoice_line.invoice_line_id) AS tc FROM track JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY track.track_id, track.genre_id) sub WHERE sub.gid = track.genre_id)",
        "must_have_tables": ["track", "invoice_line"],
        "must_have_columns": ["track_id"],
        "must_not_have": ["milliseconds"],  # should compare SALES count, not duration!
    },
    {
        "id": 7,
        "difficulty": "HARD",
        "question": "Find artists whose total revenue is greater than the average artist revenue.",
        "tables_needed": ["artist", "album", "track", "invoice_line"],
        # ~275 artists, roughly half above average → expect 20-150
        "expected_rows": (20, 150),
        "reference_sql": "SELECT artist.artist_id, artist.name, SUM(invoice_line.unit_price * invoice_line.quantity) AS total_revenue FROM artist JOIN album ON artist.artist_id = album.artist_id JOIN track ON album.album_id = track.album_id JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY artist.artist_id, artist.name HAVING SUM(invoice_line.unit_price * invoice_line.quantity) > (SELECT AVG(ar) FROM (SELECT SUM(invoice_line.unit_price * invoice_line.quantity) AS ar FROM artist JOIN album ON artist.artist_id = album.artist_id JOIN track ON album.album_id = track.album_id JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY artist.artist_id) sub)",
        "must_have_tables": ["artist", "album", "track", "invoice_line"],
        "must_have_columns": ["artist_id", "name"],
        "must_not_have": [],
    },
    {
        "id": 8,
        "difficulty": "HARD",
        "question": "Find albums whose total duration is greater than the average album duration.",
        "tables_needed": ["album", "track"],
        # ~347 albums, about half above average → expect 30-200
        "expected_rows": (30, 200),
        "reference_sql": "SELECT album.album_id, album.title, SUM(track.milliseconds) AS total_duration FROM album JOIN track ON album.album_id = track.album_id GROUP BY album.album_id, album.title HAVING SUM(track.milliseconds) > (SELECT AVG(album_dur) FROM (SELECT SUM(track.milliseconds) AS album_dur FROM track GROUP BY track.album_id) sub)",
        "must_have_tables": ["album", "track"],
        "must_have_columns": ["album_id", "milliseconds"],
        "must_not_have": ["duration"],  # column is 'milliseconds', NOT 'duration'
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def call_qwen3(system: str, prompt: str) -> dict:
    """Call Qwen3-Coder-Next via OpenAI-compatible chat completions API."""
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
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
    # Find first SELECT or WITH
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


def build_hr_prompt(question: str) -> str:
    """Build prompt using human-readable schema."""
    return f"""Schema:
{HUMAN_READABLE_SCHEMA}

User Question: {question}

SQL query:"""


def build_ddl_prompt(question: str) -> str:
    """Build prompt using DDL schema."""
    return f"""### Database Schema
{DDL_SCHEMA}

### Task
{question}

### SQL
"""


def build_ddl_enhanced_prompt(question: str) -> str:
    """Build prompt using enhanced DDL with FK comments + Rules block."""
    return f"""You are an expert PostgreSQL SQL generator.

Generate ONLY executable PostgreSQL SQL.

{RULES_BLOCK}

Schema:
{DDL_ENHANCED_SCHEMA}

Question:
{question}

SQL:
"""


def check_semantic_correctness(sql: str, test: dict, row_count: int) -> dict:
    """Deep semantic validation: does the SQL actually answer the question?"""
    upper = sql.upper()
    issues = []
    scores = {}  # category → True/False

    # 1. ROW COUNT IN EXPECTED RANGE
    exp_min, exp_max = test.get("expected_rows", (0, 999999))
    rows_ok = exp_min <= row_count <= exp_max
    scores["rows_in_range"] = rows_ok
    if not rows_ok:
        issues.append(f"Row count {row_count} outside expected [{exp_min}–{exp_max}]")

    # 2. REQUIRED TABLES PRESENT
    must_tables = test.get("must_have_tables", [])
    for tbl in must_tables:
        if tbl.upper() not in upper:
            scores[f"has_table_{tbl}"] = False
            issues.append(f"Missing required table: {tbl}")
        else:
            scores[f"has_table_{tbl}"] = True

    # 3. REQUIRED COLUMNS PRESENT (check column name appears anywhere in SQL)
    must_cols = test.get("must_have_columns", [])
    for col in must_cols:
        if col.upper() not in upper:
            scores[f"has_col_{col}"] = False
            issues.append(f"Missing required column: {col}")
        else:
            scores[f"has_col_{col}"] = True

    # 4. ANTI-PATTERN COLUMNS ABSENT (model hallucinated or used wrong column)
    must_not = test.get("must_not_have", [])
    for bad in must_not:
        bad_upper = bad.upper()
        # Match as a standalone word (column reference), not inside aliases
        pattern = r'(?<![A-Z_])' + re.escape(bad_upper) + r'(?![A-Z_])'
        if re.search(pattern, upper):
            scores[f"no_{bad}"] = False
            issues.append(f"Contains anti-pattern: '{bad}' (model misunderstood schema)")
        else:
            scores[f"no_{bad}"] = True

    # 5. JOIN CORRECTNESS (check common wrong joins)
    join_issues = []
    if "ARTIST_ID = TRACK_ID" in upper or "TRACK_ID = ARTIST_ID" in upper:
        join_issues.append("Wrong join: artist_id = track_id")
    if "INVOICE_LINE.CUSTOMER_ID" in upper:
        join_issues.append("Wrong column: invoice_line.customer_id doesn't exist")
    if "TRACK.DURATION" in upper or "B.DURATION" in upper or "T.DURATION" in upper:
        join_issues.append("Hallucinated column: 'duration' — should be 'milliseconds'")
    if "I.QUANTITY" in upper and "INVOICE_LINE" not in upper.replace(" ", ""):
        join_issues.append("Wrong alias: i.quantity — 'i' is invoice, not invoice_line")

    scores["no_join_errors"] = len(join_issues) == 0
    issues.extend(join_issues)

    # 6. CROSS-VALIDATE WITH REFERENCE SQL (execute reference and compare row counts)
    ref_sql = test.get("reference_sql", "")
    ref_row_count = None
    ref_matches = None
    if ref_sql and row_count > 0:
        ref_result = execute_sql(ref_sql)
        if ref_result.get("success"):
            ref_row_count = ref_result.get("row_count", 0)
            # Allow 10% tolerance for borderline grouping differences
            tolerance = max(2, int(ref_row_count * 0.1))
            ref_matches = abs(row_count - ref_row_count) <= tolerance
            scores["matches_reference"] = ref_matches
            if not ref_matches:
                issues.append(f"Row mismatch vs reference: got {row_count}, expected ~{ref_row_count}")
        else:
            ref_matches = None  # ref query itself failed, skip

    # OVERALL SEMANTIC SCORE
    total_checks = len(scores)
    passed = sum(1 for v in scores.values() if v)
    semantic_pass = len(issues) == 0

    return {
        "semantic_pass": semantic_pass,
        "semantic_score": f"{passed}/{total_checks}",
        "issues": issues,
        "scores": scores,
        "ref_row_count": ref_row_count,
        "ref_matches": ref_matches,
    }


def analyze_sql(raw_output: str, question: str, test: dict = None) -> dict:
    """Analyze SQL quality — syntax, execution, AND semantic correctness."""
    sql = clean_sql(raw_output)
    upper = sql.upper()
    checks = {
        "starts_with_select": upper.startswith("SELECT"),
        "no_cte": not upper.startswith("WITH"),
        "has_from": "FROM" in upper,
        "no_markdown": "```" not in raw_output,
        "no_preamble": not any(raw_output.upper().startswith(p) for p in ["HERE", "THE SQL", "SURE", "I "]),
    }
    # Execute
    exec_result = None
    exec_success = False
    row_count = 0
    exec_error = ""
    if checks["starts_with_select"] or upper.startswith("WITH"):
        exec_result = execute_sql(sql)
        exec_success = exec_result.get("success", False)
        row_count = exec_result.get("row_count", 0) if exec_success else 0
        exec_error = exec_result.get("error", "")[:200] if not exec_success else ""

    # Semantic correctness (only if execution succeeded and test metadata provided)
    semantic = None
    if exec_success and test:
        semantic = check_semantic_correctness(sql, test, row_count)

    return {
        "sql": sql,
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "exec_success": exec_success,
        "row_count": row_count,
        "exec_error": exec_error,
        "semantic": semantic,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TEST RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def print_format_result(label: str, result: dict, analysis: dict):
    """Print results for one format."""
    sem = analysis.get("semantic")
    print(f"    Tokens: {result['prompt_tokens']}→{result['output_tokens']} | Time: {result['elapsed']:.1f}s")
    print(f"    SQL: {analysis['sql'][:130]}")
    print(f"    Exec: {'✅ SUCCESS' if analysis['exec_success'] else '❌ FAILED'} | Rows: {analysis['row_count']}", end="")
    if analysis['exec_error']:
        print(f" | Error: {analysis['exec_error'][:100]}")
    else:
        print()
    if sem:
        sem_icon = "✅" if sem["semantic_pass"] else "⚠️"
        print(f"    Semantic: {sem_icon} {sem['semantic_score']}", end="")
        if sem["ref_row_count"] is not None:
            ref_icon = "✅" if sem["ref_matches"] else "❌"
            print(f" | Ref match: {ref_icon} (ref={sem['ref_row_count']})")
        else:
            print()
        if sem["issues"]:
            for iss in sem["issues"]:
                print(f"    ⚠ {iss}")


def is_semantically_correct(analysis: dict) -> bool:
    """Check if a result is both executable and semantically correct."""
    sem = analysis.get("semantic")
    if sem:
        return analysis["exec_success"] and sem["semantic_pass"]
    return analysis["exec_success"]


def run_tests():
    print(f"\n{'#' * 80}")
    print(f"# MODEL: {MODEL_NAME}")
    print(f"# Endpoint: {QWEN3_URL}")
    print(f"# Testing {len(TEST_QUERIES)} queries × 3 formats")
    print(f"#   A: Human-Readable (current DbChat)")
    print(f"#   B: DDL plain (CREATE TABLE + FOREIGN KEY)")
    print(f"#   C: DDL Enhanced (inline FK comments + Rules block)")
    print(f"{'#' * 80}")

    results = []

    for test in TEST_QUERIES:
        qid = test["id"]
        question = test["question"]
        difficulty = test["difficulty"]

        print(f"\n{'=' * 78}")
        print(f"  TEST {qid} [{difficulty}]: {question}")
        print(f"{'=' * 78}")

        # ── FORMAT A: Human-Readable ──
        print(f"\n  ▸ Format A: HUMAN-READABLE")
        hr_result = call_qwen3(SYSTEM_PROMPT_HR, build_hr_prompt(question))
        hr_analysis = analyze_sql(hr_result["response"], question, test)
        print_format_result("HR", hr_result, hr_analysis)

        # ── FORMAT B: DDL plain ──
        print(f"\n  ▸ Format B: DDL (plain)")
        ddl_result = call_qwen3(SYSTEM_PROMPT_DDL, build_ddl_prompt(question))
        ddl_analysis = analyze_sql(ddl_result["response"], question, test)
        print_format_result("DDL", ddl_result, ddl_analysis)

        # ── FORMAT C: DDL Enhanced (FK comments + Rules) ──
        print(f"\n  ▸ Format C: DDL Enhanced (FK comments + Rules)")
        enh_result = call_qwen3(SYSTEM_PROMPT_DDL_ENHANCED, build_ddl_enhanced_prompt(question))
        enh_analysis = analyze_sql(enh_result["response"], question, test)
        print_format_result("ENH", enh_result, enh_analysis)

        # ── Determine winner across 3 formats ──
        hr_ok  = is_semantically_correct(hr_analysis)
        ddl_ok = is_semantically_correct(ddl_analysis)
        enh_ok = is_semantically_correct(enh_analysis)

        correct_formats = []
        if hr_ok:  correct_formats.append("HR")
        if ddl_ok: correct_formats.append("DDL")
        if enh_ok: correct_formats.append("ENH")

        if len(correct_formats) == 3:
            winner = "TIE (all 3 correct)"
        elif len(correct_formats) == 2:
            winner = f"TIE ({'+'.join(correct_formats)} correct)"
        elif len(correct_formats) == 1:
            winner = correct_formats[0]
        else:
            # None correct — note which at least executed
            exec_formats = []
            if hr_analysis["exec_success"]:  exec_formats.append("HR")
            if ddl_analysis["exec_success"]: exec_formats.append("DDL")
            if enh_analysis["exec_success"]: exec_formats.append("ENH")
            if exec_formats:
                winner = f"TIE-FAIL ({'+'.join(exec_formats)} exec but wrong)"
            else:
                winner = "TIE (all 3 failed)"

        print(f"\n  → Winner: {winner}")

        hr_sem  = hr_analysis.get("semantic")
        ddl_sem = ddl_analysis.get("semantic")
        enh_sem = enh_analysis.get("semantic")

        results.append({
            "id": qid,
            "difficulty": difficulty,
            "question": question,
            # Format A
            "hr_success": hr_analysis["exec_success"],
            "hr_rows": hr_analysis["row_count"],
            "hr_sql": hr_analysis["sql"],
            "hr_error": hr_analysis["exec_error"],
            "hr_tokens": hr_result["prompt_tokens"],
            "hr_semantic": hr_sem,
            "hr_correct": hr_ok,
            # Format B
            "ddl_success": ddl_analysis["exec_success"],
            "ddl_rows": ddl_analysis["row_count"],
            "ddl_sql": ddl_analysis["sql"],
            "ddl_error": ddl_analysis["exec_error"],
            "ddl_tokens": ddl_result["prompt_tokens"],
            "ddl_semantic": ddl_sem,
            "ddl_correct": ddl_ok,
            # Format C
            "enh_success": enh_analysis["exec_success"],
            "enh_rows": enh_analysis["row_count"],
            "enh_sql": enh_analysis["sql"],
            "enh_error": enh_analysis["exec_error"],
            "enh_tokens": enh_result["prompt_tokens"],
            "enh_semantic": enh_sem,
            "enh_correct": enh_ok,
            "winner": winner,
        })

    # ── SUMMARY ──
    print(f"\n\n{'#' * 80}")
    print(f"  SUMMARY — {MODEL_NAME}")
    print(f"{'#' * 80}")

    # 3-format table
    hdr = f"  {'#':>2} {'Diff':>6} │ {'HR':^10} │ {'DDL':^10} │ {'ENH':^10} │ Winner"
    sep = f"  {'─'*2}─{'─'*6}─┼─{'─'*10}─┼─{'─'*10}─┼─{'─'*10}─┼─{'─'*30}"
    print(f"\n{hdr}")
    print(sep)

    hr_total_tokens = 0
    ddl_total_tokens = 0
    enh_total_tokens = 0

    for r in results:
        def fmt(success, sem, rows):
            if not success:
                return "  ❌     "
            s = sem
            if s and s["semantic_pass"]:
                return f"✅✅{rows:>4}r"
            elif s:
                return f"✅⚠️{rows:>4}r"
            else:
                return f"✅  {rows:>4}r"

        hr_cell  = fmt(r["hr_success"],  r.get("hr_semantic"),  r["hr_rows"])
        ddl_cell = fmt(r["ddl_success"], r.get("ddl_semantic"), r["ddl_rows"])
        enh_cell = fmt(r["enh_success"], r.get("enh_semantic"), r["enh_rows"])

        print(f"  {r['id']:>2} {r['difficulty']:>6} │ {hr_cell} │ {ddl_cell} │ {enh_cell} │ {r['winner']}")

        if isinstance(r["hr_tokens"], int):  hr_total_tokens  += r["hr_tokens"]
        if isinstance(r["ddl_tokens"], int): ddl_total_tokens += r["ddl_tokens"]
        if isinstance(r["enh_tokens"], int): enh_total_tokens += r["enh_tokens"]

    n = len(results)
    print(f"\n  ═══════════════════════════════════════════════════════════")
    print(f"  Legend: ✅✅ = exec+semantic pass | ✅⚠️ = exec ok, semantic fail | ❌ = exec fail")

    print(f"\n  EXECUTION (SQL runs without error):")
    hr_ep  = sum(1 for r in results if r["hr_success"])
    ddl_ep = sum(1 for r in results if r["ddl_success"])
    enh_ep = sum(1 for r in results if r["enh_success"])
    print(f"    HR:  {hr_ep}/{n} ({hr_ep*100//n}%)")
    print(f"    DDL: {ddl_ep}/{n} ({ddl_ep*100//n}%)")
    print(f"    ENH: {enh_ep}/{n} ({enh_ep*100//n}%)")

    print(f"\n  SEMANTIC (truly correct — right tables, columns, row range, ref match):")
    hr_sp  = sum(1 for r in results if r.get("hr_correct"))
    ddl_sp = sum(1 for r in results if r.get("ddl_correct"))
    enh_sp = sum(1 for r in results if r.get("enh_correct"))
    print(f"    HR:  {hr_sp}/{n} ({hr_sp*100//n}%)")
    print(f"    DDL: {ddl_sp}/{n} ({ddl_sp*100//n}%)")
    print(f"    ENH: {enh_sp}/{n} ({enh_sp*100//n}%)")

    print(f"\n  WINNER TALLY:")
    hr_wins  = sum(1 for r in results if r["winner"] == "HR")
    ddl_wins = sum(1 for r in results if r["winner"] == "DDL")
    enh_wins = sum(1 for r in results if r["winner"] == "ENH")
    tie_count = n - hr_wins - ddl_wins - enh_wins
    print(f"    HR only correct:   {hr_wins}")
    print(f"    DDL only correct:  {ddl_wins}")
    print(f"    ENH only correct:  {enh_wins}")
    print(f"    Ties / mixed:      {tie_count}")

    print(f"\n  TOKEN EFFICIENCY:")
    print(f"    HR  avg prompt tokens: {hr_total_tokens  // n if hr_total_tokens  else '?'}")
    print(f"    DDL avg prompt tokens: {ddl_total_tokens // n if ddl_total_tokens else '?'}")
    print(f"    ENH avg prompt tokens: {enh_total_tokens // n if enh_total_tokens else '?'}")
    if hr_total_tokens and ddl_total_tokens:
        print(f"    DDL saves vs HR: {hr_total_tokens - ddl_total_tokens} tokens ({(hr_total_tokens - ddl_total_tokens)*100//hr_total_tokens}%)")
    if hr_total_tokens and enh_total_tokens:
        print(f"    ENH saves vs HR: {hr_total_tokens - enh_total_tokens} tokens ({(hr_total_tokens - enh_total_tokens)*100//hr_total_tokens}%)" if enh_total_tokens < hr_total_tokens else f"    ENH costs vs HR: +{enh_total_tokens - hr_total_tokens} tokens")
    print(f"  ═══════════════════════════════════════════════════════════")

    # Print full SQL for HARD queries
    print(f"\n\n{'=' * 80}")
    print("  DETAILED SQL + UNDERSTANDING ANALYSIS FOR HARD QUERIES")
    print(f"{'=' * 80}")
    for r in results:
        if r["difficulty"] != "HARD":
            continue
        print(f"\n  Test {r['id']}: {r['question']}")

        for label, prefix in [("HR", "hr"), ("DDL", "ddl"), ("ENH", "enh")]:
            s = r.get(f"{prefix}_semantic")
            exec_mark = '✅' if r[f'{prefix}_success'] else '❌'
            sem_mark = '✅' if (s and s['semantic_pass']) else ('⚠️' if s else '—')
            print(f"  ─── {label} SQL [exec:{exec_mark} sem:{sem_mark}] ───")
            print(f"  {r[f'{prefix}_sql']}")
            if r[f"{prefix}_error"]:
                print(f"  ERROR: {r[f'{prefix}_error']}")
            if s and s["issues"]:
                print(f"  UNDERSTANDING ISSUES:")
                for iss in s["issues"]:
                    print(f"    ⚠ {iss}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"{'=' * 80}")
    print(f"  DDL vs Human-Readable — 3-Format Schema Comparison")
    print(f"  Model:    {MODEL_NAME}")
    print(f"  Endpoint: {QWEN3_URL}")
    print(f"{'=' * 80}")

    # Verify LLM endpoint
    try:
        test_payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": "SELECT 1"}],
            "max_tokens": 5,
        }
        resp = httpx.post(QWEN3_URL, json=test_payload, timeout=30.0)
        if resp.status_code == 200:
            print(f"✅ LLM endpoint reachable (status {resp.status_code})")
        else:
            print(f"⚠️  LLM endpoint returned status {resp.status_code}")
            print(f"   Check your ngrok tunnel is running")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Cannot reach LLM endpoint at {QWEN3_URL}: {e}")
        sys.exit(1)

    # Verify execute endpoint
    try:
        test_exec = execute_sql("SELECT 1")
        if test_exec.get("success"):
            print(f"✅ Execute endpoint working (connection_id={CONNECTION_ID})")
        else:
            print(f"⚠️  Execute endpoint returned error: {test_exec.get('error', '?')[:100]}")
            print(f"   Make sure uvicorn is running on port 8000")
    except Exception as e:
        print(f"❌ Cannot reach execute endpoint: {e}")
        print(f"   Start server: cd DbChat && uvicorn serve:app --port 8000")
        sys.exit(1)

    run_tests()
