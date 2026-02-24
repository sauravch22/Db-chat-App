#!/usr/bin/env python3
import psycopg2

# Check local test_db
print("=" * 50)
print("CHECKING LOCAL test_db DATABASE")
print("=" * 50)
try:
    conn = psycopg2.connect(
        host="127.0.0.1",
        user="dbchat",
        password="dbchat_secure_password",
        database="test_db",
        port=5432
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema='public' 
        ORDER BY table_name
    """)
    tables = cur.fetchall()
    if tables:
        print("Tables found:")
        for table in tables:
            print(f"  - {table[0]}")
    else:
        print("No tables found in test_db")
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error connecting to test_db: {e}")

# Check metadata records for Neon
print("\n" + "=" * 50)
print("CHECKING STORED TABLE METADATA")
print("=" * 50)
try:
    conn = psycopg2.connect(
        host="localhost",
        user="dbchat",
        password="dbchat_secure_password",
        database="dbchat_metadata",
        port=5432
    )
    cur = conn.cursor()
    
    # Check tables stored for connection_id=2 (test_db)
    print("\nTables indexed for LOCAL test_db (connection_id=2):")
    cur.execute("SELECT table_name FROM tables WHERE connection_id = 2 ORDER BY table_name;")
    local_tables = cur.fetchall()
    if local_tables:
        for table in local_tables:
            print(f"  - {table[0]}")
    else:
        print("  No tables indexed")
    
    # Check tables stored for connection_id=3 (Neon chinook)
    print("\nTables indexed for NEON chinook (connection_id=3):")
    cur.execute("SELECT table_name FROM tables WHERE connection_id = 3 ORDER BY table_name;")
    remote_tables = cur.fetchall()
    if remote_tables:
        for table in remote_tables:
            print(f"  - {table[0]}")
    else:
        print("  No tables indexed")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
