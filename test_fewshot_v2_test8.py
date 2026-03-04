"""
Test v2 — Test 8: "Find albums whose total duration is greater than the average album duration"
Album-level aggregate vs global average pattern.
"""
import httpx, time

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "mistral"

system_prompt = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): album, track
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
9. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
10. Do not wrap the query in markdown code fences
11. For "total per entity" vs "average of those totals", compute per-entity SUM with GROUP BY, then compare via HAVING to AVG of those SUMs in a subquery
12. Never reference columns from a subquery alias unless that column is explicitly selected by it"""

schema_context = """
=== TABLE: album ===
Rows: ~347

COLUMNS:
  album.album_id : INTEGER [PRIMARY KEY, NOT NULL]
  album.artist_id : INTEGER [NOT NULL]
  album.title : VARCHAR(160) [NOT NULL]

FOREIGN KEYS:
  album.artist_id -> artist.artist_id

JOIN PATHS:
  To track: track.album_id = album.album_id

================================================================================
=== TABLE: track ===
Rows: ~3503

COLUMNS:
  track.album_id : INTEGER
  track.milliseconds : INTEGER [NOT NULL]
  track.name : VARCHAR(200) [NOT NULL]
  track.track_id : INTEGER [PRIMARY KEY, NOT NULL]
  track.unit_price : NUMERIC(10, 2) [NOT NULL]

FOREIGN KEYS:
  track.album_id -> album.album_id

JOIN PATHS:
  To album: track.album_id = album.album_id

GLOBAL FOREIGN KEY RELATIONSHIPS:
  track.album_id -> album.album_id
  album.artist_id -> artist.artist_id
"""

FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find entities whose total exceeds the average entity total

IMPORTANT VOCABULARY:
- "total duration per album" = SUM(track.milliseconds) grouped by album
- "average album duration" = AVG of per-album SUM values -> AVG() on pre-grouped SUMs
- TWO levels: first SUM per entity, then AVG of those sums in subquery

Schema:
  categories.category_id, categories.name
  products.product_id, products.category_id, products.weight

Question: Find categories whose total product weight is greater than the average category weight.

SQL:
SELECT
    categories.category_id,
    categories.name,
    SUM(products.weight) AS total_weight
FROM categories
JOIN products ON categories.category_id = products.category_id
GROUP BY categories.category_id, categories.name
HAVING SUM(products.weight) > (
    SELECT AVG(cat_weight)
    FROM (
        SELECT SUM(products.weight) AS cat_weight
        FROM products
        GROUP BY products.category_id
    ) sub
)
ORDER BY total_weight DESC;

WHY THIS WORKS:
- Outer query directly JOINs categories to products (NOT via subquery)
- SUM(products.weight) per category in outer GROUP BY — products is in FROM/JOIN so it is accessible
- Inner subquery computes SUM per category independently
- AVG wraps those sums — computes ONCE, not per row
- HAVING filters after grouping — references products.weight which IS in the FROM clause
- CRITICAL: Do NOT join a subquery and then reference the original table — only reference tables/aliases in your FROM/JOIN
- No CTE needed — nested subquery in HAVING is clean
"""

user_question = "Find albums whose total duration is greater than the average album duration."

user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "total duration" per album = SUM(track.milliseconds) grouped by album
- "average album duration" = AVG of per-album SUM(milliseconds) in nested subquery
- Outer query: FROM album JOIN track ON album.album_id = track.album_id (direct JOIN, NOT a subquery join)
- HAVING SUM(track.milliseconds) > (SELECT AVG(album_dur) FROM (SELECT SUM(track.milliseconds) AS album_dur FROM track GROUP BY track.album_id) sub)
- CRITICAL: track must appear in FROM/JOIN so HAVING can reference track.milliseconds
- Copy the exact HAVING pattern from Example 1 above — direct JOIN, not subquery JOIN

SQL:"""

total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5
print("=" * 70)
print("TEST v2 — Test 8: Album duration > avg album duration")
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
    "Has SUM(track.milliseconds)": "SUM(" in upper and "MILLISECONDS" in upper,
    "Has HAVING": "HAVING" in upper,
    "Has nested subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "Inner subquery has SUM": upper.count("SUM(") >= 2,
    "AVG wrapping inner": "AVG(" in upper,
    "GROUP BY (2+)": upper.count("GROUP BY") >= 2,
    "Uses album table": "ALBUM" in upper,
    "Uses track table": "TRACK" in upper,
    "JOIN present": "JOIN" in upper,
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
