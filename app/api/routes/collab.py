"""Real-time Collaboration API — WebSocket-based shared query editing sessions."""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException

from app.api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/collab", tags=["Collaboration"])

# In-memory session store (production would use Redis pub/sub)
_sessions: Dict[str, dict] = {}
_connections: Dict[str, Set[WebSocket]] = {}


@router.post("/session")
async def create_session(user: dict = Depends(get_current_user)):
    """Create a new collaboration session."""
    session_id = uuid.uuid4().hex[:12]
    _sessions[session_id] = {
        "id": session_id,
        "created_by": user.get("sub"),
        "created_at": datetime.utcnow().isoformat(),
        "participants": [],
        "sql": "",
        "cursor_positions": {},
    }
    _connections[session_id] = set()
    return {"session_id": session_id}


@router.get("/session/{session_id}")
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    if session_id not in _sessions:
        raise HTTPException(404, "Session not found")
    s = _sessions[session_id]
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "participant_count": len(_connections.get(session_id, set())),
        "sql": s["sql"],
    }


@router.websocket("/ws/{session_id}")
async def collab_websocket(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time query collaboration."""
    if session_id not in _sessions:
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()

    token = websocket.query_params.get("token", "")
    user_id = "anon"
    username = "Anonymous"
    try:
        from app.services.auth_service import decode_access_token
        payload = decode_access_token(token)
        user_id = str(payload.get("sub", "anon"))
        username = payload.get("username", "Anonymous")
    except Exception:
        pass

    if session_id not in _connections:
        _connections[session_id] = set()
    _connections[session_id].add(websocket)

    session = _sessions[session_id]
    if user_id not in [p.get("id") for p in session.get("participants", [])]:
        session.setdefault("participants", []).append({"id": user_id, "name": username})

    try:
        await websocket.send_json({
            "type": "init",
            "sql": session["sql"],
            "participants": session["participants"],
            "cursor_positions": session.get("cursor_positions", {}),
        })

        await _broadcast(session_id, websocket, {
            "type": "user_joined",
            "user_id": user_id,
            "username": username,
        })

        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "sql_change":
                session["sql"] = msg.get("sql", "")
                await _broadcast(session_id, websocket, {
                    "type": "sql_change",
                    "sql": session["sql"],
                    "user_id": user_id,
                    "username": username,
                })

            elif msg.get("type") == "cursor":
                session.setdefault("cursor_positions", {})[user_id] = {
                    "line": msg.get("line", 0),
                    "ch": msg.get("ch", 0),
                    "username": username,
                }
                await _broadcast(session_id, websocket, {
                    "type": "cursor",
                    "user_id": user_id,
                    "username": username,
                    "line": msg.get("line", 0),
                    "ch": msg.get("ch", 0),
                })

            elif msg.get("type") == "chat":
                await _broadcast(session_id, websocket, {
                    "type": "chat",
                    "user_id": user_id,
                    "username": username,
                    "message": msg.get("message", ""),
                    "timestamp": datetime.utcnow().isoformat(),
                })

    except WebSocketDisconnect:
        _connections[session_id].discard(websocket)
        await _broadcast(session_id, None, {
            "type": "user_left",
            "user_id": user_id,
            "username": username,
        })
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        _connections[session_id].discard(websocket)


async def _broadcast(session_id: str, sender: WebSocket, message: dict):
    """Send message to all connected clients except the sender."""
    dead = set()
    for ws in _connections.get(session_id, set()):
        if ws is sender:
            continue
        try:
            await ws.send_json(message)
        except Exception:
            dead.add(ws)
    _connections.get(session_id, set()).difference_update(dead)
