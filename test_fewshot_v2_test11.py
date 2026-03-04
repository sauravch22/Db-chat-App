"""
Test v2 — Test 11: "Find artists who have more tracks than the average number of tracks per artist"
Multi-hop join: artist -> album -> track, COUNT pattern
"""
import httpx, time

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "mistral"

system_prompt = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): artist, album, track
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
9. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
10. Do not wrap the query in markdown code fences
11. For "count per entity" vs "average count", compute per-entity COUNT with GROUP BY, then compare via HAVING to AVG of those COUNTs in a subquery
12. CRITICAL: track does NOT have artist_id. To link track to artist, you MUST join through album: track.album_id = album.album_id AND album.artist_id = artist.artist_id"""

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
  track.name : VARCHAR(200) [NOT NULL]
  track.track_id : INTEGER [PRIMARY KEY, NOT NULL]

FOREIGN KEYS:
  track.album_id -> album.album_id

GLOBAL FOREIGN KEY RELATIONSHIPS:
  album.artist_id -> artist.artist_id
  track.album_id -> album.album_id
"""

FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find entities with more items than the average count per entity (MULTI-HOP JOIN)

IMPORTANT VOCABULARY:
- "more tracks than average per artist" = COUNT(tracks) per artist > AVG of per-artist counts
- TWO levels: first COUNT per entity, then AVG of those counts in subquery
- CRITICAL: track does NOT have artist_id. Must join through album.

Schema:
  departments.department_id, departments.name
  categories.category_id, categories.department_id
  products.product_id, products.category_id

Question: Find departments with more products than the average number of products per department.

NOTE: products does NOT have department_id. Path: departments -> categories -> products.

SQL:
SELECT
    departments.department_id,
    departments.name,
    COUNT(products.product_id) AS track_count
FROM departments
JOIN categories ON departments.department_id = categories.department_id
JOIN products ON categories.category_id = products.category_id
GROUP BY departments.department_id, departments.name
HAVING COUNT(products.product_id) > (
    SELECT AVG(dept_count)
    FROM (
        SELECT COUNT(products.product_id) AS dept_count
        FROM categories
        JOIN products ON categories.category_id = products.category_id
        GROUP BY categories.department_id
    ) sub
)
ORDER BY track_count DESC;

WHY THIS WORKS:
- Outer query: departments -> categories -> products (2-hop)
- Inner subquery: categories -> products, GROUP BY categories.department_id
- COUNT per department in both outer and inner, AVG wraps those COUNTs
- HAVING filters after grouping
"""

user_question = "Find artists who have more tracks than the average number of tracks per artist."

user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- "number of tracks per artist" = COUNT(track.track_id) grouped by artist
- JOIN path: artist -> album -> track (album.artist_id = artist.artist_id AND track.album_id = album.album_id)
- CRITICAL: track does NOT have artist_id. Inner subquery must also join album -> track, GROUP BY album.artist_id
- Inner subquery: SELECT COUNT(track.track_id) FROM album JOIN track ON track.album_id = album.album_id GROUP BY album.artist_id
- HAVING COUNT(track.track_id) > (SELECT AVG(artist_count) FROM (...) sub)
- Copy the exact multi-hop HAVING pattern from Example 1 above

SQL:"""

total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5
print("=" * 70)
print("TEST v2 — Test 11: Artist track count > avg tracks per artist")
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
    "Has COUNT": "COUNT(" in upper,
    "Has HAVING": "HAVING" in upper,
    "Has nested subquery (2+ SELECTs)": upper.count("SELECT") >= 2,
    "Inner subquery has COUNT": upper.count("COUNT(") >= 2,
    "AVG wrapping inner": "AVG(" in upper,
    "GROUP BY (2+)": upper.count("GROUP BY") >= 2,
    "Uses artist table": "ARTIST" in upper,
    "Uses album table": "ALBUM" in upper,
    "Uses track table": "TRACK" in upper,
    "JOIN (2+)": upper.count("JOIN") >= 2,
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
