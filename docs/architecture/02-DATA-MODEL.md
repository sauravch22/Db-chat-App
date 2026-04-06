# DbChat — Data Model

All models live in `app/models.py` (643 lines) and use SQLAlchemy 2.x
declarative base. The metadata database is PostgreSQL.

---

## Entity-Relationship Diagram (simplified)

```
Connection ──1:N──▶ Database ──1:N──▶ Table ──1:N──▶ Column
                         │                    │
                         │                    └──1:N──▶ Sample
                         │
                         └──1:N──▶ ForeignKeyModel

User ──1:N──▶ UserPermission ──(optional)──▶ Connection
  │
  ├──1:N──▶ TableAccess ──▶ Connection
  ├──1:N──▶ ChatHistory ──▶ Connection
  ├──1:N──▶ Dashboard ──1:N──▶ DashboardPin ──▶ Connection
  ├──1:N──▶ SavedQuery ──▶ Connection
  │              │
  │              ├──1:N──▶ QueryAnnotation
  │              ├──1:N──▶ ScheduledQuery
  │              └──1:N──▶ GeneratedEndpoint
  │
  ├──1:N──▶ TrainingPair ──▶ Connection
  ├──1:N──▶ WriteBackRequest ──▶ Connection
  ├──1:N──▶ QueryCorrection ──▶ Connection
  └──1:N──▶ ActivityLog ──▶ Connection (optional)

EntityConcept ──1:N──▶ EntityMapping ──▶ Connection
GlossaryTerm
ColumnFingerprint ──▶ Connection
ColumnAnnotation ──▶ Connection
QueryTemplate (optional User)
```

---

## Model Reference

### Schema Metadata (populated during indexing)

| Model | Table | Key Fields | Purpose |
|-------|-------|------------|---------|
| **Connection** | `connections` | `name`, `host`, `port`, `username`, `password`, `database_name`, `database_type`, `is_active` | External DB connection credentials. Password stored as plaintext (encrypted at rest by the DB). |
| **Database** | `databases` | FK `connection_id`, `name`, `database_type` | One logical database per connection. A connection can have multiple databases. |
| **Table** | `tables` | FK `database_id`, `name`, `row_count`, `context` (AI-generated summary), `sample_values` (JSON) | Indexed table metadata. `context` is used in LLM prompts. |
| **Column** | `columns` | FK `table_id`, `name`, `data_type`, `is_primary_key`, `is_nullable`, `sample_values` | Column metadata. `sample_values` stores distinct categorical values for embedding. |
| **Sample** | `samples` | FK `table_id`, `data` (JSON) | Raw sample rows for a table. |
| **ForeignKeyModel** | `foreign_keys` | FK `database_id`, `table_name`, `column_name`, `ref_table`, `ref_column`, `constraint_name` | Extracted FK relationships. Used for join-path discovery and ERD generation. |
| **DataEmbeddingRefreshLog** | `data_embedding_refresh_log` | FKs to `connection`, `table`, `column`, timestamps | Tracks when value-level embeddings were last refreshed. |

### Authentication & Authorization

| Model | Table | Key Fields | Purpose |
|-------|-------|------------|---------|
| **User** | `users` | `username`, `hashed_password`, `is_active` | Application user. Passwords are bcrypt-hashed. |
| **UserPermission** | `user_permissions` | FK `user_id`, optional FK `connection_id`, `permission` | Permission grant. `connection_id=NULL` means global. Valid values: `db_onboard`, `db_reindex`, `prompt_query`. |
| **TableAccess** | `table_access` | FK `user_id`, FK `connection_id`, `table_name`, FK `created_by` | Optional allowlist restricting which tables a user can query. If no rows exist for a user+connection, all tables are accessible. |

### Chat & History

| Model | Table | Key Fields | Purpose |
|-------|-------|------------|---------|
| **ChatHistory** | `chat_history` | FK `user_id`, FK `connection_id`, `thread_id` (UUID), `prompt`, `sql`, `answer`, `status`, `row_count`, `tables_used` (JSON), `execution_time_ms`, `reasoning` | One row per chat turn. Grouped by `thread_id` for conversation threading. |
| **Query** | `queries` | FK `connection_id`, `query_text`, `status`, `error_message`, `execution_time`, `rows_returned` | Audit log of raw SQL executions. |

### Dashboards & Pins

| Model | Table | Key Fields | Purpose |
|-------|-------|------------|---------|
| **Dashboard** | `dashboards` | FK `user_id`, `name`, `description`, `is_default` | User-created dashboard container. |
| **DashboardPin** | `dashboard_pins` | FK `dashboard_id`, FK `connection_id`, `name`, `pin_type` (`table`/`chart`), `chart_type`, `sql`, `chart_config` (JSON), `position` | A pinned chart or table on a dashboard. SQL is re-executed on refresh. |

### Saved Queries & Scheduling

| Model | Table | Key Fields | Purpose |
|-------|-------|------------|---------|
| **SavedQuery** | `saved_queries` | FK `user_id`, FK `connection_id`, `name`, `sql`, `description`, `folder`, `is_favorite`, `tags` (JSON), `use_count` | Bookmarked SQL query. |
| **ScheduledQuery** | `scheduled_queries` | FK `saved_query_id`, FK `connection_id`, FK `user_id`, `cron_expression`, `is_active`, `alert_condition`, `alert_threshold`, `alert_email`, `last_run_*` | Cron-triggered execution of a saved query with optional alerting. |
| **QueryAnnotation** | `query_annotations` | FK `user_id`, FK `connection_id`, optional FK `chat_history_id`, optional FK `saved_query_id`, `sql`, `note`, `tags` (JSON), `is_shared` | Notes/tags attached to queries. |

### Write-Back & Templates

| Model | Table | Key Fields | Purpose |
|-------|-------|------------|---------|
| **WriteBackRequest** | `writeback_requests` | FK `user_id`, FK `connection_id`, `sql`, `description`, `status` (`pending`/`approved`/`rejected`/`executed`), FK `approved_by` | Approval workflow for DML (INSERT/UPDATE/DELETE) operations. |
| **QueryTemplate** | `query_templates` | `name`, `description`, `sql_template`, `category`, `database_type`, `variables` (JSON), `use_count`, FK `created_by` | Parameterized SQL templates with `{{variable}}` placeholders. |

### Training & RAG

| Model | Table | Key Fields | Purpose |
|-------|-------|------------|---------|
| **TrainingPair** | `training_pairs` | FK `user_id`, FK `connection_id`, `question`, `query`, `query_type`, `is_verified`, `upvotes` | Question→SQL pairs used as few-shot examples during SQL generation. |

### API Generation

| Model | Table | Key Fields | Purpose |
|-------|-------|------------|---------|
| **GeneratedEndpoint** | `generated_endpoints` | FK `user_id`, FK `saved_query_id`, FK `connection_id`, `path_slug`, `api_key`, `is_active`, `call_count` | Exposes a saved query as a REST API endpoint, accessible via API key. |

### Knowledge Graph & Semantic Layer

| Model | Table | Key Fields | Purpose |
|-------|-------|------------|---------|
| **EntityConcept** | `entity_concepts` | `name`, `description`, `category`, FK `created_by` | A canonical business entity (e.g., "Customer ID"). |
| **EntityMapping** | `entity_mappings` | FK `concept_id`, FK `connection_id`, `table_name`, `column_name`, `confidence`, `source`, FK `verified_by` | Links a concept to a physical column in a specific database. |
| **ColumnFingerprint** | `column_fingerprints` | FK `connection_id`, `table_name`, `column_name`, `data_type`, `distinct_count`, `null_ratio`, `avg_length`, `sample_values` (JSON), `pattern_class`, `fingerprint_hash` | Statistical profile for auto-discovery of matching columns across databases. |
| **GlossaryTerm** | `glossary_terms` | `term`, `definition`, `category`, `sql_expression`, `synonyms`, `upvotes`, FK `created_by` | Business glossary injected into LLM context. |
| **ColumnAnnotation** | `column_annotations` | FK `connection_id`, `table_name`, `column_name`, `annotation`, FK `annotated_by` | Free-text column notes injected into schema context. |
| **QueryCorrection** | `query_corrections` | FK `user_id`, FK `connection_id`, `original_prompt`, `original_sql`, `correction_text`, `corrected_sql` | Learning examples: when a user corrects a generated query. |

### Activity & Monitoring

| Model | Table | Key Fields | Purpose |
|-------|-------|------------|---------|
| **ActivityLog** | `activity_logs` | FK `user_id`, FK `connection_id`, `action`, `resource_type`, `resource_id`, `status`, `detail` (JSON), `ip_address`, `user_agent`, `duration_ms` | Full audit trail of every significant action. |
