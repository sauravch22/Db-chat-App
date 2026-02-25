# Onboarding Guide: Adding a Database to DbChat v2

## Quick Start (5 minutes)

### Step 1: Register Your Database

```bash
curl -X POST http://localhost:8000/api/admin/register-db \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-database",
    "host": "db.example.com",
    "port": 5432,
    "username": "user",
    "password": "secret",
    "database": "mydb",
    "database_type": "postgres"
  }'
```

**Response**:
```json
{
  "id": 3,
  "name": "my-database",
  "status": "registered",
  "indexing_scheduled": true
}
```

### Step 2: Wait for Indexing (30-60 seconds)

The system automatically:
1. ✅ Extracts schema (tables, columns, types)
2. ✅ Generates table summaries
3. ✅ Samples categorical data values
4. ✅ Creates vector embeddings
5. ✅ Indexes everything for fast lookup

**Check status** (optional):
```bash
curl http://localhost:8000/api/admin/connections | jq '.[] | select(.id == 3)'
```

Look for: `"last_indexed_at"` is not null

### Step 3: Start Chatting

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 3,
    "prompt": "How many customers do we have?"
  }'
```

---

## What Happens During Onboarding

### Phase 1: Schema Discovery (1-5 seconds)
- Connects to your database
- Lists all tables, columns, types, constraints
- Detects relationships (primary keys, foreign keys)

### Phase 2: Intelligent Summaries (2-5 seconds)
The system reads column names and types to create natural language descriptions:
- ✅ "genre: Categories of music (Rock, Jazz, Classical, etc.)"
- ✅ "invoice: Customer purchase records with dates and amounts"
- ✅ "customer: User profiles with contact information"

These summaries help the LLM pick the right tables for your questions.

### Phase 3: Data Sampling (2-5 seconds)
For categorical columns (VARCHAR, ENUM, TEXT), the system:
- Reads up to 50 distinct values
- Stores examples: `["Rock", "Jazz", "Classical", "Pop"]`
- Uses them to suggest realistic filters

**Example**: When you ask "Show me rock albums", the system knows "Rock" is a valid genre.

### Phase 4: Vector Embeddings (10-30 seconds)
The system converts all summaries and data samples into numerical vectors:
- Table descriptions → vector embeddings (fallback for table selection)
- Column metadata → vector embeddings (fallback for column selection)
- Data samples → vector embeddings (filter hint suggestions)

These vectors enable fast similarity search if the LLM needs help.

### Phase 5: Ready to Use (automatic)
Once complete, your database is ready for questions!

---

## Supported Databases

| Database | Version | Support | Notes |
|----------|---------|---------|-------|
| PostgreSQL | 12+ | ✅ Full | Recommended |
| MySQL | 8.0+ | ✅ Full | Works great |
| SQL Server | 2019+ | ✅ Partial | Most features |
| SQLite | 3.8+ | ⚠️ Limited | Local only |
| MariaDB | 10.5+ | ✅ Full | MySQL compatible |

---

## What Data is Stored

### Minimal Storage
DbChat stores **only metadata**, not your actual data:

| Data | Stored | Notes |
|------|--------|-------|
| Table/column names | ✅ Yes | Required for SQL generation |
| Data types | ✅ Yes | Required for validation |
| Sample values | ✅ Yes | Up to 50 per column, for filter hints |
| Your actual rows | ❌ No | Never touched |
| Passwords | ⚠️ Encrypted | Only used for schema access |

### Where it's Stored

**PostgreSQL Database** (your DbChat instance):
- Table schema: `app/models.py`
- Sizes: ~1 MB for typical database

**Qdrant Vector Store** (for fast search):
- Vector embeddings: ~80 MB for typical database
- Metadata: Column names, types, samples

---

## Monitoring Onboarding

### Check Indexing Status
```bash
# Get all connections with indexing status
curl http://localhost:8000/api/admin/connections | jq '.[] | {id, name, last_indexed_at}'

# Example output:
# {
#   "id": 3,
#   "name": "my-database",
#   "last_indexed_at": "2026-02-25T10:30:00"
# }
```

### View Extracted Schema
```bash
# Get details of a registered connection
curl http://localhost:8000/api/admin/connections/3 | jq .

# Get list of indexed tables (coming soon)
# GET /api/admin/connections/3/tables
```

### Check Vector Store
```bash
# Verify embeddings in Qdrant
curl http://localhost:6333/collections | jq '.result'
```

---

## Troubleshooting

### Problem: "Invalid credentials" error during onboarding

**Solution**: 
1. Verify username/password are correct
2. Ensure host/port are accessible from DbChat server
3. Check firewall rules (allow connection from your container)

```bash
# Test connectivity manually
nc -zv db.example.com 5432  # PostgreSQL
mysql -h db.example.com -u user -p  # MySQL
```

### Problem: Indexing hangs or times out

**Solution**:
1. Check database size (>100 GB may take longer)
2. Verify vector store (Qdrant) is running: `docker ps`
3. Check Ollama embeddings: `curl http://localhost:11434/api/tags`

```bash
# Restart vector store
docker restart qdrant

# Restart embedding server
docker restart ollama
```

### Problem: Table summaries are generic/poor quality

**Solution**:
The auto-generated summaries work, but you can improve them:

1. Add column comments to your database:
   ```sql
   ALTER TABLE genre COMMENT = 'Music categories: Rock, Jazz, Classical, etc.';
   COMMENT ON COLUMN invoice.total IS 'Invoice amount in USD, typically 0.99-307.55';
   ```

2. Re-index the database (coming soon):
   ```bash
   POST /api/admin/connections/3/reindex
   ```

### Problem: "No tables selected" for a query

**Solution**: 
The LLM couldn't find matching tables. Try:
1. Use more specific language: "artists" instead of "musicians"
2. Add database context: "In our Chinook music database, ..."
3. List options: "Show me genre, album, or artist counts"

---

## Advanced: Manual Schema Tuning

For best results, you can enhance the metadata after onboarding:

### Improve Table Summaries
```sql
UPDATE tables 
SET context = 'Invoice records for customer purchases. Fields: invoice_id (pk), customer_id (fk), invoice_date, total. Contains 412 invoices from 2009-2013, amount range 0.99-307.55'
WHERE name = 'invoice' AND database_id = 1;
```

### Add Column Samples
```sql
UPDATE columns 
SET sample_values = '["Rock", "Jazz", "Classical", "Pop", "Blues", "Latin", "Metal", "Alternative", "Reggae", "Hip-Hop"]'
WHERE name = 'name' AND table_id = (SELECT id FROM tables WHERE name = 'genre');
```

### Check Current Metadata
```sql
SELECT name, context FROM tables WHERE database_id = 1;
SELECT name, data_type, sample_values FROM columns WHERE table_id = 1;
```

---

## Performance Expectations

### Query Response Time
- **Fast** (5-15 seconds): Simple queries, well-indexed tables
  - Example: "How many artists?" 
  
- **Medium** (15-30 seconds): Multi-table joins, aggregations
  - Example: "Top 10 genres by revenue"
  
- **Slow** (30-60+ seconds): Complex queries, large datasets
  - Example: "Find customers who bought from multiple genres in different years"

### Factors Affecting Speed
- ✅ Good: Indexed columns, small tables, simple joins
- ❌ Bad: Full table scans, Cartesian products, 10+ table joins
- ❌ Bad: Ollama embedding time (5-10s baseline), LLM inference time

---

## Next Steps

1. ✅ Register your database (see Step 1 above)
2. ✅ Wait for onboarding to complete
3. ✅ Test with simple queries first
4. ⚙️ Tune summaries if needed (see Advanced section)
5. 🎯 Use for real analysis!

---

## Questions?

- **Setup issues**: Check [SETUP_COMPLETE.md](SETUP_COMPLETE.md)
- **Architecture details**: See [METADATA_DESIGN.md](METADATA_DESIGN.md)
- **API reference**: See [API_REFERENCE.md](API_REFERENCE.md)
- **Database changes**: See [ARCHITECTURE_V2.md](ARCHITECTURE_V2.md)
