"""Test: login as Saurav, send a prompt, check if history is saved."""
import requests, json, sys, time
sys.path.insert(0, '.')

BASE = 'http://localhost:8000'

# 1. Login as Saurav
print("1. Login as Saurav...")
r = requests.post(f'{BASE}/api/auth/login', json={'username': 'Saurav', 'password': 'Saurav123'})
if not r.ok:
    print(f"   FAILED: {r.status_code} {r.text}")
    sys.exit(1)
token = r.json()['access_token']
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
print(f"   OK. user_id from token sub = {r.json().get('perms')}")

# Decode JWT to see sub
import base64
payload = token.split('.')[1]
payload += '=' * (4 - len(payload) % 4)
decoded = json.loads(base64.b64decode(payload))
print(f"   JWT payload: sub={decoded['sub']}, username={decoded['username']}")

# 2. Check history BEFORE prompt
print("\n2. Check history BEFORE sending prompt...")
r = requests.get(f'{BASE}/api/chat/history?connection_id=3&limit=50', headers=headers)
print(f"   Status: {r.status_code}, items: {len(r.json())}")

# 3. Send a chat prompt
print("\n3. Sending chat prompt: 'Show me all artists'...")
r = requests.post(f'{BASE}/api/chat', headers=headers,
                  json={'connection_id': 3, 'prompt': 'Show me all artists'})
print(f"   Response status: {r.status_code}")
if r.ok:
    data = r.json()
    print(f"   Chat status: {data.get('status')}")
    print(f"   Has SQL: {bool(data.get('sql'))}")
    print(f"   Row count: {data.get('row_count')}")
    print(f"   Answer: {(data.get('answer') or '')[:80]}")
else:
    print(f"   ERROR: {r.text[:200]}")
    sys.exit(1)

# 4. Small delay then check history AFTER prompt
time.sleep(1)
print("\n4. Check history AFTER sending prompt...")
r = requests.get(f'{BASE}/api/chat/history?connection_id=3&limit=50', headers=headers)
items = r.json()
print(f"   Status: {r.status_code}, items: {len(items)}")
if items:
    for it in items:
        print(f"   -> id={it['id']}, prompt='{it['prompt'][:40]}', status={it['status']}")
    print("\n   ✅ HISTORY IS WORKING!")
else:
    print("\n   ❌ HISTORY IS EMPTY - _save_chat_history FAILED!")
    print("   Check /tmp/dbchat_server.log for [HISTORY-SAVE-ERROR]")

# 5. Check DB directly
print("\n5. Direct DB check...")
import logging; logging.disable(logging.CRITICAL)
from app.database import SessionLocal
from app.models import ChatHistory
db = SessionLocal()
rows = db.query(ChatHistory).filter(ChatHistory.user_id == 3).all()
print(f"   DB rows for user_id=3: {len(rows)}")
for r in rows:
    print(f"   -> id={r.id}, prompt='{r.prompt[:40]}', status={r.status}")
db.close()
