"""
Test v2 approach for Test 12: "Find artists whose longest track is longer than the average longest track across artists"

Two-level aggregate comparison:
- "longest track per artist" = MAX(track.milliseconds) GROUP BY artist
- "average longest track across artists" = AVG of those MAX values
- Pattern: GROUP BY artist, HAVING MAX(ms) > (SELECT AVG(max_ms) FROM (SELECT MAX(ms) GROUP BY artist) sub)
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
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): track, album, artist
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. If a JOIN PATH or GLOBAL FOREIGN KEY RELATIONSHIPS are provided, use those exact join conditions.
9. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
10. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
11. Do not wrap the query in markdown code fences
12. If you JOIN a subquery, the join key columns MUST be included in that subquery SELECT list
13. Never reference columns from a subquery alias unless that column is explicitly selected by it
14. For comparisons like "per-entity MAX/MIN" vs "average of those MAX/MIN values", compute per-entity aggregates with GROUP BY + HAVING, and compare to AVG of those aggregates in a nested subquery"""

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

JOIN PATHS TO OTHER SELECTED TABLES:
  To artist: track -> album -> artist (track.album_id = album.album_id AND album.artist_id = artist.artist_id)
  To album: track.album_id = album.album_id

================================================================================
=== TABLE: artist ===
Rows: ~275

COLUMNS:
  artist.artist_id : INTEGER [PRIMARY KEY, NOT NULL]
  artist.name : VARCHAR(120) | Examples: Legião Urbana, Ben Harper, Incognito

JOIN PATHS TO OTHER SELECTED TABLES:
  To track: artist -> album -> track (album.artist_id = artist.artist_id AND track.album_id = album.album_id)
  To album: album.artist_id = artist.artist_id

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
  To artist: album.artist_id = artist.artist_id

GLOBAL FOREIGN KEY RELATIONSHIPS:
  album.artist_id -> artist.artist_id
  track.album_id -> album.album_id
  track.genre_id -> genre.genre_id
"""

# === FEW-SHOT EXAMPLES — semantically close to "per-entity MAX vs avg of MAX values" ===
FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find entities whose per-entity MAX exceeds the average of all per-entity MAX values (MULTI-HOP JOIN)

IMPORTANT VOCABULARY:
- "longest track" = MAX(milliseconds) per artist -> use MAX()
- "average longest track" = AVG of per-artist MAX values -> AVG() over pre-grouped MAXes
- These require TWO levels: first MAX per entity, then AVG of those MAX values in a subquery
- CRITICAL: track does NOT have artist_id. To group tracks by artist, you MUST JOIN through album:
  track.album_id = album.album_id AND album.artist_id = artist.artist_id
- The inner subquery MUST ALSO join through album to reach artist_id

Schema:
  products.product_id, products.category_id, products.weight
  categories.category_id, categories.department_id
  departments.department_id, departments.name

Question: Find departments whose heaviest product is heavier than the average heaviest product across departments.

NOTE: products does NOT have department_id. Path: products -> categories -> departments.

SQL:
SELECT
    departments.department_id,
    departments.name,
    MAX(products.weight) AS heaviest_product
FROM departments
JOIN categories ON departments.department_id = categories.department_id
JOIN products ON categories.category_id = products.category_id
GROUP BY departments.department_id, departments.name
HAVING MAX(products.weight) > (
    SELECT AVG(max_weight)
    FROM (
        SELECT MAX(products.weight) AS max_weight
        FROM products
        JOIN categories ON products.category_id = categories.category_id
        GROUP BY categories.department_id
    ) sub
)
ORDER BY heaviest_product DESC;

WHY THIS WORKS:
- Outer query joins departments -> categories -> products (2-hop)
- Inner subquery ALSO joins products -> categories to reach department_id for grouping
- Inner subquery does NOT reference departments directly — it only needs categories.department_id
- MAX per department in both outer and inner, AVG wraps those MAXes
- HAVING filters after grouping — correct for aggregate comparisons
- No CTE needed — nested subquery in HAVING is clean

EXAMPLE 2: Find entities whose total exceeds the global average total

Schema:
  orders.order_id, orders.customer_id, orders.amount
  customers.customer_id, customers.name

Question: Find customers whose total spending is higher than the average customer spending.

SQL:
SELECT
    customers.customer_id,
    customers.name,
    SUM(orders.amount) AS total_spending
FROM customers
JOIN orders ON customers.customer_id = orders.customer_id
GROUP BY customers.customer_id, customers.name
HAVING SUM(orders.amount) > (
    SELECT AVG(customer_total)
    FROM (
        SELECT SUM(orders.amount) AS customer_total
        FROM orders
        GROUP BY orders.customer_id
    ) sub
)
ORDER BY total_spending DESC;
"""

# === USER QUESTION (Test 12) ===
user_question = "Find artists whose longest track is longer than the average longest track across artists."

# === BUILD FULL USER PROMPT ===
user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "longest track" per artist = MAX(track.milliseconds) -> use MAX(), not raw column
- "average longest track across artists" = AVG of per-artist MAX values -> nested subquery
- JOIN path: artist -> album -> track (album.artist_id = artist.artist_id AND track.album_id = album.album_id)
- CRITICAL: track does NOT have artist_id. The inner subquery MUST also join album to reach artist_id:
  FROM track JOIN album ON track.album_id = album.album_id GROUP BY album.artist_id
- GROUP BY artist, HAVING MAX(track.milliseconds) > (SELECT AVG(max_ms) FROM (SELECT MAX(track.milliseconds) FROM track JOIN album ON track.album_id = album.album_id GROUP BY album.artist_id) sub)
- Copy the exact multi-hop HAVING pattern from Example 1 above

SQL:"""

# === TOKEN ESTIMATION ===
total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5

print("=" * 70)
print("TEST v2 — Test 12: Longest track > avg longest track (per-artist)")
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
    "Uses MAX(track.milliseconds)": "MAX(" in upper and "MILLISECONDS" in upper,
    "Has HAVING clause": "HAVING" in upper,
    "HAVING uses MAX()": "HAVING" in upper and "MAX(" in upper,
    "Has nested subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "Inner subquery has MAX": upper.count("MAX(") >= 2,
    "Inner subquery has GROUP BY": upper.count("GROUP BY") >= 2,
    "AVG() wrapping inner MAX": "AVG(" in upper,
    "Uses artist table": "ARTIST" in upper,
    "Uses album table": "ALBUM" in upper,
    "Uses track table": "TRACK" in upper,
    "JOIN present (2 JOINs needed)": upper.count("JOIN") >= 2,
    "ORDER BY present": "ORDER BY" in upper,
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
    print("VERDICT: ALL CHECKS PASSED — Few-shot v2 worked for Test 12!")
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
            if row_count > 0 and row_count <= 275:
                print(f"  SANITY: Row count {row_count} is reasonable (max 275 artists)")
            elif row_count == 0:
                print("  SANITY: WARNING — 0 rows")
            else:
                print(f"  SANITY: WARNING — {row_count} rows exceeds artist count (275)")
        else:
            print(f"  EXECUTION: FAILED — {exec_data.get('error', 'unknown')[:300]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
else:
    print("  Skipped — output doesn't look like SQL")
