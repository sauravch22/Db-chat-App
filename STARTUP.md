# DbChat Development Startup Guide

## Prerequisites

### 1. Start Docker Desktop

On macOS, start Docker Desktop application:
```bash
# Option 1: Using Spotlight
cmd + space
# Type "Docker" and press Enter

# Option 2: Direct command
open /Applications/Docker.app
```

Wait for Docker to fully start (you should see the whale icon in menu bar)

### 2. Verify Docker is Running

```bash
docker ps
docker version
```

## Quick Start

### Step 1: Navigate to Project

```bash
cd /Users/sauravchakraborty/DbChat
```

### Step 2: Start Services

```bash
# Start all containers
docker-compose up -d

# Watch them start
docker-compose logs -f
```

You should see:
```
✓ postgres (healthy)
✓ redis (healthy)
✓ qdrant (healthy)
✓ ollama (running)
```

### Step 3: Pull Ollama Models

```bash
# Open new terminal while containers are running

# Pull LLM model (Mistral - ~4GB)
docker-compose exec ollama ollama pull mistral

# Pull embedding model (Nomic - ~274MB)
docker-compose exec ollama ollama pull nomic-embed-text

# Verify models are installed
docker-compose exec ollama ollama list
```

**Note**: First run takes time (downloading models). Be patient!

### Step 4: Setup Python

```bash
# Create virtual environment
python3 -m venv venv

# Activate
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 5: Run Application

```bash
# With virtual environment activated
python main.py
```

App should start on `http://localhost:8000`

## Verify Everything Works

### Test 1: Check Services

```bash
# Health check
curl http://localhost:8000/health

# Should return:
# {"status": "healthy", "timestamp": "2026-02-21T..."}
```

### Test 2: Check Database

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U dbchat -d dbchat_metadata -c "\dt"

# Should show tables:
# - connections
# - databases
# - tables
# - columns
# - samples
# - queries
```

### Test 3: Check Redis

```bash
docker-compose exec redis redis-cli ping
# Should return: PONG
```

### Test 4: Check Qdrant

```bash
curl http://localhost:6333/health
# Should return health info
```

### Test 5: Check Ollama

```bash
curl http://localhost:11434/api/tags
# Should list mistral and nomic-embed-text
```

## Common Issues & Fixes

### Issue: Docker daemon not running

**Solution:**
```bash
# Start Docker Desktop
open /Applications/Docker.app

# Wait ~1 minute for it to fully start
# Then verify
docker ps
```

### Issue: Port already in use

```bash
# Find what's using the port
lsof -i :5432  # PostgreSQL
lsof -i :6379  # Redis
lsof -i :6333  # Qdrant
lsof -i :11434 # Ollama

# Kill the process
kill -9 <PID>
```

### Issue: Models not downloading

```bash
# Check Ollama logs
docker-compose logs ollama

# Try pulling again with verbose
docker-compose exec ollama ollama pull mistral --verbose

# Check disk space
df -h
```

### Issue: Container won't start

```bash
# Rebuild everything
docker-compose down -v
docker-compose up -d

# Check logs
docker-compose logs [service_name]
```

## Directory Structure Created

```
DbChat/
├── main.py                          # FastAPI app entry point
├── requirements.txt                 # Python dependencies
├── docker-compose.yml               # Docker services
├── init_db.sql                      # Database schema
├── .env                             # Configuration
├── .gitignore                       # Git ignore rules
├── README.md                        # Main documentation
├── STARTUP.md                       # This file
│
├── app/
│   ├── __init__.py
│   ├── config.py                    # Settings management
│   ├── database.py                  # DB connection
│   ├── models.py                    # SQLAlchemy models
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── health.py            # Health checks
│   │       ├── chat.py              # Chat API
│   │       └── admin.py             # Admin API
│   │
│   └── services/
│       ├── __init__.py
│       ├── ollama_service.py        # LLM interface
│       ├── vector_service.py        # Vector DB interface
│       └── cache_service.py         # Cache interface
```

## Services Running

| Service | Port | URL | Purpose |
|---------|------|-----|---------|
| FastAPI | 8000 | http://localhost:8000 | Main application |
| PostgreSQL | 5432 | localhost:5432 | Metadata database |
| Redis | 6379 | localhost:6379 | Caching |
| Qdrant | 6333 | http://localhost:6333 | Vector database |
| Ollama | 11434 | http://localhost:11434 | LLM inference |

## Next Steps

1. ✅ Docker containers running
2. ✅ Python environment setup
3. ✅ FastAPI application running
4. 🔄 **Implement chat service logic**
5. 🔄 Add schema extraction
6. 🔄 Add context builder
7. 🔄 Add SQL generation
8. 🔄 Add vector search
9. 🔄 Add query execution
10. 🔄 Add result formatting

## Stop Services

```bash
# Stop all containers
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v
```

## View Logs

```bash
# All services
docker-compose logs -f

# Single service
docker-compose logs -f ollama
docker-compose logs -f postgres
docker-compose logs -f redis
docker-compose logs -f qdrant

# Last 100 lines
docker-compose logs -f --tail=100
```

## Using API Docs

Once app is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

These provide interactive API documentation and testing.

---

**Ready to start?**
1. Start Docker Desktop
2. Run `docker-compose up -d`
3. Pull Ollama models
4. Run `python main.py`
5. Open http://localhost:8000/docs

Good luck! 🚀
