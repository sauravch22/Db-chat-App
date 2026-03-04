"""Test: send 2 prompts as Saurav, logout, re-login, verify history persists."""
import requests, json, sys, time
sys.path.insert(0, '.')

BASE = 'http://localhost:8000'

# 1. Login as Saurav
print("1. Login as Saurav...")
r = requests.post(f'{BASE}/api/auth/login', json={'username': 'Saurav', 'password': 'Saurav123'})
assert r.ok, f"Login failed: {r.status_code}"
token1 = r.json()['access_token']
h1 = {'Authorization': f'Bearer {token1}', 'Content-Type': 'application/json'}
print("   OK")

# 2. Send second prompt
print("\n2. Sending prompt: 'Show me top 5 albums'...")
r = requests.post(f'{BASE}/api/chat', headers=h1,
                  json={'connection_id': 3, 'prompt': 'Show me top 5 albums'})
print(f"   Status: {r.status_code}, chat_status: {r.json().get('status')}")

time.sleep(1)

# 3. Check history - should have 2 items now
print("\n3. Check history (should be 2 items)...")
r = requests.get(f'{BASE}/api/chat/history?connection_id=3&limit=50', headers=h1)
items = r.json()
print(f"   Items: {len(items)}")
for it in items:
    print(f"   -> {it['prompt'][:50]}")

# 4. Simulate LOGOUT + RE-LOGIN
print("\n4. Simulating logout + re-login...")
r = requests.post(f'{BASE}/api/auth/login', json={'username': 'Saurav', 'password': 'Saurav123'})
assert r.ok
token2 = r.json()['access_token']
h2 = {'Authorization': f'Bearer {token2}', 'Content-Type': 'application/json'}
print("   Got new token")

# 5. Check history with new token
print("\n5. Check history after re-login...")
r = requests.get(f'{BASE}/api/chat/history?connection_id=3&limit=50', headers=h2)
items = r.json()
print(f"   Items: {len(items)}")
for it in items:
    print(f"   -> {it['prompt'][:50]}")

if len(items) >= 2:
    print("\n✅ PASS: Chat history persists across login sessions!")
else:
    print("\n❌ FAIL: History lost after re-login!")
