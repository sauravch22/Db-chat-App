# DbChat — API Routes

33 route modules registered in `serve.py`. All routes require JWT
`Authorization: Bearer <token>` unless noted otherwise.

---

## Quick Reference (all endpoints)

### Core Chat (`/api/chat` — chat.py, 767 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/chat` | `prompt_query` | NL → SQL → execute → answer |
| POST | `/api/chat/stream` | `prompt_query` | Same as above via SSE stream |
| POST | `/api/chat/execute` | `prompt_query` | Run raw SQL |
| POST | `/api/chat/explain` | `prompt_query` | LLM explanation of SQL |
| GET | `/api/chat/history` | user | Chat history (optional thread filter) |
| GET | `/api/chat/history/search` | user | Full-text search across history |
| DELETE | `/api/chat/history` | user | Clear history |
| GET | `/api/chat/threads` | user | List conversation threads |
| PUT | `/api/chat/threads/{id}/title` | user | Rename thread |
| DELETE | `/api/chat/threads/{id}` | user | Delete thread |
| GET | `/api/chat/welcome` | user | AI welcome summary for a DB |

### Authentication (`/api/auth` — auth.py, 413 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/auth/login` | public | Login → JWT |
| POST | `/api/auth/signup` | public | Self-registration |
| GET | `/api/auth/me` | user | Profile + permissions |
| GET | `/api/auth/users` | global admin | List all users |
| GET | `/api/auth/users/db/{conn_id}` | DB admin | Users for a DB |
| PUT | `/api/auth/users/{uid}/db-permissions` | DB admin | Set user DB perms |
| GET | `/api/auth/permissions` | public | Available permission types |
| GET | `/api/auth/table-access/{conn_id}/{uid}` | DB admin | User's table allowlist |
| PUT | `/api/auth/table-access` | DB admin | Set table allowlist |
| GET | `/api/auth/table-access/available/{conn_id}` | DB admin | Indexed tables for picker |

### Administration (`/api/admin` — admin.py, 626 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/admin/register-db` | `db_onboard` | Register new DB connection + background index |
| GET | `/api/admin/databases` | user | List accessible databases |
| POST | `/api/admin/reindex/{conn_id}` | `db_reindex` | Trigger schema re-index |
| GET | `/api/admin/audit` | `prompt_query` | SQL audit log |
| GET | `/api/admin/summaries/{conn_id}` | `prompt_query` | Table summaries |
| PUT | `/api/admin/summaries/{table_id}` | `db_reindex` | Edit table summary |
| POST | `/api/admin/refresh-data-embeddings/{conn_id}` | `db_reindex` | Refresh value embeddings |

### Activity Log (`/api/activity` — activity.py, 396 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/activity/me` | user | My activity log |
| GET | `/api/activity/me/stats` | user | My aggregated stats |
| GET | `/api/activity/user/{uid}` | global admin | Another user's log |
| GET | `/api/activity/user/{uid}/stats` | global admin | Another user's stats |
| GET | `/api/activity/db/{conn_id}` | DB admin | Activity for one DB |
| GET | `/api/activity/global` | global admin | Full org-wide log |
| GET | `/api/activity/stats` | admin/user | Aggregated stats |
| GET | `/api/activity/actions` | public | Action type enum for filters |

### Dashboards (`/api/dashboards` — dashboard.py, 421 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/dashboards` | user | Create dashboard |
| GET | `/api/dashboards` | user | List my dashboards |
| GET | `/api/dashboards/{id}` | user | Dashboard detail + pins |
| PUT | `/api/dashboards/{id}` | user | Update dashboard |
| DELETE | `/api/dashboards/{id}` | user | Delete dashboard |
| POST | `/api/dashboards/{id}/pins` | user | Add pin |
| PUT | `/api/dashboards/pins/{pin_id}` | user | Update pin |
| DELETE | `/api/dashboards/pins/{pin_id}` | user | Delete pin |
| POST | `/api/dashboards/{id}/refresh` | user | Re-run all pins' SQL |

### Saved Queries (`/api/saved-queries` — saved_queries.py, 252 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/saved-queries` | `prompt_query` | Save a query |
| GET | `/api/saved-queries` | user | List saved queries |
| GET | `/api/saved-queries/folders` | user | Folder names |
| PUT | `/api/saved-queries/{id}` | user | Update metadata |
| DELETE | `/api/saved-queries/{id}` | user | Delete |
| POST | `/api/saved-queries/{id}/run` | user | Execute with pagination |
| POST | `/api/saved-queries/{id}/toggle-favorite` | user | Toggle favorite |

### Schema Explorer (`/api/schema` — schema_explorer.py, 155 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/schema/explorer/{conn_id}` | `prompt_query` | Full indexed schema + FKs |
| GET | `/api/schema/table/{table_id}` | user | Single table detail + FK edges |

### Workbench (`/api/workbench` — workbench.py, 186 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/workbench/execute` | `prompt_query` | Run up to 10 SQL queries |
| POST | `/api/workbench/diff` | `prompt_query` | Diff two result sets |

### Write-Back (`/api/writeback` — writeback.py, 213 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/writeback` | `prompt_query` | Submit DML for approval |
| GET | `/api/writeback` | user | List requests |
| POST | `/api/writeback/{id}/approve` | `db_reindex` | Approve |
| POST | `/api/writeback/{id}/reject` | `db_reindex` | Reject |
| POST | `/api/writeback/{id}/execute` | `db_reindex` | Execute approved DML |

### Training / RAG (`/api/training` — training.py, 153 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/training` | `prompt_query` | Add question→SQL pair |
| GET | `/api/training` | `prompt_query` | List pairs for connection |
| POST | `/api/training/{id}/upvote` | user | Upvote pair |
| DELETE | `/api/training/{id}` | user (own) | Delete own pair |
| GET | `/api/training/context/{conn_id}` | `prompt_query` | RAG context text |
| POST | `/api/training/auto-save` | `prompt_query` | Auto-save from chat |

### Knowledge Graph (`/api/knowledge` — knowledge_graph.py, 453 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET/POST | `/api/knowledge/concepts` | user | List/create entity concepts |
| GET/DELETE | `/api/knowledge/concepts/{id}` | user | Get/delete concept |
| POST | `/api/knowledge/mappings` | user | Map concept to column |
| DELETE | `/api/knowledge/mappings/{id}` | user | Remove mapping |
| POST | `/api/knowledge/fingerprint/{conn_id}` | DB admin | Run column fingerprinting |
| GET | `/api/knowledge/fingerprints/{conn_id}` | user | List fingerprints |
| GET | `/api/knowledge/discover` | user | Auto entity match suggestions |
| POST | `/api/knowledge/discover/accept` | user | Accept discovery |
| GET/POST | `/api/knowledge/glossary` | user | List/create glossary terms |
| PUT | `/api/knowledge/glossary/{id}` | user | Update term |
| POST | `/api/knowledge/glossary/{id}/upvote` | user | Upvote |
| DELETE | `/api/knowledge/glossary/{id}` | user | Delete term |
| GET/POST | `/api/knowledge/annotations` | user | Column annotations |
| DELETE | `/api/knowledge/annotations/{id}` | user | Delete annotation |
| POST | `/api/knowledge/corrections` | user | Store query correction |
| GET | `/api/knowledge/corrections/{conn_id}` | user | List corrections |
| GET | `/api/knowledge/context/{conn_id}` | user | Combined knowledge context |

### ERD (`/api/erd` — erd.py, 56 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/erd/{conn_id}` | `prompt_query` | Mermaid erDiagram string |

### Query Optimizer (`/api/optimizer` — optimizer.py, 122 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/optimizer/analyze` | `prompt_query` | EXPLAIN + LLM suggestions |

### Data Quality (`/api/quality` — data_quality.py, 149 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/quality/scan` | user | Per-column null/distinct stats |
| GET | `/api/quality/score/{conn_id}` | user | Per-table quality scores |

### Scheduled Queries (`/api/scheduled` — scheduled.py, 276 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/scheduled` | user | Create schedule from saved query |
| GET | `/api/scheduled` | user | List schedules |
| PUT | `/api/scheduled/{id}` | user | Update schedule |
| DELETE | `/api/scheduled/{id}` | user | Delete schedule |
| POST | `/api/scheduled/{id}/run` | user | Manual run + alert check |
| GET | `/api/scheduled/presets` | user | Built-in cron presets |

### Annotations (`/api/annotations` — annotations.py, 154 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/annotations` | user | Create annotation on query |
| GET | `/api/annotations` | user | List annotations |
| PUT | `/api/annotations/{id}` | user | Update annotation |
| DELETE | `/api/annotations/{id}` | user | Delete annotation |

### Suggestions (`/api/suggestions` — suggestions.py, 129 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/suggestions` | user | Follow-up queries + related tables |

### Summarize (`/api/summarize` — summarize.py, 36 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/summarize` | user | AI summary of result data |

### Templates (`/api/templates` — templates.py, 270 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/templates` | user | List templates (seeds builtins) |
| GET | `/api/templates/categories` | user | Template categories |
| POST | `/api/templates/render` | user | Render template with variables |
| POST | `/api/templates/create` | user | Create custom template |
| DELETE | `/api/templates/{id}` | user | Delete template |

### Cross-Database (`/api/crossdb` — cross_db.py, 158 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/crossdb/connections` | user | Accessible connections |
| POST | `/api/crossdb/query` | `prompt_query` | Same SQL on multiple DBs |
| GET | `/api/crossdb/db-types` | user | Supported DB types |

### NoSQL (`/api/nosql` — nosql.py, 126 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/nosql/types` | user | Supported NoSQL types |
| GET | `/api/nosql/schema/{conn_id}` | `prompt_query` | NoSQL schema extraction |
| POST | `/api/nosql/execute` | `prompt_query` | Run NoSQL query |

### File Upload (`/api/files` — file_upload.py, 131 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/files/upload` | user | Upload CSV/Excel/Parquet/JSON → DuckDB |
| GET | `/api/files/tables` | user | List uploaded tables |
| POST | `/api/files/query` | user | SQL against DuckDB |
| DELETE | `/api/files/table/{name}` | user | Drop uploaded table |

### Lineage (`/api/lineage` — lineage.py, 216 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/lineage/{conn_id}` | `prompt_query` | FK deps + co-occurrence + usage stats |
| GET | `/api/lineage/impact/{conn_id}/{table}` | `prompt_query` | Impact score for a table |

### Intelligence (`/api/intelligence` — intelligence.py, 244 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/intelligence/{conn_id}` | `prompt_query` | DB stats + live PG queries + index recs |

### LLM Settings (`/api/llm` — llm_settings.py, 163 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/llm/providers` | user | Provider list + active config |
| POST | `/api/llm/provider` | global admin | Change default provider |
| GET | `/api/llm/health` | user | Provider health |
| GET | `/api/llm/model-routing` | user | Per-role routing config |
| POST | `/api/llm/model-routing` | global admin | Set role provider |
| DELETE | `/api/llm/model-routing` | global admin | Clear role override |
| GET | `/api/llm/model-routing/health/{role}` | user | Role-specific health |

### API Generator (`/api/endpoints` — api_generator.py, 151 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/endpoints/generate` | user (own query) | Create REST endpoint from saved query |
| GET | `/api/endpoints` | user | List generated endpoints |
| DELETE | `/api/endpoints/{id}` | user (own) | Delete endpoint |
| GET | `/api/endpoints/v1/{slug}` | **API key** | Public execution of saved query |

### Migration (`/api/migration` — migration.py, 107 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/migration/generate` | DB admin | NL → DDL; optional execute |

### Pipeline (`/api/pipeline` — pipeline.py, 121 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/pipeline/execute` | DB admin (both) | ETL: source SQL → target table |
| GET | `/api/pipeline/preview` | DB admin | Preview source query |

### Collaboration (`/api/collab` — collab.py, 152 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/collab/session` | user | Create collab session |
| GET | `/api/collab/session/{id}` | user | Session metadata |
| WS | `/api/collab/ws/{id}` | JWT in query | Real-time SQL/cursor sync |

### Embed Widget (`/api/embed` — embed.py, 173 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/embed/create` | `prompt_query` | Generate embed token |
| GET | `/api/embed/tokens` | user | List tokens |
| GET | `/api/embed/widget.js` | public | JS loader |
| GET | `/api/embed/frame` | embed token | Iframe HTML |
| POST | `/api/embed/query` | embed token | Execute via widget |

### Connection Test (`/api/connection` — connection_test.py, 85 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/connection/test` | `db_onboard` | Test connectivity (SSRF-protected) |

### Query Validation (`/api/validate` — query_validation.py, 132 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/validate/query` | user | Static SQL safety checks + EXPLAIN |

### Health (`/api/health` — health.py, 24 lines)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/health` | public | Liveness |
| GET | `/api/health/ready` | public | Readiness |
