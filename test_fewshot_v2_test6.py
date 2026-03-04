"""
Test v2 — Test 6: "Find genres whose total revenue is higher than the average genre revenue"
Genre-level aggregate vs global average pattern.
"""
import httpx, time

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL = "mistral"

system_prompt = """You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.

STRICT RULES:
1. Output ONLY the SQL query — no explanation, no preamble, no commentary
2. Do NOT write "Here is", "The SQL is", or any sentence before or after the query
3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP
4. EXACT TABLE NAMES YOU MUST USE (copy these letter-for-letter): genre, track, invoice_line
5. Use ONLY column names listed in the schema below — do not guess or invent names
6. Always use table-qualified column names shown in the schema (table.column). Never use unqualified columns.
7. If you reference a table in SELECT/WHERE/GROUP BY/ORDER BY, it MUST appear in FROM or JOIN.
8. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.
9. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks
10. Do not wrap the query in markdown code fences
11. For "total per entity" vs "average of those totals", compute per-entity SUM with GROUP BY, then compare via HAVING to AVG of those SUMs in a subquery
12. Never reference columns from a subquery alias unless that column is explicitly selected by it"""

schema_context = """
=== TABLE: genre ===
Rows: ~25

COLUMNS:
  genre.genre_id : INTEGER [PRIMARY KEY, NOT NULL]
  genre.name : VARCHAR(120)

JOIN PATHS:
  To track: track.genre_id = genre.genre_id

================================================================================
=== TABLE: track ===
Rows: ~3503

COLUMNS:
  track.album_id : INTEGER
  track.genre_id : INTEGER
  track.milliseconds : INTEGER [NOT NULL]
  track.name : VARCHAR(200) [NOT NULL]
  track.track_id : INTEGER [PRIMARY KEY, NOT NULL]
  track.unit_price : NUMERIC(10, 2) [NOT NULL]

FOREIGN KEYS:
  track.genre_id -> genre.genre_id

JOIN PATHS:
  To genre: track.genre_id = genre.genre_id
  To invoice_line: invoice_line.track_id = track.track_id

================================================================================
=== TABLE: invoice_line ===
Rows: ~2240

COLUMNS:
  invoice_line.invoice_id : INTEGER [NOT NULL]
  invoice_line.invoice_line_id : INTEGER [PRIMARY KEY, NOT NULL]
  invoice_line.quantity : INTEGER [NOT NULL]
  invoice_line.track_id : INTEGER [NOT NULL]
  invoice_line.unit_price : NUMERIC(10, 2) [NOT NULL]

FOREIGN KEYS:
  invoice_line.track_id -> track.track_id

JOIN PATHS:
  To track: invoice_line.track_id = track.track_id

GLOBAL FOREIGN KEY RELATIONSHIPS:
  track.genre_id -> genre.genre_id
  invoice_line.track_id -> track.track_id
"""

FEW_SHOT_EXAMPLES = """
EXAMPLES OF CORRECT SQL PATTERNS:

EXAMPLE 1: Find entities whose total revenue exceeds the average entity revenue

IMPORTANT VOCABULARY:
- "total revenue per genre" = SUM of (quantity * unit_price) or SUM(unit_price) grouped by genre
- "average genre revenue" = AVG of per-genre totals -> AVG() on pre-grouped SUMs
- TWO levels: first SUM per entity, then AVG of those sums in subquery

Schema:
  categories.category_id, categories.name
  products.product_id, products.category_id, products.price
  sales.sale_id, sales.product_id, sales.quantity, sales.unit_price

Question: Find categories whose total revenue is higher than the average category revenue.

SQL:
SELECT
    categories.category_id,
    categories.name,
    SUM(sales.quantity * sales.unit_price) AS total_revenue
FROM categories
JOIN products ON categories.category_id = products.category_id
JOIN sales ON products.product_id = sales.product_id
GROUP BY categories.category_id, categories.name
HAVING SUM(sales.quantity * sales.unit_price) > (
    SELECT AVG(cat_revenue)
    FROM (
        SELECT SUM(sales.quantity * sales.unit_price) AS cat_revenue
        FROM products
        JOIN sales ON products.product_id = sales.product_id
        GROUP BY products.category_id
    ) sub
)
ORDER BY total_revenue DESC;

WHY THIS WORKS:
- SUM(quantity * unit_price) per category in outer GROUP BY
- Inner subquery computes SUM per category independently
- AVG wraps those sums — computes ONCE, not per row
- HAVING filters after grouping
- JOIN chain: categories -> products -> sales (multi-hop)
"""

user_question = "Find genres whose total revenue is higher than the average genre revenue."

user_prompt = f"""Schema:
{schema_context}

{FEW_SHOT_EXAMPLES}

NOW WRITE THE SQL FOR THIS:

Question: {user_question}

BEFORE WRITING — CHECK:
- Revenue per genre = SUM(invoice_line.quantity * invoice_line.unit_price) grouped by genre
- JOIN path: genre -> track -> invoice_line (genre.genre_id = track.genre_id AND track.track_id = invoice_line.track_id)
- Average genre revenue = AVG of per-genre SUMs in nested subquery
- Inner subquery: SELECT SUM(invoice_line.quantity * invoice_line.unit_price) FROM track JOIN invoice_line ON track.track_id = invoice_line.track_id GROUP BY track.genre_id
- HAVING SUM(...) > (SELECT AVG(genre_rev) FROM (...) sub)
- Copy the exact HAVING pattern from Example 1 above

SQL:"""

total_chars = len(system_prompt) + len(user_prompt)
est_tokens = total_chars / 3.5
print("=" * 70)
print("TEST v2 — Test 6: Genre revenue > avg genre revenue")
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
    "Uses genre table": "GENRE" in upper,
    "Uses track table": "TRACK" in upper,
    "Uses invoice_line table": "INVOICE_LINE" in upper,
    "JOIN present (2+)": upper.count("JOIN") >= 2,
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
            for row in (d.get("data") or [])[:10]:
                print(f"    {row}")
        else:
            print(f"  EXECUTION: FAILED — {d.get('error', 'unknown')[:300]}")
    except Exception as e:
        print(f"  EXECUTION: ERROR — {e}")
