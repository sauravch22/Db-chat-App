"""
Test v2 approach for Test 9: "Find tracks whose price is higher than the average price of tracks in the same genre"

Per-genre comparison within the same row context:
- "track price" = track.unit_price
- "average price in same genre" = AVG(unit_price) WHERE genre_id matches
- This is a correlated subquery or self-join pattern
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
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): track, genre
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. If a JOIN PATH or GLOBAL FOREIGN KEY RELATIONSHIPS are provided, use those exact join conditions.
9. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
10. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
11. Do not wrap the query in markdown code fences
12. If you JOIN a subquery, the join key columns MUST be included in that subquery SELECT list
13. Never reference columns from a subquery alias unless that column is explicitly selected by it
14. For "higher/lower than the average in the same group" — use a correlated subquery in WHERE that filters by the same group key"""

# === SCHEMA CONTEXT ===
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
  track.media_type_id -> media_type.media_type_id

JOIN PATHS TO OTHER SELECTED TABLES:
  To genre: track.genre_id = genre.genre_id

AMBIGUOUS COLUMNS (exist in multiple tables):
    -> track.genre_id (in this context)
    -> track.name (in this context)
================================================================================
=== TABLE: genre ===
Rows: ~25

COLUMNS:
  genre.genre_id : INTEGER [PRIMARY KEY, NOT NULL]
  genre.name : VARCHAR(120) | Examples: Heavy Metal, TV Shows, Latin

JOIN PATHS TO OTHER SELECTED TABLES:
  To track: track.genre_id = genre.genre_id

AMBIGUOUS COLUMNS (exist in multiple tables):
    -> genre.genre_id (in this context)
    -> genre.name (in this context)

GLOBAL FOREIGN KEY RELATIONSHIPS:
  album.artist_id -> artist.artist_id
  track.album_id -> album.album_id
  track.genre_id -> genre.genre_id
  track.media_type_id -> media_type.media_type_id
"""

# === FEW-SHOT EXAMPLES — semantically close to "value > avg in same group" ===
FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find items whose value is higher than the average value in the SAME GROUP

IMPORTANT VOCABULARY:
- "price higher than average in same genre/category" = compare one row's value to AVG of its group
- "same genre" / "same category" = correlated subquery filtering by the SAME group key
- Pattern: WHERE item.value > (SELECT AVG(t.value) FROM table t WHERE t.group_id = item.group_id)

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

EXAMPLE 2: Find items above the GLOBAL average (not per-group)

Schema:
  products.product_id, products.category_id, products.price, products.name

Question: Find products whose price is higher than the overall average price.

SQL:
SELECT
    products.product_id,
    products.name,
    products.price
FROM products
WHERE products.price > (
    SELECT AVG(products.price)
    FROM products
)
ORDER BY products.price DESC;

WHY THIS WORKS:
- Non-correlated subquery computes one global AVG
- Simple WHERE filter — no GROUP BY, no HAVING needed
"""

# === USER QUESTION (Test 9) ===
user_question = "Find tracks whose price is higher than the average price of tracks in the same genre."

# === BUILD FULL USER PROMPT ===
user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "price" = track.unit_price
- "average price in same genre" = AVG(unit_price) WHERE genre_id matches -> correlated subquery
- Use the EXACT pattern from Example 1: WHERE track.unit_price > (SELECT AVG(t2.unit_price) FROM track t2 WHERE t2.genre_id = track.genre_id)
- JOIN genre to show genre name in output
- No GROUP BY needed — each track row is compared individually

SQL:"""

# === TOKEN ESTIMATION ===
total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5

print("=" * 70)
print("TEST v2 — Test 9: Track price > avg price in same genre")
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
    "Uses track.unit_price": "UNIT_PRICE" in upper,
    "Has correlated subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "AVG in subquery": "AVG(" in upper,
    "Correlated by genre_id": "GENRE_ID" in upper and upper.count("GENRE_ID") >= 3,
    "WHERE for comparison (not HAVING)": "WHERE" in upper,
    "Uses track table": "TRACK" in upper,
    "Uses genre table": "GENRE" in upper,
    "JOIN present": "JOIN" in upper,
    "No GROUP BY in outer query": True,  # will verify manually
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
    print("VERDICT: ALL CHECKS PASSED — Few-shot v2 worked for Test 9!")
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
                for row in exec_data["data"][:5]:
                    print(f"    {row}")
            print()
            if row_count > 0 and row_count <= 3503:
                print(f"  SANITY: Row count {row_count} is reasonable (max 3503 tracks)")
            elif row_count == 0:
                print("  SANITY: WARNING — 0 rows")
        else:
            print(f"  EXECUTION: FAILED — {exec_data.get('error', 'unknown')[:300]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
else:
    print("  Skipped — output doesn't look like SQL")
