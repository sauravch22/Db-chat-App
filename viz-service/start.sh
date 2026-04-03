#!/bin/bash

# Start Visualization Service
# Independent microservice for chart recommendations

echo "Starting DbChat Visualization Service..."

# Activate virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Install dependencies
pip install -r requirements.txt

# Start service on port 8001
uvicorn app:app --host 0.0.0.0 --port 8001 --reload
