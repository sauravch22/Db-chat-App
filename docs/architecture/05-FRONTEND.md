# DbChat — Frontend Architecture

The frontend is a **single-page application** built with vanilla JavaScript,
Tailwind CSS (CDN), Chart.js, CodeMirror (SQL editor), and Mermaid (ERD
diagrams). No build step is required.

---

## File Inventory

| File | Lines | Role |
|------|------:|------|
| `frontend/index.html` | 1,486 | HTML structure, inline CSS, all modals |
| `frontend/app.js` | 2,851 | Core: auth, chat, dashboards, saved queries, admin, activity |
| `frontend/features.js` | 2,022 | Feature tabs: workbench, schema, ERD, quality, training, pipeline, etc. |
| `frontend/server.py` | 81 | Static file server + API reverse proxy |

---

## Page Structure (`index.html`)

```
┌──────────────────────────────────────────────────────────┐
│  #loginScreen (full-screen, shown when no JWT)           │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Sign In form / Sign Up form (toggle)              │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  #appShell (hidden until login)                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  HEADER: DB selector · user badge · logout         │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌──────────┬─────────────────────────────────────────┐  │
│  │ #sideNav │  #mainContent                           │  │
│  │          │  ┌───────────────────────────────────┐  │  │
│  │ Sidebar  │  │ #chatTab (default)                │  │  │
│  │ groups:  │  │ ┌──────────┬──────────────────┐   │  │  │
│  │          │  │ │ #thread  │  #chatArea        │   │  │  │
│  │ Core     │  │ │ Sidebar  │  Messages +       │   │  │  │
│  │ Analytics│  │ │          │  welcome panel    │   │  │  │
│  │ AI&Qual  │  │ └──────────┴──────────────────┘   │  │  │
│  │ Data Ops │  │ Footer: input + send button       │  │  │
│  │ Knowledge│  └───────────────────────────────────┘  │  │
│  │ Admin    │  ┌───────────────────────────────────┐  │  │
│  │          │  │ #adminTab / #dashboardTab / ...   │  │  │
│  │          │  │ (21 feature tabs, one visible)    │  │  │
│  │          │  └───────────────────────────────────┘  │  │
│  └──────────┴─────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘

Modals (overlay, end of body):
  #tableAccessModal · #saveQueryModal · #scheduleModal
  #writebackModal · #chartModal · #pinModal
  #createDashboardModal · #detailModal · #explainModal
  #userActivityModal
```

### Sidebar Navigation Groups

| Group | Tabs |
|-------|------|
| **Core** | Chat, Schema, Workbench, Saved Queries |
| **Analytics** | Dashboards, Activity, Lineage, Intelligence |
| **AI & Quality** | ERD, Quality, Optimizer, Training, Templates |
| **Data Ops** | File Upload, Pipeline, Cross-DB, API Generator, Migration, NoSQL |
| **Knowledge** | Knowledge Graph, Glossary, Embed |
| **Admin** | Admin panel (DB registration, users, LLM, reindex) |

---

## JavaScript Architecture

### Global State (`app.js`)

| Variable | Type | Purpose |
|----------|------|---------|
| `authToken` | string | JWT stored in `localStorage` |
| `currentUser` | object | `{username, perms}` from login response |
| `selectedConnId` | number | Currently selected database connection |
| `currentThreadId` | string | Active chat thread UUID |
| `isProcessing` | boolean | Prevents duplicate sends |
| `lastResponseRows/Cols` | array | Last query result for export |
| `currentDashboardId` | number | Open dashboard |
| `dashboardPinCharts` | object | Chart.js instances by pin ID |
| `dashboardPinData` | object | Pin result data by pin ID |
| `pinContext` | object | Chart config being pinned |
| `saveQueryContext` | object | SQL being saved |
| `welcomeCache` | object | Cached welcome data per connection |

### Communication Pattern

```
Browser ──HTTP──▶ frontend/server.py:3000
                     │
                     ├── /           → index.html
                     ├── /app.js     → static file
                     └── /api/*      → proxy to serve.py:8000
```

All API calls go through `authFetch()`:
```javascript
async function authFetch(url, opts = {}) {
    opts.headers = { ...opts.headers, ...authHeaders() };
    const r = await fetch(url, opts);
    if (r.status === 401) { doLogout(); throw new Error('Session expired'); }
    return r;
}
```

### Key Functions (`app.js`)

**Auth Flow:**
- `doLogin()` → POST `/api/auth/login` → store JWT → `showApp()`
- `doSignup()` → POST `/api/auth/signup` → auto-login
- `showApp()` → `loadDatabases()` → render sidebar → `loadWelcome()`

**Chat Flow:**
- `sendMessage()` → tries `_sendViaSSE()`, falls back to `_sendViaRegular()`
- `_sendViaSSE()` → `POST /api/chat/stream` → processes SSE events
- `_handleSSEEvent()` → accumulates status/sql/data/answer/summary
- `addBotReply()` → renders table, export buttons, chart chips, explain button
- `buildTable()` → paginated HTML table with sort

**Thread Management:**
- `loadThreads()` → GET `/api/chat/threads` → sidebar list
- `selectThread()` → `loadChatHistory()` → re-render messages
- `startNewThread()` → clears state for new conversation

**Dashboard Flow:**
- `loadDashboardsList()` → GET `/api/dashboards`
- `openDashboard()` → GET `/api/dashboards/{id}` → render pins
- `refreshCurrentDashboard()` → POST `/api/dashboards/{id}/refresh` → re-render charts
- `submitPin()` → POST `/api/dashboards/{id}/pins`

**Admin Flow:**
- `submitRegisterDb()` → POST `/api/admin/register-db`
- `loadAdminUsersForDb()` → GET `/api/auth/users/db/{id}` → render user grid
- `togglePerm()` → PUT `/api/auth/users/{id}/db-permissions`
- `saveTableAccess()` → PUT `/api/auth/table-access`

### Key Functions (`features.js`)

**Schema Explorer:**
- `loadSchemaExplorer()` → GET `/api/schema/explorer/{id}` → tree view
- `askAboutTable()` → inserts NL question about a table

**Workbench:**
- `renderWorkbench()` → multi-pane SQL editor with CodeMirror
- `executeWorkbench()` → POST `/api/workbench/execute`
- `diffWorkbench()` → POST `/api/workbench/diff`

**ERD:**
- `loadErd()` → GET `/api/erd/{id}` → Mermaid render

**Training:**
- `loadTrainingPairs()` → GET `/api/training?connection_id=X`
- `addTrainingPair()` → POST `/api/training`

**Quality & Optimizer:**
- `runQualityScan()` → POST `/api/quality/scan`
- `runOptimizer()` → POST `/api/optimizer/analyze`

**Pipeline:**
- `executePipeline()` → POST `/api/pipeline/execute`
- `previewPipeline()` → GET `/api/pipeline/preview`

**Knowledge & Glossary:**
- `loadConcepts()` / `createConcept()` → `/api/knowledge/concepts`
- `loadGlossaryTerms()` / `createGlossaryTerm()` → `/api/knowledge/glossary`
- `fingerprintConnection()` → POST `/api/knowledge/fingerprint/{id}`
- `discoverMatches()` → GET `/api/knowledge/discover`

---

## Chart System

```
User asks question → ChatService returns rows
    │
    ▼
fetchChartChips(columns, rows, prompt, sql)
    │
    POST to viz-service:8001/analyze
    │
    ▼
Viz service returns recommendations:
    [{chart_type: "bar", x_axis: "month", y_axis: "revenue", title: "..."}]
    │
    ▼
Render chip buttons: "📊 Bar: Revenue by Month"
    │
    click → openChartModal() → Chart.js render
              │
              click "📌 Pin" → openPinModal()
                                  │
                                  submitPin() → POST /api/dashboards/{id}/pins
```

---

## Modal System

All modals follow the same pattern:

```html
<div id="fooModal" class="modal-overlay" role="dialog" aria-modal="true"
     onclick="if(event.target===this)closeFoo()">
  <div class="modal-box">
    <div class="modal-header">
      <h3>Title</h3>
      <button class="modal-close" aria-label="Close" onclick="closeFoo()">✕</button>
    </div>
    <div class="modal-body">...</div>
  </div>
</div>
```

Opening: `document.getElementById('fooModal').classList.add('open')`
Closing: `document.getElementById('fooModal').classList.remove('open')`
Escape key: global listener finds `.modal-overlay.open` and clicks its close button.

---

## Viz Microservice (`viz-service/app.py` — 435 lines)

Separate FastAPI app on port 8001 that recommends chart types.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Service info |
| `/health` | GET | Health check |
| `/analyze` | POST | Accepts columns + rows (or URL), returns chart recommendations |

### Recommendation Logic (`generate_lux_recommendations`)

1. Classify columns: ID columns, measures (numeric), labels (categorical)
2. Generate recommendations based on column types:
   - 1 measure → single-value card
   - 1 label + 1 measure → bar/pie chart
   - Date/time + measure → line/area chart
   - 2 measures → scatter plot
   - Multiple measures → grouped bar
3. Return up to `max_recommendations` results with chart config
