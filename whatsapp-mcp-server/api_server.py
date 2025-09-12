from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Query, HTTPException, Body, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from whatsapp import (
    MESSAGES_DB_PATH,
    get_message_context,
    list_chats as wa_list_chats,
    search_contacts as wa_search_contacts,
    get_chat as wa_get_chat,
    get_direct_chat_by_contact as wa_get_direct_chat,
    get_contact_chats as wa_get_contact_chats,
    send_message as wa_send_message,
    send_file as wa_send_file,
    send_audio_message as wa_send_audio,
    download_media as wa_download_media,
    Chat,
    Contact,
)

app = FastAPI(title="WhatsApp MCP Web API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def chat_to_dict(chat: Chat) -> Dict[str, Any]:
    return {
        "jid": chat.jid,
        "name": chat.name,
        "last_message_time": chat.last_message_time.isoformat() if chat.last_message_time else None,
        "last_message": chat.last_message,
        "last_sender": chat.last_sender,
        "last_is_from_me": chat.last_is_from_me,
        "is_group": chat.jid.endswith("@g.us"),
    }

def contact_to_dict(contact: Contact) -> Dict[str, Any]:
    return {
        "jid": contact.jid,
        "name": contact.name,
        "phone_number": contact.phone_number,
    }

def row_to_message(row: tuple) -> Dict[str, Any]:
    # matches select order
    return {
        "timestamp": datetime.fromisoformat(row[0]).isoformat(),
        "sender": row[1],
        "chat_name": row[2],
        "content": row[3],
        "is_from_me": bool(row[4]),
        "chat_jid": row[5],
        "id": row[6],
        "media_type": row[7],
    }

@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok"}

@app.get("/api/health/details")
def health_details() -> Dict[str, Any]:
    """
    Extended health/status payload including database statistics.
    """
    conn = sqlite3.connect(MESSAGES_DB_PATH)
    try:
        cur = conn.cursor()
        # Chats
        cur.execute("SELECT COUNT(*) FROM chats")
        chat_count = cur.fetchone()[0]
        # Messages
        cur.execute("SELECT COUNT(*) FROM messages")
        msg_count = cur.fetchone()[0]
        # Latest message time
        cur.execute("SELECT MAX(timestamp) FROM messages")
        latest = cur.fetchone()[0]
    finally:
        conn.close()
    return {
        "status": "ok",
        "schema_version": 1,
        "database": {
            "path": MESSAGES_DB_PATH,
            "chats": chat_count,
            "messages": msg_count,
            "latest_message_time": latest,
        },
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
    }

class ConnectionManager:
    """
    Very lightweight in-memory WebSocket connection manager.
    Not production-hardened (no auth / scaling / backpressure handling).
    """
    def __init__(self) -> None:
        self.active: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, data: Dict[str, Any]) -> None:
        survivors: List[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_json(data)
                survivors.append(ws)
            except Exception:
                # Drop broken connection silently
                pass
        self.active = survivors

manager = ConnectionManager()

@app.websocket("/ws/messages")
async def websocket_messages(websocket: WebSocket):
    """
    WebSocket stub:
      - Accepts connections
      - Echoes any received JSON back to the client
      - Provides a simple heartbeat pattern clients can use
    Future enhancement: push newly observed messages via broadcast().
    """
    await manager.connect(websocket)
    try:
        await websocket.send_json({"type": "welcome", "message": "Connected to /ws/messages"})
        while True:
            data = await websocket.receive_json()
            # Simple echo / heartbeat response
            await websocket.send_json({"type": "echo", "received": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        manager.disconnect(websocket)

@app.get("/api/chats")
def get_chats(
    q: Optional[str] = Query(default=None, description="Search by name or JID"),
    limit: int = Query(20, ge=1, le=200),
    page: int = Query(0, ge=0),
    include_last_message: bool = Query(True),
    sort_by: str = Query("last_active", pattern="^(last_active|name)$"),
) -> Dict[str, Any]:
    chats = wa_list_chats(query=q, limit=limit, page=page, include_last_message=include_last_message, sort_by=sort_by)
    return {
        "chats": [chat_to_dict(c) for c in chats],
        "pagination": {"limit": limit, "page": page, "count": len(chats), "has_more": len(chats) == limit},
    }

@app.get("/api/chats/{jid}")
def get_chat(jid: str, include_last_message: bool = Query(True)) -> Dict[str, Any]:
    chat = wa_get_chat(jid, include_last_message)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat_to_dict(chat)

@app.get("/api/chats/{jid}/messages")
def get_chat_messages(
    jid: str,
    limit: int = Query(50, ge=1, le=500),
    page: int = Query(0, ge=0),
    before: Optional[str] = Query(None, description="Only messages before this ISO timestamp"),
    after: Optional[str] = Query(None, description="Only messages after this ISO timestamp"),
    query: Optional[str] = Query(None, description="Search text"),
    include_context: bool = Query(False),
    context_before: int = Query(1, ge=0, le=10),
    context_after: int = Query(1, ge=0, le=10),
) -> Dict[str, Any]:
    if before:
        try:
           datetime.fromisoformat(before)
        except ValueError:
           raise HTTPException(400, "Invalid 'before' timestamp")
    if after:
        try:
           datetime.fromisoformat(after)
        except ValueError:
           raise HTTPException(400, "Invalid 'after' timestamp")
    conn = sqlite3.connect(MESSAGES_DB_PATH)
    try:
        qp = ["SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type FROM messages"]
        qp.append("JOIN chats ON messages.chat_jid = chats.jid")
        where = ["messages.chat_jid = ?"]
        params: List[Any] = [jid]
        if after:
           where.append("messages.timestamp > ?")
           params.append(after)
        if before:
           where.append("messages.timestamp < ?")
           params.append(before)
        if query:
           where.append("LOWER(messages.content) LIKE LOWER(?)")
           params.append(f"%{query}%")
        qp.append("WHERE " + " AND ".join(where))
        qp.append("ORDER BY messages.timestamp DESC")
        offset = page * limit
        qp.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        cur = conn.cursor()
        cur.execute(" ".join(qp), tuple(params))
        rows = cur.fetchall()
        messages = [row_to_message(r) for r in rows]
        if include_context:
            expanded: Dict[str, Dict[str, Any]] = {}
            out: List[Dict[str, Any]] = []
            for m in messages:
                out.append(m)
                ctx = get_message_context(m["id"], context_before, context_after)
                for b in ctx.before:
                    if b.id not in expanded:
                        expanded[b.id] = row_to_message((
                            b.timestamp.isoformat(), b.sender, b.chat_name, b.content, int(b.is_from_me), b.chat_jid, b.id, b.media_type
                        ))
                        out.append(expanded[b.id])
                if ctx.message.id not in expanded:
                    expanded[ctx.message.id] = row_to_message((
                        ctx.message.timestamp.isoformat(), ctx.message.sender, ctx.message.chat_name, ctx.message.content, int(ctx.message.is_from_me), ctx.message.chat_jid, ctx.message.id, ctx.message.media_type
                    ))
                for a in ctx.after:
                    if a.id not in expanded:
                        expanded[a.id] = row_to_message((
                            a.timestamp.isoformat(), a.sender, a.chat_name, a.content, int(a.is_from_me), a.chat_jid, a.id, a.media_type
                        ))
                        out.append(expanded[a.id])
            messages = out
        return {
            "messages": messages,
            "pagination": {"limit": limit, "page": page, "count": len(messages), "has_more": len(rows) == limit},
            "chat_jid": jid,
        }
    finally:
        conn.close()

@app.get("/api/messages")
def global_messages(
    limit: int = Query(50, ge=1, le=500),
    page: int = Query(0, ge=0),
    query: Optional[str] = Query(None),
    sender: Optional[str] = Query(None),
    chat_jid: Optional[str] = Query(None),
) -> Dict[str, Any]:
    conn = sqlite3.connect(MESSAGES_DB_PATH)
    try:
        qp = ["SELECT messages.timestamp, messages.sender, chats.name, messages.content, messages.is_from_me, chats.jid, messages.id, messages.media_type FROM messages JOIN chats ON messages.chat_jid = chats.jid"]
        where: List[str] = []
        params: List[Any] = []
        if query:
            where.append("LOWER(messages.content) LIKE LOWER(?)")
            params.append(f"%{query}%")
        if sender:
            where.append("messages.sender = ?")
            params.append(sender)
        if chat_jid:
            where.append("messages.chat_jid = ?")
            params.append(chat_jid)
        if where:
            qp.append("WHERE " + " AND ".join(where))
        qp.append("ORDER BY messages.timestamp DESC")
        offset = page * limit
        qp.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        cur = conn.cursor()
        cur.execute(" ".join(qp), tuple(params))
        rows = cur.fetchall()
        messages = [row_to_message(r) for r in rows]
        return {
            "messages": messages,
            "pagination": {"limit": limit, "page": page, "count": len(messages), "has_more": len(rows) == limit},
        }
    finally:
        conn.close()

@app.get("/api/contacts")
def contacts(q: str = Query(..., description="Search query")) -> Dict[str, Any]:
    items = wa_search_contacts(q)
    return {"contacts": [contact_to_dict(c) for c in items]}

@app.get("/api/contacts/{phone_number}/direct-chat")
def direct_chat(phone_number: str) -> Dict[str, Any]:
    chat = wa_get_direct_chat(phone_number)
    if not chat:
        raise HTTPException(404, "Direct chat not found")
    return chat_to_dict(chat)

@app.get("/api/contacts/{jid}/chats")
def contact_chats(jid: str, limit: int = Query(20, ge=1, le=200), page: int = Query(0, ge=0)) -> Dict[str, Any]:
    chats = wa_get_contact_chats(jid, limit, page)
    return {
        "chats": [chat_to_dict(c) for c in chats],
        "pagination": {"limit": limit, "page": page, "count": len(chats), "has_more": len(chats) == limit},
    }

@app.post("/api/messages/send")
def send_text(recipient: str = Body(...), message: str = Body(...)) -> Dict[str, Any]:
    success, status = wa_send_message(recipient, message)
    return {"success": success, "message": status}

@app.post("/api/messages/send-file")
def send_file(recipient: str = Body(...), media_path: str = Body(...)) -> Dict[str, Any]:
    success, status = wa_send_file(recipient, media_path)
    return {"success": success, "message": status}

@app.post("/api/messages/send-audio")
def send_audio(recipient: str = Body(...), media_path: str = Body(...)) -> Dict[str, Any]:
    success, status = wa_send_audio(recipient, media_path)
    return {"success": success, "message": status}

@app.post("/api/media/download")
def download_media(message_id: str = Body(...), chat_jid: str = Body(...)) -> Dict[str, Any]:
    path = wa_download_media(message_id, chat_jid)
    if not path:
        raise HTTPException(500, "Failed to download media")
    return {"success": True, "path": path}

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>WhatsApp WebUI (Local)</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    body { margin:0; font-family: system-ui, sans-serif; color:#111; display:flex; height:100vh; }
    #sidebar { width:300px; border-right:1px solid #ddd; display:flex; flex-direction:column; }
    #chatList { overflow:auto; flex:1; }
    #chatList .chat { padding:8px 10px; cursor:pointer; border-bottom:1px solid #eee; }
    #chatList .chat.active { background:#eef; }
    #main { flex:1; display:flex; flex-direction:column; }
    #messages { flex:1; overflow:auto; padding:12px; background:#fafafa; }
    .msg { margin-bottom:8px; padding:6px 8px; border-radius:6px; max-width:70%; }
    .from-me { background:#d1f5d3; margin-left:auto; }
    .from-them { background:white; border:1px solid #e2e2e2; }
    #composer { border-top:1px solid #ddd; padding:8px; display:flex; gap:6px; }
    #composer input { flex:1; padding:6px 8px; }
    header { padding:8px; border-bottom:1px solid #ddd; font-weight:600; }
  </style>
</head>
<body>
  <div id="sidebar">
    <header>Chats</header>
    <div style="padding:6px;">
      <input id="searchChats" type="text" placeholder="Search chats..." style="width:100%;padding:6px 8px;">
    </div>
    <div id="chatList"></div>
  </div>
  <div id="main">
    <header id="chatHeader">Select a chat</header>
    <div id="messages"></div>
    <div id="composer">
      <input id="messageInput" placeholder="Type a message..." />
      <button id="sendBtn">Send</button>
    </div>
  </div>
  <script>
  const api = (p, opts={}) => fetch(p, {headers:{'Content-Type':'application/json'}, ...opts}).then(r=>r.json());
  let currentChat = null;
  async function loadChats(q='') {
    const data = await api('/api/chats'+(q?`?q=${encodeURIComponent(q)}`:''));
    const list = document.getElementById('chatList');
    list.innerHTML = '';
    data.chats.forEach(c=>{
      const div = document.createElement('div');
      div.className='chat'+(currentChat && currentChat.jid===c.jid?' active':'');
      div.textContent = c.name || c.jid;
      div.onclick=()=>{ currentChat=c; document.getElementById('chatHeader').textContent = c.name||c.jid; loadMessages(); loadChats(document.getElementById('searchChats').value); };
      list.appendChild(div);
    });
  }
  async function loadMessages() {
    if(!currentChat) return;
    const data = await api(`/api/chats/${encodeURIComponent(currentChat.jid)}/messages?limit=100`);
    const box = document.getElementById('messages');
    box.innerHTML='';
    data.messages.slice().reverse().forEach(m=>{
      const div=document.createElement('div');
      div.className='msg '+(m.is_from_me?'from-me':'from-them');
      div.innerHTML = '<small>'+new Date(m.timestamp).toLocaleString()+'</small><br>'+ (m.media_type?`<em>[${m.media_type}]</em> `:'') + (m.content||'');
      box.appendChild(div);
    });
    box.scrollTop=box.scrollHeight;
  }
  document.getElementById('sendBtn').onclick=async ()=>{
    if(!currentChat) return alert('Select a chat first');
    const input=document.getElementById('messageInput');
    const text=input.value.trim();
    if(!text) return;
    const res = await api('/api/messages/send',{method:'POST',body:JSON.stringify({recipient: currentChat.jid, message: text})});
    if(res.success){ input.value=''; loadMessages(); } else { alert(res.message); }
  };
  document.getElementById('searchChats').oninput = (e)=> loadChats(e.target.value);
  loadChats();
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)

if __name__ == "__main__":
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=False)
