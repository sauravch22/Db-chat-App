"""End-to-end test: verify chat history persists across logins."""
import requests
import json
import sys

# Add project root to path
sys.path.insert(0, '.')

BASE = 'http://localhost:8000'

def main():
    # 1. Login as Saurav
    print("=== Step 1: Login as Saurav ===")
    r = requests.post(f'{BASE}/api/auth/login', json={'username': 'Saurav', 'password': 'Saurav123'})
    assert r.ok, f"Login failed: {r.status_code} {r.text}"
    token1 = r.json()['access_token']
    h1 = {'Authorization': f'Bearer {token1}', 'Content-Type': 'application/json'}
    print(f"  OK, perms={r.json()['perms']}")

    # 2. Check history (should be empty for Saurav)
    print("\n=== Step 2: Check initial history ===")
    r = requests.get(f'{BASE}/api/chat/history?connection_id=3&limit=50', headers=h1)
    print(f"  History count: {len(r.json())}")

    # 3. Insert test history via DB (simulating what _save_chat_history does)
    print("\n=== Step 3: Insert test history via DB ===")
    from app.database import SessionLocal
    from app.models import ChatHistory
    db = SessionLocal()
    entry = ChatHistory(
        user_id=3, connection_id=3,
        prompt="Show me all artists",
        answer="Here are all the artists from the database:",
        sql="SELECT * FROM artists LIMIT 5",
        columns=json.dumps(["ArtistId", "Name"]),
        rows=json.dumps([{"ArtistId": 1, "Name": "AC/DC"}, {"ArtistId": 2, "Name": "Accept"}]),
        row_count=2,
        execution_time_ms=150,
        selected_tables=json.dumps(["artists"]),
        status="success"
    )
    db.add(entry)
    db.commit()
    entry_id = entry.id
    print(f"  Inserted entry id={entry_id}")
    db.close()

    # 4. Check history with same token
    print("\n=== Step 4: Check history after insert ===")
    r = requests.get(f'{BASE}/api/chat/history?connection_id=3&limit=50', headers=h1)
    items = r.json()
    print(f"  History count: {len(items)}")
    for it in items:
        print(f"    prompt='{it['prompt'][:40]}', status={it['status']}, rows={len(it.get('rows') or [])}")

    # 5. Simulate logout + re-login
    print("\n=== Step 5: Re-login as Saurav (new token) ===")
    r = requests.post(f'{BASE}/api/auth/login', json={'username': 'Saurav', 'password': 'Saurav123'})
    token2 = r.json()['access_token']
    h2 = {'Authorization': f'Bearer {token2}', 'Content-Type': 'application/json'}
    print(f"  OK, got new token")

    # 6. Check history persists with new token
    print("\n=== Step 6: Check history with new token ===")
    r = requests.get(f'{BASE}/api/chat/history?connection_id=3&limit=50', headers=h2)
    items = r.json()
    print(f"  History count: {len(items)}")
    for it in items:
        print(f"    prompt='{it['prompt'][:40]}', status={it['status']}, rows={len(it.get('rows') or [])}")

    # 7. Cleanup
    print("\n=== Step 7: Cleanup test data ===")
    db = SessionLocal()
    db.query(ChatHistory).filter(ChatHistory.id == entry_id).delete()
    db.commit()
    db.close()
    print(f"  Deleted test entry id={entry_id}")

    if len(items) > 0:
        print("\n✅ SUCCESS: Chat history persists across logins!")
    else:
        print("\n❌ FAILURE: Chat history NOT persisting!")

if __name__ == '__main__':
    main()
