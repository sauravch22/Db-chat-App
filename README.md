# DbChat - Natural Language Database Query Engine

Query databases using natural language. No SQL knowledge required.

## Architecture

```
┌─────────────────────────────────────────┐
│         FastAPI Application             │
│     (Python + Natural Language)         │
└────────────┬────────────────────────────┘
             │
   ┌─────────┼──────────┬─────────────┐
   ▼         ▼          ▼             ▼
┌──────┐ ┌──────┐  ┌────────┐  ┌──────────┐
│  DB  │ │Cache │  │ Vector │  │  LLM     │
│(PG) │ │Redis │  │ Qdrant │  │ Ollama   │
└──────┘ └──────┘  └────────┘  └──────────┘
```

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.10+

### 1. Start All Services

```bash
cd /Users/sauravchakraborty/DbChat
docker-compose up -d
```

This starts:
- **PostgreSQL** (Metadata DB) - Port 5432
- **Redis** (Cache) - Port 6379
- **Qdrant** (Vector DB) - Port 6333
- **Ollama** (LLM) - Port 11434

### 2. Pull Ollama Models

```bash
# Terminal into Ollama container
docker-compose exec ollama bash

# Download models
ollama pull mistral              # LLM (main model)
ollama pull nomic-embed-text     # Embedding model
```

Or in one command:
```bash
docker-compose exec ollama ollama pull mistral
docker-compose exec ollama ollama pull nomic-embed-text
```

### 3. Setup Python Environment

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Initialize Database

```bash
# Database is auto-initialized by Docker
# But you can verify:
psql -h localhost -U dbchat -d dbchat_metadata -c "\dt"
```

### 5. Run Application

```bash
# From project root
python main.py
```

Application runs on `http://localhost:8000`

## API Endpoints

### Health Checks

```bash
# Health check
curl http://localhost:8000/health

# Readiness check
curl http://localhost:8000/health/ready
```

### Chat API

```bash
# Natural language query
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": 1,
    "prompt": "What is the average order value from last month?"
  }'
```

### Admin API

```bash
# Register database
curl -X POST http://localhost:8000/api/admin/register-db \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production_db",
    "host": "db.example.com",
    "port": 3306,
    "username": "dbchat_user",
    "password": "password",
    "database_type": "mysql"
  }'

# List databases
curl http://localhost:8000/api/admin/databases

# Trigger reindex
curl -X POST http://localhost:8000/api/admin/reindex/1
```

## Project Structure

```
DbChat/
├── main.py                    # Application entry point
├── requirements.txt           # Python dependencies
├── docker-compose.yml         # Docker services config
├── init_db.sql               # Database initialization
├── .env                       # Environment variables
│
├── app/
│   ├── config.py             # Settings management
│   ├── database.py           # Database connection
│   ├── models.py             # SQLAlchemy models
│   │
│   ├── api/
│   │   └── routes/
│   │       ├── health.py     # Health endpoints
│   │       ├── chat.py       # Chat endpoints
│   │       └── admin.py      # Admin endpoints
│   │
│   └── services/
│       ├── ollama_service.py      # Ollama LLM
│       ├── vector_service.py      # Qdrant Vector DB
│       └── cache_service.py       # Redis Cache
```

## Development

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f ollama
docker-compose logs -f postgres
docker-compose logs -f qdrant
docker-compose logs -f redis
```

### Database Access

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U dbchat -d dbchat_metadata

# Check tables
\dt

# Exit
\q
```

### Ollama Management

```bash
# Check available models
docker-compose exec ollama ollama list

# Remove model
docker-compose exec ollama ollama rm mistral

# Check Ollama status
curl http://localhost:11434/api/tags
```

### Vector DB Access

```bash
# Qdrant Web UI
http://localhost:6333/dashboard

# List collections
curl http://localhost:6333/collections
```

## Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=app

# Watch mode
ptw
```

## Performance Tuning

### Connection Pooling
PostgreSQL uses HikariCP-like pooling:
- Pool size: 20
- Max overflow: 10

### Caching
Redis caching for:
- Vector search results (TTL: 24h)
- Schema metadata (TTL: 24h)
- Query results (TTL: 5 min)
- Embeddings (TTL: 30 days)

### Query Optimization
- Index on `created_at`, `connection_id`, etc.
- LIMIT on sample data (max 50 rows)
- Query timeout: 30 seconds

## Troubleshooting

### Docker Issues

```bash
# Rebuild containers
docker-compose down
docker-compose up -d

# Check health
docker-compose ps

# View logs
docker-compose logs [service_name]
```

### Connection Issues

```bash
# Test PostgreSQL
docker-compose exec postgres pg_isready

# Test Redis
docker-compose exec redis redis-cli ping

# Test Qdrant
curl http://localhost:6333/health

# Test Ollama
curl http://localhost:11434/api/tags
```

### Python Issues

```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall

# Check Python version
python --version

# Verify imports
python -c "import fastapi; print(fastapi.__version__)"
```

## Configuration

All settings in `.env`:

```env
# Database
DB_HOST=postgres
DB_PORT=5432
DB_NAME=dbchat_metadata
DB_USER=dbchat
DB_PASSWORD=dbchat_secure_password

# Redis
REDIS_URL=redis://redis:6379

# Qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=your_qdrant_api_key_here

# Ollama
OLLAMA_URL=http://ollama:11434
OLLAMA_LLM_MODEL=mistral
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# App
APP_ENV=development
DEBUG=true
API_PORT=8000
```

## Production Deployment

For production:
1. Update `.env` with production values
2. Use environment-specific configs
3. Enable SSL/TLS
4. Use managed databases (RDS, Managed PostgreSQL)
5. Deploy with Kubernetes or Docker Swarm
6. Set up monitoring (Prometheus, Grafana)

## Next Steps

- [ ] Implement chat service logic
- [ ] Add schema extraction from user databases
- [ ] Implement context builder for tables
- [ ] Add SQL generation with Ollama
- [ ] Add query validation
- [ ] Implement vector search
- [ ] Add query execution
- [ ] Add response formatting
- [ ] Add data visualization (Matplotlib)
- [ ] Add comprehensive tests

## License

MIT
