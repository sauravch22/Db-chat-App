#!/usr/bin/env python3
"""Test auth system: permissions enforcement"""
import requests
import json

BASE = "http://localhost:8000"

# 1. Login as admin
resp = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
assert resp.status_code == 200, f"Admin login failed: {resp.text}"
admin_token = resp.json()["access_token"]
admin_h = {"Authorization": f"Bearer {admin_token}"}
print("✅ Admin login OK")

# 2. Register a viewer user (prompt_query only)
r = requests.post(f"{BASE}/api/auth/register", json={
    "username": "viewer",
    "password": "viewer123",
    "permissions": ["prompt_query"]
}, headers=admin_h)
if r.status_code == 200:
    print(f"✅ Registered viewer: {r.json()}")
elif r.status_code == 400 and "already exists" in r.text:
    print("ℹ️  Viewer already exists, continuing")
else:
    print(f"❌ Register viewer failed: {r.status_code} {r.text}")

# 3. Login as viewer
resp2 = requests.post(f"{BASE}/api/auth/login", json={"username": "viewer", "password": "viewer123"})
assert resp2.status_code == 200, f"Viewer login failed: {resp2.text}"
viewer_token = resp2.json()["access_token"]
viewer_h = {"Authorization": f"Bearer {viewer_token}"}
perms = resp2.json()["permissions"]
print(f"✅ Viewer login OK, permissions: {perms}")

# 4. Viewer CAN access /databases (any authenticated user)
r1 = requests.get(f"{BASE}/api/admin/databases", headers=viewer_h)
print(f"{'✅' if r1.status_code == 200 else '❌'} GET /databases (viewer) => {r1.status_code}")

# 5. Viewer CANNOT register-db (needs db_onboard)
r2 = requests.post(f"{BASE}/api/admin/register-db", json={
    "name": "test", "host": "x", "port": 5432,
    "username": "x", "password": "x", "database": "x"
}, headers=viewer_h)
detail = r2.json().get("detail", "")
print(f"{'✅' if r2.status_code == 403 else '❌'} POST /register-db (viewer) => {r2.status_code} {detail}")

# 6. Viewer CANNOT reindex (needs db_reindex)
r3 = requests.post(f"{BASE}/api/admin/reindex/3", headers=viewer_h)
detail3 = r3.json().get("detail", "")
print(f"{'✅' if r3.status_code == 403 else '❌'} POST /reindex (viewer) => {r3.status_code} {detail3}")

# 7. No token => 401 on chat
r4 = requests.post(f"{BASE}/api/chat", json={"message": "hello", "connection_id": 3})
print(f"{'✅' if r4.status_code == 401 else '❌'} POST /chat (no auth) => {r4.status_code}")

# 8. Viewer CAN use chat (has prompt_query)
r5 = requests.post(f"{BASE}/api/chat", json={"prompt": "how many tables?", "connection_id": 3}, headers=viewer_h)
print(f"{'✅' if r5.status_code == 200 else '❌'} POST /chat (viewer) => {r5.status_code}")

print("\n--- Auth test complete ---")
