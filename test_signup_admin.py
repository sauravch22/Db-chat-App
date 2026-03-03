#!/usr/bin/env python3
"""Test signup, login, and admin permission management"""
import requests
import json

BASE = "http://localhost:8000"

# Test 1: Public signup (no auth needed)
r = requests.post(f"{BASE}/api/auth/signup", json={"username": "newguy", "password": "newguy123"})
if r.status_code == 200:
    print(f"✅ Signup OK: {r.json()['username']} with perms {r.json()['permissions']}")
elif r.status_code == 400 and "already exists" in r.text:
    print("ℹ️  newguy already exists, continuing")
else:
    print(f"❌ Signup failed: {r.status_code} {r.text}")

# Test 2: Login as new user (should have only prompt_query)
r2 = requests.post(f"{BASE}/api/auth/login", json={"username": "newguy", "password": "newguy123"})
perms = r2.json().get("permissions", [])
print(f"{'✅' if r2.status_code == 200 and perms == ['prompt_query'] else '❌'} Login newguy => {r2.status_code}, perms: {perms}")

# Test 3: Admin can update permissions
admin = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
atoken = admin.json()["access_token"]
ah = {"Authorization": f"Bearer {atoken}"}

users = requests.get(f"{BASE}/api/auth/users", headers=ah).json()
newguy = next((u for u in users if u["username"] == "newguy"), None)
print(f"{'✅' if newguy else '❌'} User list contains newguy: id={newguy['id'] if newguy else 'N/A'}")

if newguy:
    r3 = requests.put(f"{BASE}/api/auth/users/{newguy['id']}/permissions",
        json={"permissions": ["prompt_query", "db_reindex"]}, headers=ah)
    data = r3.json()
    print(f"{'✅' if r3.status_code == 200 else '❌'} Admin update perms => {r3.status_code}: {data.get('permissions', data.get('detail', ''))}")

# Test 4: Viewer cannot update permissions
viewer = requests.post(f"{BASE}/api/auth/login", json={"username": "viewer", "password": "viewer123"})
vtoken = viewer.json()["access_token"]
vh = {"Authorization": f"Bearer {vtoken}"}
if newguy:
    r4 = requests.put(f"{BASE}/api/auth/users/{newguy['id']}/permissions",
        json={"permissions": ["prompt_query"]}, headers=vh)
    print(f"{'✅' if r4.status_code == 403 else '❌'} Viewer update perms => {r4.status_code}: {r4.json().get('detail', '')}")

# Test 5: Frontend serves updated HTML
r5 = requests.get("http://localhost:3000/")
has_signup = "signupForm" in r5.text and "showSignupForm" in r5.text
has_admin = "adminTab" in r5.text and "tabAdmin" in r5.text
print(f"{'✅' if has_signup else '❌'} Frontend has signup form")
print(f"{'✅' if has_admin else '❌'} Frontend has admin tab")

# Test 6: Frontend JS has new functions
r6 = requests.get("http://localhost:3000/app.js?v=7")
has_funcs = all(f in r6.text for f in ["doSignup", "showSignupForm", "showSigninForm", "switchTab", "loadAdminUsers", "togglePerm"])
print(f"{'✅' if has_funcs else '❌'} app.js has all new functions")

print("\n--- All tests complete ---")
