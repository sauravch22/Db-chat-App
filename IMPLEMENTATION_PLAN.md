# DbChat v13 — Implementation Plan

## Feature 1: Query Explanation Mode
## Feature 2: Multi-Turn Conversations (Context Memory)

---

# FEATURE 1 — QUERY EXPLANATION MODE (🧠 Explain)

## What It Does

After any SQL query is generated and executed, an **"🧠 Explain"** button appears next to "🔍 Explore" and "📌 Pin Data." Clicking it sends the SQL + schema context + user prompt to the LLM, which returns a structured plain-English breakdown of the query — what each JOIN does, what filters apply, what the aggregation computes.

Non-technical users gain understanding; technical users use it as a quick audit of what the system actually ran.

## Files to Modify

| File | What Changes |
|---|---|
| `app/services/ollama_service.py` | Add `explain_sql()` method |
| `app/api/routes/chat.py` | Add `POST /api/chat/explain` endpoint |
| `frontend/app.js` | Add Explain button in `addBotReply()`, modal rendering |
| `frontend/index.html` | Add the Explain modal HTML |

---

### Step 1 — `ollama_service.py` — Add `explain_sql()`

Add a new method after `generate_sql_with_reasoning()` (~line 220):

```python
async def explain_sql(
    self,
    sql: str,
    user_prompt: str,
    schema_context: str,
    columns: list = None,
    row_count: int = None
) -> str:
    system = """You are a SQL teacher explaining a query to a business user
who does NOT know SQL. Break down the query into sections:

1. **What this query does** — one-sentence summary
2. **Tables used** — list each table and what data it holds
3. **How tables connect** — explain each JOIN in plain English
4. **Filters applied** — explain WHERE conditions in plain English
5. **Calculations** — explain any SUM, COUNT, AVG, GROUP BY
6. **Sorting & Limits** — explain ORDER BY and LIMIT if present

Use bullet points. No SQL syntax in your explanation — only plain English.
Keep it concise — max 200 words."""

    prompt = f"""User's original question: {user_prompt}

SQL query that was generated:
{sql}

Database schema used:
{schema_context}

{f"Result: {row_count} rows returned with columns: {', '.join(columns)}" if columns else ""}

Explain this query in plain English:"""

    try:
        explanation = await self._call_chat_completions(
            system, prompt, temperature=0.3, max_tokens=512
        )
        return explanation
    except Exception as e:
        logger.error(f"Error explaining SQL: {str(e)}")
        return "Unable to generate explanation at this time."
```

**Design rationale:**
- Temperature 0.3 — more natural language than SQL gen (which uses 0.0), but still focused
- 512 max tokens — concise explanations, not essays
- Structured system prompt — enforces consistent 6-section breakdown every time
- Schema context included — the LLM knows what "customers" and "invoices" actually hold
- Result metadata (row_count, columns) gives the LLM result-awareness

---

### Step 2 — `chat.py` — Add explain endpoint

Add after the existing `/execute` endpoint (after line 291):

```python
class ExplainRequest(BaseModel):
    connection_id: int
    sql: str
    prompt: str
    schema_context: Optional[str] = None
    columns: Optional[List[str]] = None
    row_count: Optional[int] = None

class ExplainResponse(BaseModel):
    explanation: str
    execution_time_ms: int

@router.post("/explain", response_model=ExplainResponse)
async def explain_query(
    request: ExplainRequest,
    req: Request,
    user: dict = Depends(get_current_user),
):
    if not has_db_permission(user, request.connection_id, "prompt_query"):
        raise HTTPException(status_code=403, detail="Permission required")

    t0 = time.time()
    try:
        chat_service = ChatService()
        try:
            schema_context = request.schema_context
            if not schema_context:
                schema_context = chat_service.metadata.get_column_schema(
                    request.connection_id,
                    chat_service._extract_tables_from_sql(request.sql)
                ) or "Schema not available"

            explanation = await chat_service.ollama.explain_sql(
                sql=request.sql,
                user_prompt=request.prompt,
                schema_context=schema_context,
                columns=request.columns,
                row_count=request.row_count
            )
            dur = int((time.time() - t0) * 1000)
            await log_activity(
                req, user=user, action="chat.explain",
                connection_id=request.connection_id,
                detail={"sql": request.sql[:300], "prompt": request.prompt[:200]},
                duration_ms=dur
            )
            return ExplainResponse(explanation=explanation, execution_time_ms=dur)
        finally:
            chat_service.close()
    except Exception as e:
        logger.error(f"Explain endpoint error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
```

**Also add a helper to `ChatService`** (in `chat_service.py`):

```python
def _extract_tables_from_sql(self, sql: str) -> list:
    """Extract table names from a SQL query (best effort)."""
    import re
    tables = set()
    pattern = r'(?:FROM|JOIN)\s+"?(\w+)"?'
    for match in re.finditer(pattern, sql, re.IGNORECASE):
        tables.add(match.group(1))
    return list(tables)
```

**Why rebuild schema if missing:** When "Explain" is clicked on a history message, the original schema_context might not be in the frontend payload. This fallback parses the SQL for table names and rebuilds it.

---

### Step 3 — `frontend/app.js` — Explain button + handler

In `addBotReply()`, the action buttons are rendered after the data table. Currently:

```
🔍 Explore full data    📌 Pin Data
```

**Add a third button** right after Pin Data:

```javascript
const explainBtnId = 'explain-' + ts;
if (data.sql) {
    h += `<button id="${explainBtnId}" class="chip"
           style="color:#a78bfa;border-color:rgba(167,139,250,.3)">
           🧠 Explain</button>`;
}
```

**Click handler** (after the pinDataBtn handler):

```javascript
const explainBtn = document.getElementById(explainBtnId);
if (explainBtn) {
    explainBtn.onclick = async () => {
        explainBtn.disabled = true;
        explainBtn.textContent = '🧠 Thinking...';
        try {
            const r = await authFetch(`${chatUrl()}/api/chat/explain`, {
                method: 'POST',
                body: JSON.stringify({
                    connection_id: selectedConnId,
                    sql: data.sql,
                    prompt: query,
                    schema_context: data.schema_context || null,
                    columns: data.columns || null,
                    row_count: data.row_count || null
                })
            });
            const result = await r.json();
            openExplainModal(result.explanation, data.sql, query);
        } catch (err) {
            alert('Failed to generate explanation');
        } finally {
            explainBtn.disabled = false;
            explainBtn.textContent = '🧠 Explain';
        }
    };
}
```

**`openExplainModal()` function:**

```javascript
function openExplainModal(explanation, sql, prompt) {
    const modal = document.getElementById('explainModal');
    const body = document.getElementById('explainBody');
    let html = explanation
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/^- /gm, '• ')
        .replace(/\n/g, '<br>');
    body.innerHTML = `
        <div style="margin-bottom:12px;color:#94a3b8;font-size:13px">
            <em>Question: "${prompt}"</em>
        </div>
        <div style="line-height:1.7;color:#e2e8f0;font-size:14px">${html}</div>
        <details style="margin-top:16px">
            <summary style="cursor:pointer;color:#64748b;font-size:12px">View SQL</summary>
            <pre style="background:#0f172a;padding:12px;border-radius:8px;
                        margin-top:8px;font-size:12px;color:#7c6eff;
                        overflow-x:auto">${esc(sql)}</pre>
        </details>`;
    modal.classList.add('active');
}
```

---

### Step 4 — `frontend/index.html` — Explain modal markup

Add after the existing chart modal:

```html
<div id="explainModal" class="modal-overlay">
    <div class="modal-content" style="max-width:640px">
        <div class="modal-header">
            <h2>🧠 Query Explanation</h2>
            <button class="modal-close"
                onclick="document.getElementById('explainModal').classList.remove('active')">✕</button>
        </div>
        <div id="explainBody" class="modal-body"
             style="max-height:70vh;overflow-y:auto;padding:20px"></div>
    </div>
</div>
```

---

### Explain Feature — Flow Summary

```
User clicks "🧠 Explain"
  → Frontend POSTs to /api/chat/explain  { sql, prompt, schema_context, columns, row_count }
  → Backend calls ollama.explain_sql()
  → LLM returns structured plain-English breakdown
  → Frontend opens modal with formatted explanation
```

**Effort: ~2-3 hours.** One new OllamaService method, one new API endpoint, one frontend button + modal. No database changes. No model changes. Fully additive.

---
---

# FEATURE 2 — MULTI-TURN CONVERSATIONS (Context Memory)

## What Changes Fundamentally

Today, every chat message is **stateless**:

```
POST /api/chat  { connection_id: 3, prompt: "find customers..." }
→ SQL generated from scratch, no memory of what came before
```

After this feature:

```
POST /api/chat  { connection_id: 3, prompt: "find customers...", conversation_id: "conv_abc123" }
→ System checks prior turns
→ Classifies: is this a modification or new query?
→ Passes prior SQL/results as context
→ LLM modifies or generates informed SQL
```

## The Four Intent Types

Every user follow-up falls into one of four categories:

| Intent | Example | What Happens |
|---|---|---|
| `first_query` | "Show me top customers" | Normal flow — no prior context exists |
| `modify_sql` | "Also show country", "Filter to USA", "Sort by revenue" | Previous SQL is **edited surgically** |
| `new_with_context` | "Show me their invoices", "What did they buy?" | **New SQL** generated, but prior context informs it |
| `question_about_results` | "How many is that?", "What's the average?" | No SQL — answered from cached result metadata |

### Why Two Types of Follow-ups?

This is the critical architectural insight. "Add the country column" and "Show me their invoices" both reference previous context, but they require fundamentally different handling:

**SQL Modification** → The LLM receives the previous SQL + the modification request. It surgically edits the existing query (add a column, add a WHERE, change ORDER BY). The table set doesn't change.

**New Query with Context** → The LLM generates a completely new SQL, but it gets a summary of the conversation so far. "Their invoices" means "invoices for the customers we just found." This might involve different tables entirely.

---

## Files to Create

| File | Purpose |
|---|---|
| `app/services/conversation_service.py` | **New** — conversation orchestrator (intent classifier, SQL modifier, context manager) |

## Files to Modify

| File | What Changes |
|---|---|
| `app/models.py` | Add `Conversation` model + two columns on `ChatHistory` |
| `app/services/ollama_service.py` | Add `modify_sql()` method |
| `app/services/chat_service.py` | Add `_extract_tables_from_sql()` helper |
| `app/api/routes/chat.py` | Modify `POST /api/chat` to accept `conversation_id`, add conversation management endpoints |
| `serve.py` | Add migration for new `ChatHistory` columns |
| `frontend/app.js` | Track conversation_id, send with each request, show intent badges, "New" button |

---

## PHASE 1: Database Model + Migration

### Step 1.1 — Add `Conversation` model to `models.py`

Add after the `ChatHistory` model (~line 280):

```python
class Conversation(Base):
    """
    Tracks a multi-turn conversation session.
    Each conversation belongs to one user on one database connection.
    Turns are stored in chat_history linked by conversation_id.
    """
    __tablename__ = "conversations"

    id            = SA_Column(Integer, primary_key=True)
    conversation_id = SA_Column(String(64), unique=True, nullable=False, index=True)
    user_id       = SA_Column(Integer, SA_ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    connection_id = SA_Column(Integer, SA_ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    is_active     = SA_Column(Boolean, default=True)
    turn_count    = SA_Column(Integer, default=0)
    last_sql      = SA_Column(Text, nullable=True)
    last_columns  = SA_Column(Text, nullable=True)       # JSON array
    last_row_count = SA_Column(Integer, nullable=True)
    last_tables   = SA_Column(Text, nullable=True)        # JSON array
    last_schema_context = SA_Column(Text, nullable=True)  # cached schema for modifications
    created_at    = SA_Column(DateTime, default=datetime.utcnow)
    updated_at    = SA_Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Design rationale:**
- **Lightweight state object.** Stores only what the next turn needs: last SQL, last columns, last table set, cached schema.
- **No full history in JSON blobs.** Each turn is already a `ChatHistory` row — they're linked by `conversation_id`.
- **`last_schema_context` cached.** The modify_sql path needs schema context but we shouldn't re-fetch/re-embed every turn.

### Step 1.2 — Add columns to `ChatHistory`

```python
# Add these two columns to the existing ChatHistory class:
conversation_id = SA_Column(String(64), nullable=True, index=True)
intent          = SA_Column(String(30), nullable=True)
```

These are **nullable** — all existing history rows keep working with NULL values. Zero migration risk.

### Step 1.3 — Migration in `serve.py`

Add after the existing `user_permissions` migration block:

```python
cols = [c["name"] for c in insp.get_columns("chat_history")]
if "conversation_id" not in cols:
    conn.execute(text("ALTER TABLE chat_history ADD COLUMN conversation_id VARCHAR(64)"))
    conn.execute(text("ALTER TABLE chat_history ADD COLUMN intent VARCHAR(30)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_history_conv_id ON chat_history (conversation_id)"))
    conn.commit()
    logger.info("Migrated: added conversation_id, intent to chat_history")
```

---

## PHASE 2: Intent Classifier (Rule-Based)

### Step 2.1 — `ConversationIntentClassifier` in `conversation_service.py`

```python
class ConversationIntentClassifier:
    """
    Rule-based intent classifier. Fast, deterministic, handles 80% of cases.
    Can be upgraded to LLM-based later if needed.
    """

    MODIFICATION_SIGNALS = [
        "also show", "also include", "add column", "include",
        "but only", "but just", "filter to", "filter by", "filter for",
        "where", "only show", "only include", "exclude", "remove",
        "sort by", "order by", "sort it", "sort them",
        "limit to", "top ", "bottom ", "just the",
        "now show", "instead show", "change to", "switch to",
        "group by", "break down by", "break it down",
        "ascending", "descending", "without the",
    ]

    REFERENCE_SIGNALS = [
        "those", "them", "they", "their", "these",
        "that", "the same", "among them", "from those",
        "of those", "for them", "for these", "for those",
    ]

    RESULT_QUESTION_SIGNALS = [
        "how many is that", "how many are there",
        "what's the total", "what is the total",
        "what's the average", "what is the average",
        "how much is that", "summarize",
    ]

    def classify(self, user_message: str, has_prior_turns: bool, last_sql: str = None) -> str:
        if not has_prior_turns or not last_sql:
            return "first_query"

        msg = user_message.lower().strip()
        word_count = len(msg.split())

        # Result questions (very specific patterns)
        if any(sig in msg for sig in self.RESULT_QUESTION_SIGNALS):
            return "question_about_results"

        # Modification signals
        has_mod = any(sig in msg for sig in self.MODIFICATION_SIGNALS)
        if has_mod and word_count <= 20:
            return "modify_sql"

        # Reference signals without modification → new query using context
        has_ref = any(sig in msg for sig in self.REFERENCE_SIGNALS)
        if has_ref:
            return "new_with_context"

        # Very short follow-ups (< 5 words) → likely modifications
        if word_count <= 4 and has_prior_turns:
            return "modify_sql"

        # Default: new query with context available
        return "new_with_context"
```

**Why rule-based, not LLM-based:**
- Zero latency — no extra LLM call per message
- Deterministic — same input always gives same classification
- The signal lists cover the vast majority of natural follow-up patterns
- Can be upgraded to LLM-fallback later for ambiguous cases

---

## PHASE 3: `modify_sql()` in OllamaService

Add after `generate_sql_with_reasoning()` in `ollama_service.py`:

```python
async def modify_sql(
    self,
    user_message: str,
    previous_sql: str,
    previous_columns: list,
    schema_context: str
) -> str:
    system = """You are a PostgreSQL SQL expert.
You will be given an existing SQL query and a modification request.
Output ONLY the modified SQL — complete and executable. No explanation.

Rules:
- Preserve ALL existing logic unless explicitly asked to change it
- Never remove WHERE conditions unless the user asks to
- Never change JOINs unless the modification requires it
- If adding a column: add to SELECT and GROUP BY if needed
- If filtering: add to WHERE clause (AND with existing conditions)
- If sorting: add or replace ORDER BY
- If adding a new table: add appropriate JOIN using schema foreign keys
- Always use table-qualified column names
- Use standard PostgreSQL syntax
- Do NOT use CTE / WITH — use subqueries"""

    prompt = f"""Existing SQL:
{previous_sql}

Current result columns: {', '.join(previous_columns)}

Schema:
{schema_context}

Modification requested: {user_message}

Modified SQL:"""

    try:
        raw = await self._call_chat_completions(system, prompt, temperature=0.0)
        return self._clean_sql_output(raw)
    except Exception as e:
        logger.error(f"Error modifying SQL: {str(e)}")
        return None
```

**Critical difference from `generate_sql()`:**
- `generate_sql()` creates SQL from a natural language question
- `modify_sql()` **edits** existing SQL based on a modification request
- The system prompt explicitly tells the LLM to **preserve** everything not mentioned
- Temperature 0.0 for deterministic, surgical edits

---

## PHASE 4: Conversation Service (the Orchestrator)

### `app/services/conversation_service.py` — Full Implementation

This is the **core new file**. It:
1. Loads or creates a conversation
2. Classifies the user's intent
3. Routes to the correct handler
4. Updates conversation state for the next turn

```python
class ConversationService:
    """
    Wraps ChatService — does NOT replace it.
    
    - first_query → delegates to ChatService.process_query() unchanged
    - modify_sql → uses OllamaService.modify_sql() + execute + repair
    - new_with_context → enriches prompt with conversation context, then delegates to ChatService
    - question_about_results → answers from cached metadata, no SQL
    """

    def __init__(self):
        self.classifier = ConversationIntentClassifier()
        self.chat_service = ChatService()
        self.ollama = OllamaService()

    def close(self):
        self.chat_service.close()

    async def process_message(
        self,
        user_id: int,
        connection_id: int,
        user_message: str,
        conversation_id: Optional[str] = None,
        top_k_tables: int = 5
    ) -> Dict[str, Any]:
        """Main entry point. Same return shape as ChatService.process_query()."""
        db = SessionLocal()
        try:
            # 1. Load conversation
            conv = None
            if conversation_id:
                conv = db.query(Conversation).filter(
                    Conversation.conversation_id == conversation_id,
                    Conversation.user_id == user_id,
                    Conversation.connection_id == connection_id,
                    Conversation.is_active == True
                ).first()

            has_prior = conv is not None and conv.turn_count > 0
            last_sql = conv.last_sql if conv else None

            # 2. Classify intent
            intent = self.classifier.classify(user_message, has_prior, last_sql)

            # 3. Route by intent
            if intent == "question_about_results":
                result = await self._handle_result_question(user_message, conv)
            elif intent == "modify_sql":
                result = await self._handle_sql_modification(
                    connection_id, user_message, conv, top_k_tables
                )
            elif intent == "new_with_context":
                context_summary = self._build_context_summary(conv, db)
                enriched = self._enrich_prompt(user_message, context_summary)
                result = await self.chat_service.process_query(
                    connection_id, enriched, top_k_tables
                )
            else:  # first_query
                result = await self.chat_service.process_query(
                    connection_id, user_message, top_k_tables
                )

            result["intent"] = intent

            # 4. Update conversation state
            if not conv:
                conv = Conversation(
                    conversation_id=conversation_id or f"conv_{uuid.uuid4().hex[:12]}",
                    user_id=user_id,
                    connection_id=connection_id,
                    turn_count=0, is_active=True
                )
                db.add(conv)

            conv.turn_count += 1
            conv.updated_at = datetime.utcnow()
            if result.get("sql"):
                conv.last_sql = result["sql"]
            if result.get("columns"):
                conv.last_columns = json.dumps(result["columns"])
            if result.get("row_count") is not None:
                conv.last_row_count = result["row_count"]
            if result.get("selected_tables"):
                conv.last_tables = json.dumps(result["selected_tables"])
            if result.get("schema_context"):
                conv.last_schema_context = result["schema_context"]

            db.commit()

            result["conversation_id"] = conv.conversation_id
            result["turn_number"] = conv.turn_count
            return result

        except Exception as e:
            logger.error(f"Conversation error: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": f"Conversation processing failed: {str(e)}",
                "conversation_id": conversation_id,
                "intent": "error"
            }
        finally:
            db.close()
```

### `_handle_sql_modification()` — The surgical edit handler

```python
async def _handle_sql_modification(self, connection_id, user_message, conv, top_k_tables):
    last_sql = conv.last_sql
    last_columns = json.loads(conv.last_columns) if conv.last_columns else []
    last_tables = json.loads(conv.last_tables) if conv.last_tables else []
    schema_context = conv.last_schema_context

    # Rebuild schema if not cached
    if not schema_context and last_tables:
        schema_context = self.chat_service.metadata.get_column_schema(
            connection_id, last_tables
        )
    if not schema_context:
        # Fallback: treat as new query
        return await self.chat_service.process_query(connection_id, user_message, top_k_tables)

    # Generate modified SQL
    modified_sql = await self.ollama.modify_sql(
        user_message, last_sql, last_columns, schema_context
    )
    if not modified_sql:
        return {"status": "error", "error": "Failed to modify SQL"}

    modified_sql = modified_sql.replace('`', '"')

    # Validate + Execute
    validation_error = self.chat_service._validate_sql(modified_sql)
    if validation_error:
        return {"status": "error", "error": f"Invalid modified SQL: {validation_error}", "sql": modified_sql}

    # Load connection and execute
    connection = db.query(Connection).filter(Connection.id == connection_id, Connection.is_active == True).first()
    exec_result = await self.chat_service._execute_query(connection=connection, sql=modified_sql, timeout=30)

    # Repair loop (1 retry) if execution fails
    if exec_result.get("status") == "error":
        error_text = exec_result.get("error", "")
        repair_sql = await self.ollama.modify_sql(
            f"Fix this error: {error_text}. Original request: {user_message}",
            modified_sql, last_columns, schema_context
        )
        if repair_sql:
            repair_sql = repair_sql.replace('`', '"')
            exec_result = await self.chat_service._execute_query(connection=connection, sql=repair_sql, timeout=30)
            if exec_result.get("status") == "success":
                modified_sql = repair_sql

    if exec_result.get("status") == "error":
        return {**exec_result, "sql": modified_sql, "selected_tables": last_tables, "schema_context": schema_context}

    # Format answer
    answer = await self.chat_service._format_answer(
        user_prompt=user_message, sql=modified_sql,
        rows=exec_result["rows"], columns=exec_result["columns"],
        row_count=exec_result["row_count"]
    )

    return {
        "status": "success", "answer": answer, "sql": modified_sql,
        "rows": exec_result["rows"], "columns": exec_result["columns"],
        "row_count": exec_result["row_count"],
        "selected_tables": last_tables, "schema_context": schema_context
    }
```

### `_handle_result_question()` — Answer without SQL

```python
async def _handle_result_question(self, user_message, conv):
    if not conv or not conv.last_row_count:
        return {
            "status": "success",
            "answer": "I don't have previous results. Please ask a data question first.",
            "sql": None, "rows": None, "columns": None, "row_count": None,
        }

    last_columns = json.loads(conv.last_columns) if conv.last_columns else []

    if "how many" in user_message.lower():
        return {
            "status": "success",
            "answer": f"The previous query returned **{conv.last_row_count}** rows.",
            "sql": None, "rows": None, "columns": None, "row_count": conv.last_row_count,
        }

    # For complex questions, ask the LLM with result metadata
    system = "You are a data analyst. Answer the user's question about query results. Be concise."
    prompt = (
        f"Previous query returned {conv.last_row_count} rows "
        f"with columns: {', '.join(last_columns)}.\n\n"
        f"Question: {user_message}\n\n"
        f"If you cannot answer from this metadata alone, say so clearly."
    )
    answer = await self.ollama._call_chat_completions(system, prompt, temperature=0.3, max_tokens=200)
    return {"status": "success", "answer": answer, "sql": None, "rows": None, "columns": None, "row_count": conv.last_row_count}
```

### `_build_context_summary()` — For `new_with_context`

```python
def _build_context_summary(self, conv, db):
    if not conv:
        return ""

    entries = (
        db.query(ChatHistory)
        .filter(ChatHistory.conversation_id == conv.conversation_id)
        .order_by(ChatHistory.created_at.desc())
        .limit(3)
        .all()
    )
    if not entries:
        return ""

    lines = ["Recent conversation context:"]
    for entry in reversed(entries):
        lines.append(f'- User asked: "{entry.prompt}"')
        if entry.row_count is not None:
            cols = json.loads(entry.columns) if entry.columns else []
            lines.append(f"  Result: {entry.row_count} rows, columns: {', '.join(cols)}")
        if entry.sql:
            sql_preview = entry.sql[:300] + "..." if len(entry.sql) > 300 else entry.sql
            lines.append(f"  SQL: {sql_preview}")

    if conv.last_sql:
        lines.append(f"\nMost recent SQL (full):\n{conv.last_sql}")

    return "\n".join(lines)
```

**Why only last 3 turns:** With a large model the context window is generous, but SQL schema context is already substantial. 3 turns give enough conversational context without crowding out the schema that `process_query()` will inject.

### `_enrich_prompt()` — Prefix context to the user message

```python
def _enrich_prompt(self, user_message, context_summary):
    if not context_summary:
        return user_message
    return (
        f"[CONVERSATION CONTEXT]\n{context_summary}\n"
        f"[END CONTEXT]\n\nCurrent question: {user_message}"
    )
```

The key trick: the enriched prompt is passed into the **existing** `process_query()` pipeline. The table selector, SQL generator, and answer formatter all run normally — they just have more context in the user prompt.

---

## PHASE 5: API Changes

### Step 5.1 — Modify `ChatRequest` and `ChatResponse`

```python
class ChatRequest(BaseModel):
    connection_id: int
    prompt: str
    top_k_tables: int = 5
    conversation_id: Optional[str] = None   # NEW

class ChatResponse(BaseModel):
    # ... existing fields ...
    conversation_id: Optional[str] = None   # NEW
    turn_number: Optional[int] = None       # NEW
    intent: Optional[str] = None            # NEW
```

### Step 5.2 — Modify `POST /api/chat` handler

```python
@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request, user: dict = Depends(get_current_user)):
    # ... permission check unchanged ...

    t0 = time.time()
    try:
        if request.conversation_id:
            # Multi-turn path
            from app.services.conversation_service import ConversationService
            conv_service = ConversationService()
            try:
                result = await conv_service.process_message(
                    user_id=int(user["sub"]),
                    connection_id=request.connection_id,
                    user_message=request.prompt,
                    conversation_id=request.conversation_id,
                    top_k_tables=request.top_k_tables
                )
            finally:
                conv_service.close()
        else:
            # Stateless path (backward compatible — nothing changes)
            chat_service = ChatService()
            try:
                result = await chat_service.process_query(
                    connection_id=request.connection_id,
                    user_prompt=request.prompt,
                    top_k_tables=request.top_k_tables
                )
            finally:
                chat_service.close()

        # ... rest of response handling stays the same ...
```

**Backward compatible.** If `conversation_id` is null, the exact existing flow runs. Zero breaking changes.

### Step 5.3 — Conversation management endpoints

```python
@router.post("/conversations")
async def create_conversation(connection_id: int, user: dict = Depends(get_current_user)):
    """Start a new conversation session."""
    from app.services.conversation_service import ConversationService
    conv_service = ConversationService()
    try:
        conv = await conv_service.get_or_create_conversation(
            user_id=int(user["sub"]), connection_id=connection_id
        )
        return {"conversation_id": conv.conversation_id, "connection_id": connection_id}
    finally:
        conv_service.close()

@router.delete("/conversations/{conversation_id}")
async def end_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    """End a conversation."""
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.conversation_id == conversation_id,
            Conversation.user_id == int(user["sub"])
        ).first()
        if conv:
            conv.is_active = False
            db.commit()
        return {"status": "ok"}
    finally:
        db.close()
```

---

## PHASE 6: Frontend Changes

### Step 6.1 — Track conversation_id

```javascript
let currentConversationId = null;

async function startConversation(connId) {
    try {
        const r = await authFetch(`${chatUrl()}/api/chat/conversations?connection_id=${connId}`, {
            method: 'POST'
        });
        const data = await r.json();
        currentConversationId = data.conversation_id;
    } catch (e) {
        currentConversationId = null;
    }
}
```

Call `startConversation()` when user selects a database connection.

### Step 6.2 — Send conversation_id with every chat

In `sendQuery()`:

```javascript
const r = await authFetch(`${chatUrl()}/api/chat`, {
    method: 'POST',
    body: JSON.stringify({
        connection_id: selectedConnId || 3,
        prompt: q,
        conversation_id: currentConversationId   // NEW
    })
});
```

### Step 6.3 — Intent badge in responses

In `addBotReply()`:

```javascript
if (data.intent && data.intent !== 'first_query') {
    const intentLabels = {
        'modify_sql': '✏️ Modified previous query',
        'new_with_context': '🔗 Context-aware query',
        'question_about_results': '💬 Answered from results'
    };
    h += `<span style="font-size:11px;color:#64748b;background:#1e293b;
           padding:2px 8px;border-radius:8px;margin-left:8px">
           ${intentLabels[data.intent] || data.intent}</span>`;
}
```

### Step 6.4 — "🔄 New Conversation" button

```javascript
<button onclick="clearAndRestart()" title="Start new conversation"
        style="background:none;border:1px solid #334155;border-radius:8px;
               padding:4px 8px;color:#64748b;cursor:pointer;font-size:12px">
    🔄 New
</button>

async function clearAndRestart() {
    // existing clear logic
    currentConversationId = null;
    await startConversation(selectedConnId);
}
```

### Step 6.5 — Save conversation_id in history

Update `_save_chat_history()` in `chat.py`:

```python
entry = ChatHistory(
    # ... existing fields ...
    conversation_id=conversation_id,   # NEW
    intent=result.get("intent"),       # NEW
)
```

---

## Implementation Timeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  WEEK 1: Explain Mode (standalone, no dependencies)                 │
│                                                                     │
│  Day 1:  ollama_service.py — add explain_sql()                      │
│  Day 1:  chat.py — add POST /api/chat/explain                      │
│  Day 2:  frontend — Explain button + modal                          │
│  Day 2:  Test end-to-end                                            │
│                                                                     │
│  ✅ Ship as v13.0 — fully independent feature                      │
├─────────────────────────────────────────────────────────────────────┤
│  WEEK 2: Conversation Backend                                       │
│                                                                     │
│  Day 1:  models.py — Conversation model + ChatHistory columns       │
│  Day 1:  serve.py — migration for new columns                       │
│  Day 2:  conversation_service.py — IntentClassifier + shell         │
│  Day 2:  ollama_service.py — modify_sql()                           │
│  Day 3:  conversation_service.py — full process_message()           │
│  Day 3:  Wire to chat.py (backward-compatible)                      │
│  Day 4:  Test: first_query path (verify nothing breaks)             │
│  Day 4:  Test: modify_sql with simple cases                         │
│                                                                     │
│  ✅ Ship as v13.1 — backend ready, frontend still stateless        │
├─────────────────────────────────────────────────────────────────────┤
│  WEEK 3: Frontend + Polish                                          │
│                                                                     │
│  Day 1:  frontend — conversation tracking, send conversation_id     │
│  Day 1:  frontend — intent badge, "New Conversation" button         │
│  Day 2:  Test full conversations: progressive refinement            │
│  Day 2:  Test: exploration, drill-down, comparison use cases        │
│  Day 3:  Edge cases — misclassified intents, repair failures        │
│  Day 3:  Save conversation_id in chat history                       │
│                                                                     │
│  ✅ Ship as v13.2 — full multi-turn conversations                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Test Scenarios

### Test 1: Progressive Refinement
```
"Show me top customers"                    → first_query
"Also show their country"                  → modify_sql (adds column)
"Filter to USA only"                       → modify_sql (adds WHERE)
"Sort by spending descending"              → modify_sql (adds ORDER BY)
"Top 5 only"                               → modify_sql (adds LIMIT)
```

### Test 2: Exploration
```
"How many invoices do we have?"            → first_query
"Break that down by country"               → modify_sql (adds GROUP BY)
"Which country has the highest average?"   → modify_sql (ORDER BY + LIMIT)
"Show me those customers"                  → new_with_context (different tables!)
```

### Test 3: Result Questions
```
"Show me customers from Germany"           → first_query
"How many is that?"                        → question_about_results (no SQL)
"Who's the biggest spender among them?"    → new_with_context
```

### Test 4: Conversation Reset
```
"Revenue by genre"                         → first_query
"Top 5 only"                               → modify_sql
[User clicks 🔄 New]
"Show all employees"                       → first_query (fresh context)
```

---

## Edge Cases

| Edge Case | Resolution |
|---|---|
| Completely unrelated follow-up | Classified as `new_with_context`; context is available but LLM generates fresh SQL |
| Modification produces invalid SQL | Repair loop retries once; falls back to error response |
| Schema context too large | Cached from last turn; only covers the tables from the last query |
| Very long conversation (20+ turns) | Context summary uses last 3 turns; older turns are in ChatHistory but not in the prompt |
| User switches databases | `conversation_id` is per-connection; switching DB starts a new conversation |
| `conversation_id` is null/missing | Falls back to stateless path — zero breaking changes |
| LLM misclassifies intent | User can click "🔄 New" to reset; repair loop handles invalid SQL |

---

## Architecture After v13

```
Frontend
    │
    │  { prompt, connection_id, conversation_id }
    ▼
POST /api/chat
    │
    ├── conversation_id is NULL?
    │   └── YES → ChatService.process_query()        ← existing stateless path
    │
    └── NO → ConversationService.process_message()
              │
              ├── Classify intent (rule-based, 0ms)
              │   │
              │   ├── first_query
              │   │   └→ ChatService.process_query()  ← same existing path
              │   │
              │   ├── modify_sql
              │   │   └→ OllamaService.modify_sql()
              │   │      → validate → execute → repair if needed → format
              │   │
              │   ├── new_with_context
              │   │   └→ enrich prompt with context summary
              │   │      → ChatService.process_query() ← same path, richer prompt
              │   │
              │   └── question_about_results
              │       └→ answer from cached metadata (no SQL)
              │
              └── Update Conversation state (last_sql, last_columns, etc.)
```

**No existing flow is broken. The conversation layer is purely additive.**
