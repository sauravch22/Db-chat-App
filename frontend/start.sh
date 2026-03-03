#!/bin/bash

# Frontend startup script

echo "🚀 Starting DbChat Frontend..."

cd "$(dirname "$0")"

# Check if venv exists
if [ ! -d "../venv" ]; then
    echo "❌ Virtual environment not found at ../venv"
    exit 1
fi

# Activate venv
source ../venv/bin/activate

# Start frontend server on port 3000
echo "📱 Frontend will be available at http://localhost:3000"
echo ""
echo "Make sure the following services are running:"
echo "  - Chat Service: http://localhost:8000"
echo "  - Viz Service: http://localhost:8001"
echo ""

uvicorn server:app --host 0.0.0.0 --port 3000 --reload
