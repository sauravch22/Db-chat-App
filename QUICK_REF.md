# DbChat Development Quick Reference

## 🚀 Quick Start (Copy & Paste)

### Terminal 1: Start Services
```bash
cd /Users/sauravchakraborty/DbChat
docker-compose up -d
```

Wait for all services to be healthy (check with `docker-compose ps`)

### Terminal 2: Pull Models (one-time)
```bash
docker-compose exec ollama ollama pull mistral
docker-compose exec ollama ollama pull nomic-embed-text
```

### Terminal 3: Run App
```bash
cd /Users/sauravchakraborty/DbChat
source venv/bin/activate
python main.py
```

**Visit**: http://localhost:8000/docs for API documentation

---

## 🔍 Verification Checklist

After starting services:

```bash
# 1. Check all containers are running
docker-compose ps
# All should show "healthy" or "running"

# 2. Check PostgreSQL
curl http://localhost:5432 || docker-compose exec postgres pg_isready

# 3. Check Redis
docker-compose exec redis redis-cli ping
# Should return: PONG

# 4. Check Qdrant
curl http://localhost:6333/health

# 5. Check Ollama
curl http://localhost:11434/api/tags
# Should show: "models": ["mistral", "nomic-embed-text"]

# 6. Check FastAPI
curl http://localhost:8000/health
# Should return: {"status": "healthy", ...}
```

---

## 📝 Common Development Tasks

### View Service Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f ollama
docker-compose logs -f postgres
docker-compose logs -f redis
docker-compose logs -f qdrant

# Last N lines
docker-compose logs --tail=50
```

### Database Operations

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U dbchat -d dbchat_metadata

# Inside psql:
\dt                    # List tables
\d [table_name]        # Show table schema
SELECT * FROM connections;  # Query
\q                     # Exit

# Direct query
docker-compose exec postgres psql -U dbchat -d dbchat_metadata \
  -c "SELECT COUNT(*) FROM connections;"
```

### Redis Operations

```bash
# Connect to Redis CLI
docker-compose exec redis redis-cli

# Inside redis-cli:
ping                   # Test connection
keys *                 # List all keys
get [key]             # Get value
del [key]             # Delete key
flushall              # Clear all cache
quit                  # Exit
```

### Qdrant Operations

```bash
# List collections
curl http://localhost:6333/collections

# Get collection info
curl http://localhost:6333/collections/dbchat_embeddings

# Delete collection
curl -X DELETE http://localhost:6333/collections/dbchat_embeddings

# Web UI
# Open: http://localhost:6333/dashboard
```

### Ollama Operations

```bash
# List installed models
docker-compose exec ollama ollama list

# Pull a model
docker-compose exec ollama ollama pull [model_name]

# Remove a model
docker-compose exec ollama ollama rm [model_name]

# Run a model directly
docker-compose exec ollama ollama run mistral "What is 2+2?"

# Check Ollama status
curl http://localhost:11434/api/tags
```

### Python/FastAPI

```bash
# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
pip install -r requirements.txt

# Run application
python main.py

# Run with auto-reload
python main.py --reload

# Access API docs
# http://localhost:8000/docs        (Swagger UI)
# http://localhost:8000/redoc       (ReDoc)
```

### Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_chat.py

# Run with coverage
pytest --cov=app

# Verbose output
pytest -v

# Watch mode (auto-rerun on changes)
ptw
```

---

## 🛠️ Troubleshooting

### Docker Issues

```bash
# Container won't start
docker-compose logs [service]    # Check logs
docker-compose restart [service] # Restart

# Port already in use
lsof -i :[port]                  # Find process
kill -9 [PID]                    # Kill process

# Everything broken
docker-compose down -v           # Remove everything
docker-compose up -d             # Rebuild
```

### Database Issues

```bash
# Can't connect to PostgreSQL
docker-compose exec postgres pg_isready

# Reset database
docker-compose down -v
# Data in volumes will be deleted

# Migrations issue
docker-compose exec postgres psql -U dbchat -d dbchat_metadata \
  -c "DROP TABLE IF EXISTS [table]; CREATE TABLE ..."
```

### Python Issues

```bash
# Import errors
pip install -r requirements.txt --force-reinstall

# Check Python version
python --version  # Should be 3.10+

# Virtual env not activating
source venv/bin/activate
python -m pip install --upgrade pip

# Module not found
python -c "import [module]; print([module].__file__)"
```

### Ollama Issues

```bash
# Models not downloading
docker-compose logs ollama       # Check logs
docker-compose exec ollama ollama list  # Check what's installed

# Slow inference
# Models need GPU. CPU inference is slow.
# Reduce model size or use GPU acceleration

# Out of memory
# mistral = 4GB
# nomic-embed-text = 274MB
# Check system resources: docker stats
```

---

## 📊 Service Monitoring

### Health Endpoints

```bash
# App health
curl http://localhost:8000/health

# Detailed health check
curl http://localhost:8000/health/ready

# PostgreSQL
curl http://localhost:5432/  # (will error but shows it's running)

# Redis
docker-compose exec redis redis-cli ping

# Qdrant
curl http://localhost:6333/health

# Ollama
curl http://localhost:11434/api/tags
```

### Resource Usage

```bash
# View container stats
docker stats

# View specific container
docker stats [container_name]

# Check disk usage
df -h

# Check memory
free -h

# Check processes
top
```

---

## 🔐 Security Reminders

```python
# ✅ Always use:
PreparedStatement     # SQL queries (not string concat)
HTTPS                 # In production
Environment vars      # For secrets (not hardcoded)
Input validation      # Always sanitize
Audit logging         # Track all queries

# ❌ Never:
String concatenation  # SELECT * FROM table WHERE id = " + id
Store passwords       # In plaintext
Commit .env           # With real credentials
Allow DELETE/DROP     # In generated SQL
Skip validation       # Of user input
```

---

## 📚 Project Structure

```
/Users/sauravchakraborty/DbChat/
├── main.py                          # FastAPI app
├── requirements.txt
├── docker-compose.yml
├── init_db.sql
├── .env
├── README.md                        # Full documentation
├── STARTUP.md                       # Setup instructions
├── SETUP_COMPLETE.md               # What was created
├── QUICK_REF.md                    # This file
│
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── health.py
│   │       ├── chat.py
│   │       └── admin.py
│   │
│   └── services/
│       ├── __init__.py
│       ├── ollama_service.py
│       ├── vector_service.py
│       └── cache_service.py
│
├── tests/                           # (To be created)
└── venv/                            # Virtual environment
```

---

## 🎯 Common Workflows

### Add a New API Endpoint

1. Create route in `app/api/routes/[feature].py`
2. Import in `main.py`
3. Add router: `app.include_router(feature.router)`
4. Test at http://localhost:8000/docs

### Add a New Service

1. Create file in `app/services/[service].py`
2. Implement service class
3. Import where needed: `from app.services import [service]`

### Add Database Migration

1. Modify schema in `app/models.py`
2. For changes: `docker-compose down -v`
3. Restart with `docker-compose up -d`

### Cache a Result

```python
from app.services.cache_service import CacheService

cache = CacheService()
await cache.set("key", value, ttl=3600)
result = await cache.get("key")
```

### Query Vector DB

```python
from app.services.vector_service import VectorService

vector = VectorService()
results = await vector.search(embedding, top_k=5)
```

### Query PostgreSQL

```python
from app.database import SessionLocal
from app.models import Connection

db = SessionLocal()
conn = db.query(Connection).filter_by(id=1).first()
```

---

## 📈 Performance Tips

```python
# ✅ Good
results = db.query(User).limit(100)      # Limit results
stmt.setQueryTimeout(30)                 # Add timeout
use_indexes = True                       # Create indexes
cache_results = True                     # Cache hits

# ❌ Bad
results = db.query(User).all()           # Fetch all rows
# No timeout                             # Can hang forever
# No indexes                             # Full table scan
# No cache                               # Repeated DB hits
```

---

## 🚀 Production Checklist

Before deploying:

```bash
# ✅ Security
[ ] Update .env with production values
[ ] Enable HTTPS/SSL
[ ] Set DEBUG=false
[ ] Rotate API keys
[ ] Enable authentication

# ✅ Performance
[ ] Enable caching
[ ] Add database indexes
[ ] Set query timeout
[ ] Enable connection pooling
[ ] Monitor resource usage

# ✅ Reliability
[ ] Health checks enabled
[ ] Logging configured
[ ] Backup strategy
[ ] Error handling
[ ] Monitoring/alerting

# ✅ Compliance
[ ] Audit logging
[ ] Data encryption
[ ] Privacy settings
[ ] Documentation
```

---

## 📞 Quick Help

```bash
# Docker help
docker --help
docker-compose --help

# Python help
python --help
pip help

# FastAPI docs
# http://localhost:8000/docs

# PostgreSQL psql commands
# \h [command]

# Redis CLI help
# HELP [command]
```

---

**Last Updated**: February 21, 2026
**Status**: Development Environment Ready ✅
