#!/usr/bin/env python3
"""Simple script to verify connectivity to a Postgres database and list basic info.

Example:
  python scripts/check_remote_db.py \
    --host db.chinookdatabase.com --port 5432 --database Chinook \
    --user postgres --password postgres --sslmode require
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

import psycopg2
import psycopg2.extras


def connect_and_probe(host: str, port: int, database: str, user: str, password: str, sslmode: str, timeout: int = 10) -> Dict[str, Any]:
    conn = None
    out: Dict[str, Any] = {"ok": False}
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
            sslmode=sslmode,
            connect_timeout=timeout,
        )

        cur = conn.cursor()

        # Basic ping
        cur.execute("SELECT 1;")
        ping = cur.fetchone()[0]

        # Server version
        cur.execute("SELECT version();")
        version = cur.fetchone()[0]

        # List public tables (limit)
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
            LIMIT 200
        """)
        tables = [r[0] for r in cur.fetchall()]

        # Try to fetch small sample from a common table if present
        samples = {}
        lc_tables = [t.lower() for t in tables]
        sample_targets = ["artist", "artists", "album", "albums", "customers", "customer"]
        for target in sample_targets:
            for t in tables:
                if t.lower() == target:
                    try:
                        cur.execute(f"SELECT * FROM \"{t}\" LIMIT 5;")
                        cols = [d[0] for d in cur.description]
                        rows = cur.fetchall()
                        samples[t] = {"columns": cols, "rows": rows}
                    except Exception:
                        samples[t] = {"error": "could not fetch sample"}
                    break
            if samples:
                break

        out.update({
            "ok": True,
            "ping": ping,
            "version": version,
            "tables_count": len(tables),
            "tables": tables,
            "samples": samples,
        })

        cur.close()
        return out

    except Exception as e:  # pragma: no cover - runtime error reporting
        out["error"] = str(e)
        return out

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check connectivity to a Postgres database")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--database", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--sslmode", default="require", choices=["disable", "allow", "prefer", "require", "verify-ca", "verify-full"])
    parser.add_argument("--timeout", type=int, default=10)

    args = parser.parse_args(argv)

    result = connect_and_probe(
        host=args.host,
        port=args.port,
        database=args.database,
        user=args.user,
        password=args.password,
        sslmode=args.sslmode,
        timeout=args.timeout,
    )

    if result.get("ok"):
        print(json.dumps(result, default=str, indent=2))
        return 0
    else:
        print(json.dumps(result, default=str, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
