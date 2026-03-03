"""
Frontend server for DbChat
Serves the web interface and handles CORS
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

app = FastAPI(title="DbChat Frontend")

# Enable CORS for backend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get the directory of this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
async def root():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

@app.get("/{file_path:path}")
async def serve_file(file_path: str):
    file_full_path = os.path.join(BASE_DIR, file_path)
    if os.path.isfile(file_full_path):
        return FileResponse(file_full_path)
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000, reload=True)
