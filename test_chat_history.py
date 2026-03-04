"""Test chat history save and retrieval."""
import requests
import json
import sys

BASE = "http://localhost:8000"

# 1. Login
login = requests.post(f"{BASE}/api/auth/login", json={"username": "Saurav", "password": "Saurav"})
if login.status_code != 200:
    print(f"Saurav login failed ({login.status_code}), trying admin...")
    login = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})

if login.status_code != 200:
    print(f"FAIL: Login failed with status {login.status_code}")
    sys.exit(1)

data = login.json()
token = data["access_token"]
username = data.get("username", "?")
print(f"Logged in as: {username}")

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# 2. Send a chat query
print("\nSending chat query...")
resp = requests.post(f"{BASE}/api/chat", headers=headers,
                     json={"connection_id": 3, "prompt": "Show me all artists"}, timeout=120)
print(f"  Status: {resp.status_code}")
chat_data = resp.json()
print(f"  Response status: {chat_data.get('status')}")
print(f"  Row count: {chat_data.get('row_count')}")
print(f"  Has SQL: {bool(chat_data.get('sql'))}")
if chat_data.get("error"):
    print(f"  Error: {chat_data['error']}")

# 3. Check chat_history via API
print("\nFetching chat history via API...")
hist = requests.get(f"{BASE}/api/chat/history?connection_id=3", headers=headers)
print(f"  History status: {hist.status_code}")
items = hist.json()
print(f"  Items returned: {len(items)}")
for it in items:
    print(f"    id={it['id']} prompt='{it['prompt'][:40]}' status={it['status']}")

# 4. Also check DB directly
print("\nChecking DB directly...")
from app.database import SessionLocal
from app.models import ChatHistory
db = SessionLocal()
count = db.query(ChatHistory).count()
print(f"  Total rows in chat_history: {count}")
for r in db.query(ChatHistory).all():
    print(f"    id={r.id} user_id={r.user_id} conn={r.connection_id} prompt='{r.prompt[:40]}' status={r.status}")
db.close()

print("\nDone.")
