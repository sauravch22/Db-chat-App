#!/usr/bin/env python3
"""
Debug a single test case to understand the full flow
"""

import requests
import json

BASE_URL = "http://localhost:8000"
CONNECTION_ID = 3

# Test case 2: "Total spending > avg spending"
prompt = "Find customers whose total spending is higher than the average customer spending"

print("=" * 80)
print(f"DEBUGGING TEST CASE: {prompt}")
print("=" * 80)

response = requests.post(
    f"{BASE_URL}/api/chat",
    json={"connection_id": CONNECTION_ID, "prompt": prompt},
    timeout=180
)

data = response.json()

print("\n" + "=" * 80)
print("RESPONSE DETAILS:")
print("=" * 80)

print(f"\nStatus: {data.get('status')}")
print(f"Row Count: {data.get('row_count', 0)}")
print(f"Execution Time: {data.get('execution_time_ms', 0)}ms")

if data.get('sql'):
    print(f"\nGenerated SQL:\n{data['sql']}")

if data.get('error'):
    print(f"\nError:\n{data['error']}")

if data.get('selected_tables'):
    print(f"\nSelected Tables: {data['selected_tables']}")

if data.get('schema_context'):
    print(f"\nSchema Context:\n{data['schema_context'][:1000]}...")  # First 1000 chars

print("\n" + "=" * 80)
print("FULL RESPONSE JSON:")
print("=" * 80)
print(json.dumps(data, indent=2))
