"""Direct test of ChatHistory insert."""
import json
from app.database import SessionLocal
from app.models import ChatHistory

db = SessionLocal()
try:
    entry = ChatHistory(
        user_id=1,
        connection_id=3,
        prompt="Test prompt",
        answer="Test answer",
        sql="SELECT 1",
        columns=json.dumps(["col1"]),
        rows=json.dumps([{"col1": "val1"}]),
        row_count=1,
        execution_time_ms=100,
        selected_tables=json.dumps(["test_table"]),
        status="success",
        error_message=None,
    )
    db.add(entry)
    db.commit()
    print(f"SUCCESS: Inserted row id={entry.id}")
    
    # Verify
    count = db.query(ChatHistory).count()
    print(f"Total rows now: {count}")
    
    # Clean up
    db.delete(entry)
    db.commit()
    print("Cleaned up test row")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
