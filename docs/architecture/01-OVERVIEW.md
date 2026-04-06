# DbChat — Architecture Overview

DbChat is a **natural-language-to-SQL** web application that lets users connect to
relational and NoSQL databases, ask questions in plain English, and receive
structured answers with data, charts, and AI-powered insights.

---

## High-Level Stack

```
┌─────────────────────────────────────────────────────────────┐
│                    BROWSER (Vanilla JS)                     │
│  index.html · app.js · features.js · Tailwind · Chart.js   │
└────────────────┬────────────────────────────────────────────┘
                 │  HTTP / SSE / WebSocket
                 ▼
┌────────────────────────────┐     ┌──────────────────────┐
│  frontend/server.py :3000  │────▶│  viz-service :8001   │
│  (static files + /api      │     │  Chart recommendations│
│   reverse-proxy to :8000)  │     └──────────────────────┘
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────────┐
│              serve.py — FastAPI :8000                       │
│  33 route modules · CORS · JWT auth · Alembic migrations   │
├────────────────────────────────────────────────────────────┤
│                     SERVICE LAYER                          │
│  ChatService · AuthService · OllamaService · IndexingService│
│  MetadataService · VectorService · CacheService · etc.     │
└──────┬──────────┬──────────┬──────────┬───────────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
   PostgreSQL   Redis     Qdrant    Ollama / LLM
   (metadata)   (cache)   (vectors)  (embeddings + chat)
```

### Infrastructure (docker-compose.yml)

| Service      | Image                | Port  | Purpose                           |
|-------------|----------------------|-------|-----------------------------------|
| **postgres** | `postgres:15-alpine` | 5432  | Metadata DB (users, schema, chat) |
| **redis**    | `redis:7-alpine`     | 6379  | SQL/result caching                |
| **qdrant**   | `qdrant/qdrant`      | 6333  | Vector search for schema matching |
| **ollama**   | `ollama/ollama`      | 11434 | Local LLM + embedding server      |

The application itself (`serve.py`) runs outside Docker during development.

---

## Repository Layout

```
Db-chat-App/
├── serve.py                 ← FastAPI entry point
├── app/
│   ├── config.py            ← Pydantic Settings (env-driven)
│   ├── database.py          ← SQLAlchemy engine + session factory
│   ├── models.py            ← 30 ORM models (643 lines)
│   ├── api/
│   │   ├── deps.py          ← Auth/permission dependencies
│   │   └── routes/          ← 33 route modules (~7,200 lines)
│   └── services/            ← Business logic (14 service files)
├── frontend/
│   ├── server.py            ← Static server + API proxy (:3000)
│   ├── index.html           ← SPA shell (1,486 lines)
│   ├── app.js               ← Core UI logic (2,851 lines)
│   └── features.js          ← Feature tabs (2,022 lines)
├── viz-service/
│   └── app.py               ← Chart recommendation microservice
├── alembic/                 ← DB migrations
├── docker-compose.yml       ← Infrastructure services
├── requirements.txt         ← Python dependencies
└── .env                     ← Environment config
```

---

## Key Concepts

### 1. Connection → Database → Table → Column

A **Connection** stores credentials for an external database. Indexing extracts
its **Databases**, **Tables**, and **Columns** into PostgreSQL metadata. This
metadata drives schema context given to the LLM during SQL generation.

### 2. Natural Language → SQL Pipeline

```
User Prompt
    │
    ▼
Intent Classification (catalog vs data)
    │
    ├── catalog → Inspector-based introspection
    │
    └── data →  Embed prompt → Vector search (Qdrant)
                    → LLM table reranking
                    → FK bridge expansion
                    → Schema context assembly
                    → LLM SQL generation
                    → Validation + repair loop
                    → Execute on user's DB
                    → LLM answer formatting
```

### 3. Permission Model

```
Global admin:    perms["*"] contains "db_onboard"
DB admin:        perms["<conn_id>"] contains "db_onboard"
DB reindexer:    perms["<conn_id>"] contains "db_reindex"  (implies prompt_query)
Query user:      perms["<conn_id>"] contains "prompt_query"
Table-level:     TableAccess rows restrict which tables a user can query
```

### 4. LLM Provider Routing

The app supports multiple LLM backends (Ollama local, OpenAI-compatible,
Anthropic) with per-task role routing. Roles: `general`, `sql_generate`,
`reasoning`, `explain`, `summarize`, `classify`, `nosql`, `suggest`.

---

## How to Read the Rest of This Guide

| Document | Covers |
|----------|--------|
| `02-DATA-MODEL.md` | All 30 ORM models and their relationships |
| `03-SERVICES.md` | Every service class and the logic flow |
| `04-API-ROUTES.md` | All 33 route files and every endpoint |
| `05-FRONTEND.md` | Browser code, UI structure, and data flow |
| `06-FLOWS.md` | End-to-end walkthroughs of critical user journeys |
