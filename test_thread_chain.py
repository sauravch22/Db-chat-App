"""
Thread Chain Test — Simulates 5 follow-up prompts to test LLM contextual understanding.

Each prompt builds on the previous one, passing accumulated message history
exactly as a thread-based chat would.
"""

import requests
import json
import time

API_URL = "https://517d6b5cb913.ngrok.app/v1/chat/completions"
MODEL = "Qwen/Qwen3-Coder-Next"

SCHEMA = """CREATE TABLE artist (
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

SYSTEM_PROMPT = (
    "You are a PostgreSQL SQL expert. Your ONLY job is to output a single raw SQL SELECT query.\n\n"
    "STRICT RULES:\n"
    "1. Output ONLY the SQL query — no explanation, no preamble, no commentary\n"
    "2. Do NOT write \"Here is\", \"The SQL is\", or any sentence before or after the query\n"
    "3. Only use SELECT statements — never INSERT, UPDATE, DELETE, DROP\n"
    "4. Use ONLY table/column names from the CREATE TABLE statements — do not guess or invent names\n"
    "5. Always use table-qualified column names (table.column)\n"
    "6. For comparisons to averages or totals, use a subquery; do NOT nest aggregates directly. Do NOT use CTE / WITH.\n"
    "7. Use standard PostgreSQL syntax — double quotes for identifiers if needed, NOT backticks\n"
    "8. Do not wrap the query in markdown code fences\n"
    "9. When the user says 'filter', 'sort', 'also show', 'now', 'instead', etc., "
    "they are refining or building on the PREVIOUS query. Modify the previous SQL accordingly."
)

# ── The 5-prompt chain ──────────────────────────────────────────
# Each prompt is a natural follow-up that references the prior result.
# This is EXACTLY how a user in a thread would talk.

PROMPTS = [
    # Prompt 1: Initial standalone query
    "Find customers whose total spending is higher than the average customer spending.",

    # Prompt 2: Follow-up filter (references "those customers")
    "Filter those to only customers from Brazil and Germany.",

    # Prompt 3: Follow-up refinement (references "the results")
    "Sort by spending descending and limit to top 5.",

    # Prompt 4: Follow-up enrichment (add more columns)
    "Also show which support rep handles each customer.",

    # Prompt 5: Pivot to related analysis (references "these top customers")
    "What genres do these top customers buy the most?",
]


def call_llm(messages: list[dict]) -> str:
    """Send messages to the LLM and return the assistant response text."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 512,
    }
    resp = requests.post(API_URL, json=payload, headers={"Content-Type": "application/json"}, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def run_chain():
    # Start with system message only
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("=" * 80)
    print("THREAD CHAIN TEST — 5 follow-up prompts with accumulated history")
    print("=" * 80)

    for i, prompt in enumerate(PROMPTS, 1):
        print(f"\n{'─' * 80}")
        print(f"  PROMPT {i}: {prompt}")
        print(f"{'─' * 80}")

        # For prompt 1, include the schema in the user message.
        # For prompts 2-5, just the follow-up question (schema is already in context).
        if i == 1:
            user_content = f"### Database Schema\n\n{SCHEMA}\n\n### Task\n{prompt}\n\n### SQL\n"
        else:
            user_content = prompt

        messages.append({"role": "user", "content": user_content})

        t0 = time.time()
        try:
            sql = call_llm(messages)
            elapsed = time.time() - t0
        except Exception as exc:
            print(f"  ❌ ERROR: {exc}")
            # Still append a placeholder so the chain can try to continue
            messages.append({"role": "assistant", "content": f"-- error: {exc}"})
            continue

        # Clean up the SQL (strip markdown fences if any)
        clean_sql = sql.replace("```sql", "").replace("```", "").strip()

        print(f"\n  ✅ RESPONSE ({elapsed:.1f}s):\n")
        for line in clean_sql.split("\n"):
            print(f"    {line}")

        # Append assistant response to message history (this IS the thread context)
        messages.append({"role": "assistant", "content": clean_sql})

        # Show message count so far
        print(f"\n  📨 Messages in context: {len(messages)} (system + {i} user + {i} assistant)")

    # ── Summary ──
    print(f"\n{'=' * 80}")
    print("SUMMARY — Thread Context Accumulation")
    print(f"{'=' * 80}")
    print(f"  Total messages sent to LLM on last call: {len(messages)}")
    print(f"  System: 1")
    print(f"  User messages: {len(PROMPTS)}")
    print(f"  Assistant messages: {len(PROMPTS)}")
    print()
    print("  KEY OBSERVATIONS:")
    print("  • Prompt 2 says 'Filter those' — LLM must remember what 'those' means")
    print("  • Prompt 3 says 'Sort by spending descending' — must know which query to sort")
    print("  • Prompt 4 says 'Also show' — must ADD columns to existing query")
    print("  • Prompt 5 says 'these top customers' — must reference the subquery from prompt 3")
    print()
    print("  If the LLM correctly builds on each previous SQL, the thread approach works.")
    print("  If it ignores context and generates standalone queries, we need stronger prompting.")
    print()


if __name__ == "__main__":
    run_chain()
