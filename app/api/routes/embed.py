"""Embeddable Widget API — generates embed code and serves a lightweight chat widget."""

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from app.api.deps import get_current_user, has_db_permission
from app.database import SessionLocal
from app.models import Connection
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/embed", tags=["Embeddable Widget"])

_embed_tokens: dict = {}


class CreateEmbedRequest(BaseModel):
    connection_id: int
    title: Optional[str] = "Database Chat"
    theme: str = "light"
    allowed_tables: Optional[str] = None


@router.post("/create")
async def create_embed(req: CreateEmbedRequest, user: dict = Depends(get_current_user)):
    """Generate an embeddable widget token and HTML snippet."""
    if not has_db_permission(user, req.connection_id, "prompt_query"):
        raise HTTPException(403, "Permission required on this database")
    db = SessionLocal()
    try:
        conn = db.query(Connection).filter(Connection.id == req.connection_id,
                                            Connection.is_active == True).first()
        if not conn:
            raise HTTPException(404, "Connection not found")

        token = uuid.uuid4().hex[:20]
        _embed_tokens[token] = {
            "connection_id": req.connection_id,
            "user_id": int(user["sub"]),
            "title": req.title,
            "theme": req.theme,
            "allowed_tables": req.allowed_tables,
        }

        snippet = f"""<!-- DbChat Embed Widget -->
<div id="dbchat-widget"></div>
<script src="/api/embed/widget.js" data-token="{token}" data-theme="{req.theme}"></script>"""

        return {"token": token, "snippet": snippet, "title": req.title}
    finally:
        db.close()


@router.get("/tokens")
async def list_embed_tokens(user: dict = Depends(get_current_user)):
    return [
        {"token": t[:8] + "…", "connection_id": cfg["connection_id"],
         "title": cfg["title"], "theme": cfg["theme"]}
        for t, cfg in _embed_tokens.items()
        if cfg.get("user_id") == int(user["sub"])
    ]


@router.get("/widget.js")
async def widget_js(request: Request):
    """Serve the embeddable widget JavaScript."""
    base_url = str(request.base_url).rstrip("/")
    js = f"""
(function() {{
  var script = document.currentScript;
  var token = script.getAttribute('data-token');
  var theme = script.getAttribute('data-theme') || 'light';
  var container = document.getElementById('dbchat-widget') || document.body;

  var iframe = document.createElement('iframe');
  iframe.src = '{base_url}/api/embed/frame?token=' + token + '&theme=' + theme;
  iframe.style.cssText = 'width:100%;height:500px;border:1px solid #e2e8f0;border-radius:12px;';
  iframe.setAttribute('frameborder', '0');
  container.appendChild(iframe);
}})();
"""
    return HTMLResponse(content=js, media_type="application/javascript")


@router.get("/frame")
async def widget_frame(token: str, theme: str = "light"):
    """Serve the embeddable widget HTML frame."""
    if token not in _embed_tokens:
        return HTMLResponse("<h3>Invalid widget token</h3>", status_code=403)

    cfg = _embed_tokens[token]
    bg = "#ffffff" if theme == "light" else "#1a1a2e"
    fg = "#1a1a2e" if theme == "light" else "#e2e8f0"
    accent = "#6366f1"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<style>
  * {{ margin:0;padding:0;box-sizing:border-box; }}
  body {{ font-family:system-ui,-apple-system,sans-serif;background:{bg};color:{fg};padding:16px; }}
  .header {{ font-size:16px;font-weight:600;margin-bottom:12px;color:{accent}; }}
  .chat-box {{ display:flex;flex-direction:column;height:calc(100vh - 90px); }}
  .messages {{ flex:1;overflow-y:auto;margin-bottom:12px;padding:8px;border:1px solid #e2e8f033;border-radius:8px; }}
  .msg {{ margin-bottom:8px;padding:8px 12px;border-radius:8px;font-size:14px;line-height:1.5; }}
  .msg.user {{ background:{accent}22;text-align:right; }}
  .msg.bot {{ background:{fg}11; }}
  .msg pre {{ background:{fg}08;padding:8px;border-radius:4px;overflow-x:auto;font-size:12px;margin-top:4px; }}
  .input-row {{ display:flex;gap:8px; }}
  .input-row input {{ flex:1;padding:10px 14px;border:1px solid #e2e8f0;border-radius:8px;font-size:14px;background:{bg};color:{fg}; }}
  .input-row button {{ padding:10px 20px;background:{accent};color:#fff;border:none;border-radius:8px;cursor:pointer;font-weight:600; }}
  .input-row button:hover {{ opacity:0.9; }}
</style></head><body>
<div class="header">{cfg['title']}</div>
<div class="chat-box">
  <div class="messages" id="msgs"></div>
  <div class="input-row">
    <input type="text" id="q" placeholder="Ask about your data..." onkeydown="if(event.key==='Enter')send()">
    <button onclick="send()">Ask</button>
  </div>
</div>
<script>
  var TOKEN = '{token}';
  var CONN = {cfg['connection_id']};
  function send() {{
    var q = document.getElementById('q');
    var msg = q.value.trim();
    if (!msg) return;
    addMsg(msg, 'user');
    q.value = '';
    fetch('/api/embed/query?token='+TOKEN+'&prompt='+encodeURIComponent(msg), {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
    }}).then(r=>r.json()).then(d=>{{
      var text = d.answer || d.error || 'No response';
      if (d.sql) text += '\\n```sql\\n' + d.sql + '\\n```';
      addMsg(text, 'bot');
    }}).catch(e=>addMsg('Error: '+e.message,'bot'));
  }}
  function _escHtml(s) {{ var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }}
  function addMsg(text, cls) {{
    var d = document.createElement('div');
    d.className = 'msg ' + cls;
    var safe = _escHtml(text);
    safe = safe.replace(/```(\\w*)\\n([\\s\\S]*?)```/g, '<pre>$2</pre>');
    d.innerHTML = safe;
    document.getElementById('msgs').appendChild(d);
    d.scrollIntoView({{behavior:'smooth'}});
  }}
</script></body></html>"""
    return HTMLResponse(content=html)


@router.post("/query")
async def embed_query(token: str, prompt: str):
    """Execute a query through the embed widget."""
    if token not in _embed_tokens:
        raise HTTPException(403, "Invalid embed token")
    cfg = _embed_tokens[token]
    svc = ChatService()
    try:
        result = await svc.process_query(
            connection_id=cfg["connection_id"],
            user_prompt=prompt,
            user_id=int(cfg["user_id"]),
        )
        return result
    finally:
        svc.close()
