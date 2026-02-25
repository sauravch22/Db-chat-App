#!/bin/bash

# v2 Pipeline Validation Tests
# Validates table selection + SQL generation for multi-table queries

set -e

BASE_URL="http://localhost:8000"
CONNECTION_ID=3

fail() {
  echo "[FAIL] $1"
  exit 1
}

pass() {
  echo "[PASS] $1"
}

echo "Running v2 pipeline validation tests..."

# 1) Multi-table join should include customer + invoice
resp=$(curl -s -X POST "$BASE_URL/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"connection_id": 3, "prompt": "Show customers with their total purchases", "top_k_tables": 5}')
status=$(echo "$resp" | jq -r '.status')
sql=$(echo "$resp" | jq -r '.sql')
if [[ "$status" != "success" ]]; then
  fail "customers with purchases (status=$status)"
fi
if ! echo "$sql" | grep -Eqi "\bcustomer\b" || ! echo "$sql" | grep -Eqi "\binvoice\b"; then
  fail "customers with purchases (sql missing expected tables)"
fi
pass "customers with purchases"

# 2) Revenue by genre should include genre + invoice_line + track
resp=$(curl -s -X POST "$BASE_URL/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"connection_id": 3, "prompt": "Most popular genre by total revenue", "top_k_tables": 8}')
status=$(echo "$resp" | jq -r '.status')
sql=$(echo "$resp" | jq -r '.sql')
if [[ "$status" != "success" ]]; then
  fail "popular genre by revenue (status=$status)"
fi
if ! echo "$sql" | grep -Eqi "\bgenre\b" || ! echo "$sql" | grep -Eqi "\binvoice_line\b" || ! echo "$sql" | grep -Eqi "\btrack\b"; then
  fail "popular genre by revenue (sql missing expected tables)"
fi
pass "popular genre by revenue"

# 3) Employee hierarchy should include employee table
resp=$(curl -s -X POST "$BASE_URL/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"connection_id": 3, "prompt": "Show the employee reporting hierarchy", "top_k_tables": 5}')
status=$(echo "$resp" | jq -r '.status')
sql=$(echo "$resp" | jq -r '.sql')
if [[ "$status" != "success" ]]; then
  fail "employee hierarchy (status=$status)"
fi
if ! echo "$sql" | grep -Eqi "\bemployee\b"; then
  fail "employee hierarchy (sql missing employee table)"
fi
pass "employee hierarchy"

echo "All v2 pipeline tests passed."
