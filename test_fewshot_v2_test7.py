"""
Test v2 approach for Test 7: "Find tracks whose length is longer than the average track length in their album"

Per-album comparison at the row level:
- "track length" = track.milliseconds
- "average track length in their album" = AVG(milliseconds) WHERE album_id matches
- Correlated subquery: WHERE track.milliseconds > (SELECT AVG(t2.milliseconds) FROM track t2 WHERE t2.album_id = track.album_id)
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
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): track, album
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. If a JOIN PATH or GLOBAL FOREIGN KEY RELATIONSHIPS are provided, use those exact join conditions.
9. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
10. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
11. Do not wrap the query in markdown code fences
12. For "higher/lower than the average in the same group" — use a correlated subquery in WHERE that filters by the same group key"""

schema_context = """
=== TABLE: track ===
Rows: ~3503

COLUMNS:
  track.album_id : INTEGER
  track.bytes : INTEGER
  track.composer : VARCHAR(220)
  track.genre_id : INTEGER
  track.media_type_id : INTEGER [NOT NULL]
  track.milliseconds : INTEGER [NOT NULL]
  track.name : VARCHAR(200) [NOT NULL]
  track.track_id : INTEGER [PRIMARY KEY, NOT NULL]
  track.unit_price : NUMERIC(10, 2) [NOT NULL]

FOREIGN KEYS (actual database constraints):
  track.album_id -> album.album_id
  track.genre_id -> genre.genre_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To album: track.album_id = album.album_id

================================================================================
=== TABLE: album ===
Rows: ~347

COLUMNS:
  album.album_id : INTEGER [PRIMARY KEY, NOT NULL]
  album.artist_id : INTEGER [NOT NULL]
  album.title : VARCHAR(160) [NOT NULL]

FOREIGN KEYS (actual database constraints):
  album.artist_id -> artist.artist_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To track: track.album_id = album.album_id

GLOBAL FOREIGN KEY RELATIONSHIPS:
  album.artist_id -> artist.artist_id
  track.album_id -> album.album_id
  track.genre_id -> genre.genre_id
"""

FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find items whose value is higher than the average value in the SAME GROUP

IMPORTANT VOCABULARY:
- "length longer than average in their album" = compare one row's value to AVG of its group
- "in their album/category/genre" = correlated subquery filtering by the SAME group key
- Pattern: WHERE item.value > (SELECT AVG(t2.value) FROM table t2 WHERE t2.group_id = item.group_id)
- No GROUP BY needed in outer query — each row is compared individually

Schema:
  products.product_id, products.category_id, products.price, products.name
  categories.category_id, categories.name

Question: Find products whose price is higher than the average price in their category.

SQL:
SELECT
    products.product_id,
    products.name,
    products.price,
    categories.name AS category_name
FROM products
JOIN categories ON products.category_id = categories.category_id
WHERE products.price > (
    SELECT AVG(p2.price)
    FROM products p2
    WHERE p2.category_id = products.category_id
)
ORDER BY categories.name, products.price DESC;

WHY THIS WORKS:
- Correlated subquery computes AVG(price) for the SAME category as the outer row
- WHERE p2.category_id = products.category_id links inner to outer by group
- No GROUP BY needed in outer query — each row is compared individually
- No CTE needed — a single correlated subquery in WHERE is clean and sufficient

EXAMPLE 2: Find items above their group average with additional info from joined table

Schema:
  scores.score_id, scores.student_id, scores.subject_id, scores.marks
  subjects.subject_id, subjects.name

Question: Find scores that are above the average score in their subject.

SQL:
SELECT
    scores.score_id,
    scores.marks,
    subjects.name AS subject_name
FROM scores
JOIN subjects ON scores.subject_id = subjects.subject_id
WHERE scores.marks > (
    SELECT AVG(s2.marks)
    FROM scores s2
    WHERE s2.subject_id = scores.subject_id
)
ORDER BY subjects.name, scores.marks DESC;
"""

user_question = "Find tracks whose length is longer than the average track length in their album."

user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "track length" = track.milliseconds
- "average track length in their album" = AVG(milliseconds) WHERE album_id matches -> correlated subquery
- Use the EXACT pattern from Example 1: WHERE track.milliseconds > (SELECT AVG(t2.milliseconds) FROM track t2 WHERE t2.album_id = track.album_id)
- JOIN album to show album title in output
- No GROUP BY needed — each track row is compared individually

SQL:"""

total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5

print("=" * 70)
print("TEST v2 — Test 7: Track length > avg length in same album")
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
    "Uses track.milliseconds": "MILLISECONDS" in upper,
    "Has correlated subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "AVG in subquery": "AVG(" in upper,
    "Correlated by album_id": "ALBUM_ID" in upper and upper.count("ALBUM_ID") >= 3,
    "WHERE for comparison (not HAVING)": "WHERE" in upper,
    "Uses track table": "TRACK" in upper,
    "Uses album table": "ALBUM" in upper,
    "JOIN present": "JOIN" in upper,
    "No GROUP BY in outer": upper.split("WHERE")[0].count("GROUP BY") == 0 if "WHERE" in upper else True,
    "> operator": ">" in raw_output,
    "Self-reference alias (t2 or similar)": any(f" {a}." in raw_output.lower() for a in ["t2", "t1", "tr2", "trk2", "sub"]) or "FROM TRACK T" in upper,
}

all_pass = True
for check, passed in checks.items():
    status = "PASS" if passed else "FAIL"
    if not passed: all_pass = False
    print(f"  [{status}] {check}")

print()
print("=" * 70)
if all_pass:
    print("VERDICT: ALL CHECKS PASSED — Few-shot v2 worked for Test 7!")
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
            for row in (exec_data.get("data") or [])[:5]:
                print(f"    {row}")
            print()
            if 0 < row_count <= 3503:
                print(f"  SANITY: Row count {row_count} is reasonable (3503 total tracks)")
            elif row_count == 0:
                print("  SANITY: WARNING — 0 rows")
        else:
            print(f"  EXECUTION: FAILED — {exec_data.get('error', 'unknown')[:300]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
else:
    print("  Skipped — output doesn't look like SQL")
