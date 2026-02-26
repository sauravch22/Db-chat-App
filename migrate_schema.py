#!/usr/bin/env python3
"""
Database schema migration: Add summary fields to tables table
"""
from app.database import engine
from sqlalchemy import text

def migrate():
    """Execute schema migration"""
    with engine.connect() as conn:
        # Check if columns exist
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name='tables' AND column_name IN ('summary', 'summary_generated_at', 'summary_human_override')
        """))
        existing = [row[0] for row in result]
        print(f"Existing columns: {existing}")
        
        # Add missing columns
        if 'summary' not in existing:
            print("Adding summary column...")
            conn.execute(text("ALTER TABLE tables ADD COLUMN summary TEXT"))
        
        if 'summary_generated_at' not in existing:
            print("Adding summary_generated_at column...")
            conn.execute(text("ALTER TABLE tables ADD COLUMN summary_generated_at TIMESTAMP"))
        
        if 'summary_human_override' not in existing:
            print("Adding summary_human_override column...")
            conn.execute(text("ALTER TABLE tables ADD COLUMN summary_human_override BOOLEAN DEFAULT FALSE"))
        
        conn.commit()
        print("✓ Migration complete!")

if __name__ == "__main__":
    migrate()
