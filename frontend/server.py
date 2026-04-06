"""
Frontend server for DbChat
Serves the web interface and proxies /api/* requests to the backend.

Environment variables:
  FRONTEND_PORT  – port for this server        (default 3000)
  BACKEND_PORT   – port the backend listens on (default 8000)
  BACKEND_HOST   – backend hostname            (default 127.0.0.1)
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
import uvicorn
import os

FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "3000"))
BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

app = FastAPI(title="DbChat Frontend")

_allowed = os.getenv("ALLOWED_ORIGINS", f"http://localhost:{FRONTEND_PORT}").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_client = httpx.AsyncClient(base_url=BACKEND_URL, timeout=120.0)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_api(path: str, request: Request):
    """Reverse-proxy every /api/* request to the backend."""
    url = f"/api/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = dict(request.headers)
    headers.pop("host", None)

    body = await request.body()

    resp = await _client.request(
        method=request.method,
        url=url,
        headers=headers,
        content=body,
    )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )


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
    print(f"Frontend → http://0.0.0.0:{FRONTEND_PORT}")
    print(f"Proxying /api/* → {BACKEND_URL}")
    uvicorn.run(app, host="0.0.0.0", port=FRONTEND_PORT, reload=True)
