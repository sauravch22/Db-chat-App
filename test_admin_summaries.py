#!/usr/bin/env python3
"""
Test suite for admin summary management endpoints:
1. GET /api/admin/summaries/{connection_id}
2. PUT /api/admin/summaries/{table_id}
3. POST /api/admin/refresh-data-embeddings/{connection_id}
"""

import requests
import json
import time
from typing import Dict, Any

BASE_URL = "http://localhost:8000"
CONNECTION_ID = 3  # Chinook database

# ANSI colors
GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color


def print_header(title: str):
    print(f"\n{BLUE}{'='*70}")
    print(f"{title}")
    print(f"{'='*70}{NC}\n")


def test_get_summaries():
    """Test GET /api/admin/summaries/{connection_id}"""
    print_header("TEST 1: GET /api/admin/summaries/{connection_id}")
    
    try:
        url = f"{BASE_URL}/api/admin/summaries/{CONNECTION_ID}"
        print(f"Endpoint: {url}\n")
        
        response = requests.get(url, timeout=10)
        
        print(f"Status: {response.status_code}")
        print(f"Response Time: {response.elapsed.total_seconds():.2f}s\n")
        
        if response.status_code == 200:
            data = response.json()
            print(f"{GREEN}✓ SUCCESS{NC}")
            print(f"Connection: {data.get('connection_id')}")
            print(f"Database: {data.get('database_name')}")
            print(f"Total Tables: {data.get('total')}\n")
            
            summaries = data.get('summaries', [])
            print(f"Sample Tables (first 3):")
            for i, summary in enumerate(summaries[:3]):
                print(f"\n  [{i+1}] {summary.get('table_name')}")
                print(f"      ID: {summary.get('table_id')}")
                print(f"      Summary: {summary.get('summary', 'NOT SET')[:80] if summary.get('summary') else 'NOT SET'}...")
                print(f"      Human Override: {summary.get('summary_human_override')}")
                print(f"      Columns: {summary.get('column_count')}")
            
            return True
        else:
            print(f"{RED}✗ FAILED{NC} - Status {response.status_code}")
            print(f"Response: {response.text}")
            return False
    
    except Exception as e:
        print(f"{RED}✗ EXCEPTION{NC}: {str(e)}")
        return False


def test_update_summary():
    """Test PUT /api/admin/summaries/{table_id}"""
    print_header("TEST 2: PUT /api/admin/summaries/{table_id}")
    
    try:
        # First get the summaries to find a table
        url = f"{BASE_URL}/api/admin/summaries/{CONNECTION_ID}"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            print(f"{RED}✗ Could not fetch summaries{NC}")
            return False
        
        data = response.json()
        summaries = data.get('summaries', [])
        
        if not summaries:
            print(f"{RED}✗ No tables found{NC}")
            return False
        
        # Pick the first table
        table = summaries[0]
        table_id = table.get('table_id')
        table_name = table.get('table_name')
        
        print(f"Updating table: {table_name} (ID: {table_id})\n")
        
        # Update the summary
        new_summary = f"Updated summary for {table_name} - Test update at {time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        update_url = f"{BASE_URL}/api/admin/summaries/{table_id}"
        update_data = {
            "summary": new_summary,
            "is_human_override": True
        }
        
        print(f"Endpoint: {update_url}")
        print(f"Payload: {json.dumps(update_data, indent=2)}\n")
        
        update_response = requests.put(update_url, json=update_data, timeout=10)
        
        print(f"Status: {update_response.status_code}")
        print(f"Response Time: {update_response.elapsed.total_seconds():.2f}s\n")
        
        if update_response.status_code == 200:
            result = update_response.json()
            print(f"{GREEN}✓ SUCCESS{NC}")
            print(f"Updated summary: {result.get('summary')[:80]}...")
            print(f"Human override: {result.get('human_override')}")
            print(f"Updated at: {result.get('updated_at')}")
            
            return True
        else:
            print(f"{RED}✗ FAILED{NC} - Status {update_response.status_code}")
            print(f"Response: {update_response.text}")
            return False
    
    except Exception as e:
        print(f"{RED}✗ EXCEPTION{NC}: {str(e)}")
        return False


def test_refresh_data_embeddings():
    """Test POST /api/admin/refresh-data-embeddings/{connection_id}"""
    print_header("TEST 3: POST /api/admin/refresh-data-embeddings/{connection_id}")
    
    try:
        url = f"{BASE_URL}/api/admin/refresh-data-embeddings/{CONNECTION_ID}"
        print(f"Endpoint: {url}\n")
        
        # Test 3a: Dry run
        print(f"{YELLOW}[3a] Testing DRY RUN{NC}\n")
        
        dry_run_data = {
            "refresh_mode": "full",
            "dry_run": True
        }
        
        print(f"Payload: {json.dumps(dry_run_data, indent=2)}\n")
        
        dry_response = requests.post(url, json=dry_run_data, timeout=10)
        
        print(f"Status: {dry_response.status_code}")
        print(f"Response Time: {dry_response.elapsed.total_seconds():.2f}s\n")
        
        if dry_response.status_code == 200:
            result = dry_response.json()
            print(f"{GREEN}✓ DRY RUN SUCCESS{NC}")
            print(f"Affected tables: {result.get('affected_tables')}")
            print(f"Affected columns: {result.get('affected_columns')}")
            print(f"Message: {result.get('message')}")
        else:
            print(f"{RED}✗ DRY RUN FAILED{NC} - Status {dry_response.status_code}")
            print(f"Response: {dry_response.text}")
            return False
        
        # Test 3b: Actual refresh
        print(f"\n{YELLOW}[3b] Testing ACTUAL REFRESH{NC}\n")
        
        refresh_data = {
            "refresh_mode": "full",
            "dry_run": False
        }
        
        print(f"Payload: {json.dumps(refresh_data, indent=2)}\n")
        
        refresh_response = requests.post(url, json=refresh_data, timeout=10)
        
        print(f"Status: {refresh_response.status_code}")
        print(f"Response Time: {refresh_response.elapsed.total_seconds():.2f}s\n")
        
        if refresh_response.status_code == 200:
            result = refresh_response.json()
            print(f"{GREEN}✓ REFRESH SCHEDULED{NC}")
            print(f"Status: {result.get('status')}")
            print(f"Estimated duration: {result.get('estimated_duration_seconds')}s")
            print(f"Message: {result.get('message')}")
            
            return True
        else:
            print(f"{RED}✗ REFRESH FAILED{NC} - Status {refresh_response.status_code}")
            print(f"Response: {refresh_response.text}")
            return False
    
    except Exception as e:
        print(f"{RED}✗ EXCEPTION{NC}: {str(e)}")
        return False


def main():
    print(f"\n{BLUE}{'='*70}")
    print("ADMIN SUMMARY MANAGEMENT ENDPOINTS - TEST SUITE")
    print(f"{'='*70}{NC}")
    print(f"Target: {BASE_URL}")
    print(f"Connection ID: {CONNECTION_ID}\n")
    
    # Run tests
    test1_pass = test_get_summaries()
    test2_pass = test_update_summary()
    test3_pass = test_refresh_data_embeddings()
    
    # Summary
    print_header("TEST SUMMARY")
    
    tests = [
        ("GET /api/admin/summaries/{connection_id}", test1_pass),
        ("PUT /api/admin/summaries/{table_id}", test2_pass),
        ("POST /api/admin/refresh-data-embeddings/{connection_id}", test3_pass)
    ]
    
    passed = sum(1 for _, result in tests if result)
    total = len(tests)
    
    for name, result in tests:
        status = f"{GREEN}✓{NC}" if result else f"{RED}✗{NC}"
        print(f"{status} {name}")
    
    print(f"\nTotal: {passed}/{total} passed")
    
    if passed == total:
        print(f"{GREEN}All tests PASSED!{NC}")
        return 0
    else:
        print(f"{RED}Some tests FAILED{NC}")
        return 1


if __name__ == "__main__":
    exit(main())
