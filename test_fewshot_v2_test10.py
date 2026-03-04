"""
Test v2 — Test 10: "Find artists whose total revenue is higher than the average revenue of all artists"
Multi-hop join: artist -> album -> track -> invoice_line
"""
import httpx, time

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "mistral"

system_prompt = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): artist, album, track, invoice_line
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
9. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
10. Do not wrap the query in markdown code fences
11. For "total per entity" vs "average of those totals", compute per-entity SUM with GROUP BY, then compare via HAVING to AVG of those SUMs in a subquery
12. Never reference columns from a subquery alias unless that column is explicitly selected by it
13. CRITICAL: track does NOT have artist_id. To link track to artist, you MUST join through album: track.album_id = album.album_id AND album.artist_id = artist.artist_id"""

schema_context = """
=== TABLE: artist ===
Rows: ~275

COLUMNS:
  artist.artist_id : INTEGER [PRIMARY KEY, NOT NULL]
  artist.name : VARCHAR(120)

JOIN PATHS:
  To album: album.artist_id = artist.artist_id
  To track: artist -> album -> track (album.artist_id = artist.artist_id AND track.album_id = album.album_id)

================================================================================
=== TABLE: album ===
Rows: ~347

COLUMNS:
  album.album_id : INTEGER [PRIMARY KEY, NOT NULL]
  album.artist_id : INTEGER [NOT NULL]
  album.title : VARCHAR(160) [NOT NULL]

FOREIGN KEYS:
  album.artist_id -> artist.artist_id

================================================================================
=== TABLE: track ===
Rows: ~3503

COLUMNS:
  track.album_id : INTEGER
  track.track_id : INTEGER [PRIMARY KEY, NOT NULL]
  track.unit_price : NUMERIC(10, 2) [NOT NULL]

FOREIGN KEYS:
  track.album_id -> album.album_id

================================================================================
=== TABLE: invoice_line ===
Rows: ~2240

COLUMNS:
  invoice_line.invoice_line_id : INTEGER [PRIMARY KEY, NOT NULL]
  invoice_line.quantity : INTEGER [NOT NULL]
  invoice_line.track_id : INTEGER [NOT NULL]
  invoice_line.unit_price : NUMERIC(10, 2) [NOT NULL]

FOREIGN KEYS:
  invoice_line.track_id -> track.track_id

GLOBAL FOREIGN KEY RELATIONSHIPS:
  album.artist_id -> artist.artist_id
  track.album_id -> album.album_id
  invoice_line.track_id -> track.track_id
"""

FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find entities whose total revenue exceeds the avg entity revenue (MULTI-HOP JOIN)

IMPORTANT VOCABULARY:
- "total revenue per artist" = SUM(quantity * unit_price) grouped by artist
- "average artist revenue" = AVG of per-artist SUM values -> nested subquery
- CRITICAL: track does NOT have artist_id. Path: artist -> album -> track -> invoice_line
- The inner subquery MUST ALSO join through album to reach artist_id

Schema:
  departments.department_id, departments.name
  categories.category_id, categories.department_id
  products.product_id, products.category_id, products.price
  sales.sale_id, sales.product_id, sales.quantity, sales.unit_price

Question: Find departments whose total revenue is higher than the average department revenue.

NOTE: products does NOT have department_id. Path: departments -> categories -> products -> sales.

SQL:
SELECT
    departments.department_id,
    departments.name,
    SUM(sales.quantity * sales.unit_price) AS total_revenue
FROM departments
JOIN categories ON departments.department_id = categories.department_id
JOIN products ON categories.category_id = products.category_id
JOIN sales ON products.product_id = sales.product_id
GROUP BY departments.department_id, departments.name
HAVING SUM(sales.quantity * sales.unit_price) > (
    SELECT AVG(dept_revenue)
    FROM (
        SELECT SUM(sales.quantity * sales.unit_price) AS dept_revenue
        FROM categories
        JOIN products ON categories.category_id = products.category_id
        JOIN sales ON products.product_id = sales.product_id
        GROUP BY categories.department_id
    ) sub
)
ORDER BY total_revenue DESC;

WHY THIS WORKS:
- Outer query: departments -> categories -> products -> sales (3-hop)
- Inner subquery: categories -> products -> sales, GROUP BY categories.department_id (no need to join departments)
- SUM per department in both outer and inner, AVG wraps those SUMs
- HAVING filters after grouping
- No CTE needed — nested subquery in HAVING
"""

user_question = "Find artists whose total revenue is higher than the average revenue of all artists."

user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- Revenue per artist = SUM(invoice_line.quantity * invoice_line.unit_price) grouped by artist
- JOIN path: artist -> album -> track -> invoice_line
  (album.artist_id = artist.artist_id AND track.album_id = album.album_id AND invoice_line.track_id = track.track_id)
- CRITICAL: track does NOT have artist_id. Inner subquery must also join album -> track -> invoice_line, GROUP BY album.artist_id
- Inner subquery: SELECT SUM(invoice_line.quantity * invoice_line.unit_price) FROM album JOIN track ON track.album_id = album.album_id JOIN invoice_line ON invoice_line.track_id = track.track_id GROUP BY album.artist_id
- HAVING SUM(...) > (SELECT AVG(artist_rev) FROM (...) sub)
- Copy the exact multi-hop HAVING pattern from Example 1 above

SQL:"""

total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5
print("=" * 70)
print("TEST v2 — Test 10: Artist revenue > avg artist revenue")
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
    "Has SUM": "SUM(" in upper,
    "Has HAVING": "HAVING" in upper,
    "Has nested subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "Inner subquery has SUM": upper.count("SUM(") >= 2,
    "AVG wrapping inner": "AVG(" in upper,
    "GROUP BY (2+)": upper.count("GROUP BY") >= 2,
    "Uses artist table": "ARTIST" in upper,
    "Uses album table": "ALBUM" in upper,
    "Uses track table": "TRACK" in upper,
    "Uses invoice_line table": "INVOICE_LINE" in upper,
    "JOIN (3+)": upper.count("JOIN") >= 3,
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
