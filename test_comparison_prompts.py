#!/usr/bin/env python3
"""
Test suite for 20 comparison prompts against Chinook database
"""

import requests
import json
import time
from typing import Tuple

BASE_URL = "http://localhost:8000"
CONNECTION_ID = 3
TIMEOUT = 180  # 3 minutes for reasoning mode for slow queries/LLM regeneration

# ANSI color codes
GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color

def test_prompt(test_num: int, prompt: str) -> Tuple[bool, str, int]:
    """Test a single prompt and return (passed, error_msg, row_count)"""
    try:
        start_time = time.time()
        
        response = requests.post(
            f"{BASE_URL}/api/chat",
            json={"connection_id": CONNECTION_ID, "prompt": prompt},
            timeout=TIMEOUT
        )
        
        duration = time.time() - start_time
        
        data = response.json()
        status = data.get('status', 'unknown')
        row_count = data.get('row_count', 0)
        error = data.get('error', 'unknown error')
        
        if status == 'success':
            return True, "", row_count, duration
        else:
            return False, error, 0, duration
            
    except Exception as e:
        return False, str(e), 0, 0

def main():
    prompts = [
        # Customer comparison prompts (5)
        ("1. Latest invoice > avg invoice", 
         "Find customers whose latest invoice total is higher than their average invoice total."),
        ("2. Total spending > avg spending",
         "Find customers whose total spending is greater than the average spending of all customers."),
        ("3. 2013 spending > 2012 spending",
         "Find customers who spent more in 2013 compared to 2012."),
        ("4. Max invoice >= 2x min invoice",
         "Find customers whose maximum invoice is at least 2 times their minimum invoice."),
        ("5. First invoice < last invoice",
         "Find customers whose first invoice value is less than their last invoice value."),
        
        # Track / Genre comparison prompts (4)
        ("6. Genre revenue > avg genre revenue",
         "Find genres whose total revenue is higher than the average genre revenue."),
        ("7. Track length > avg in album",
         "Find tracks whose length is longer than the average track length in their album."),
        ("8. Album duration > avg album duration",
         "Find albums whose total duration is greater than the average album duration."),
        ("9. Track price > avg in genre",
         "Find tracks whose price is higher than the average price of tracks in the same genre."),
        
        # Artist comparison prompts (3)
        ("10. Artist revenue > avg artist revenue",
         "Find artists whose total revenue is higher than the average revenue of all artists."),
        ("11. Artist tracks > avg tracks per artist",
         "Find artists who have more tracks than the average number of tracks per artist."),
        ("12. Longest track > avg longest",
         "Find artists whose longest track is longer than the average longest track across artists."),
        
        # Country comparison prompts (3)
        ("13. Country revenue > avg per country",
         "Find countries whose total revenue is higher than the average revenue per country."),
        ("14. Highest invoice > global avg",
         "Find countries where the highest invoice total is greater than the global average invoice total."),
        ("15. Customer count > avg per country",
         "Find countries whose number of customers is higher than the average number of customers per country."),
        
        # Advanced comparison prompts (5)
        ("16. Customers with more genres than avg",
         "Find customers who purchased tracks from more genres than the average customer."),
        ("17. Album revenue > avg for artist",
         "Find albums whose revenue is higher than the average revenue of albums by the same artist."),
        ("18. Invoice > avg for customer's country",
         "Find invoices whose total is greater than the average invoice total for that customer's country."),
        ("19. Employees supporting > avg customers",
         "Find employees who support more customers than the average employee."),
        ("20. Tracks with > avg sales in genre",
         "Find tracks whose sales count is higher than the average sales count of tracks in the same genre."),
    ]
    
    print(f"\n{BLUE}{'='*70}")
    print("TESTING 20 COMPARISON PROMPTS - CHINOOK DATABASE")
    print(f"{'='*70}{NC}\n")
    
    passed = 0
    failed = 0
    results = []
    
    for i, (label, prompt) in enumerate(prompts, 1):
        success, error, row_count, duration = test_prompt(i, prompt)
        
        status_str = f"{GREEN}✓ PASS{NC}" if success else f"{RED}✗ FAIL{NC}"
        duration_str = f"{duration:.2f}s"
        rows_str = f"{row_count} rows" if success else error[:60]
        
        print(f"{status_str} | {label:<45} | {duration_str:>7} | {rows_str}")
        
        if success:
            passed += 1
        else:
            failed += 1
        
        results.append({
            'test_num': i,
            'label': label,
            'prompt': prompt,
            'passed': success,
            'error': error,
            'row_count': row_count,
            'duration': duration
        })
        
        # Small delay between requests
        time.sleep(0.5)
    
    # Summary
    pct = (passed * 100) // 20 if 20 > 0 else 0
    print(f"\n{BLUE}{'='*70}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*70}{NC}")
    print(f"Total Tests:  20")
    print(f"Passed:       {GREEN}{passed}{NC}")
    print(f"Failed:       {RED}{failed}{NC}")
    print(f"Success Rate: {pct}%")
    print(f"{'='*70}\n")
    
    # Show failures
    if failed > 0:
        print(f"\n{YELLOW}FAILED TESTS:{NC}\n")
        for r in results:
            if not r['passed']:
                print(f"Test {r['test_num']}: {r['label']}")
                print(f"  Error: {r['error'][:100]}")
                print()
    
    # Save detailed results
    with open('/tmp/comparison_test_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Detailed results saved to: /tmp/comparison_test_results.json\n")
    
    return passed, failed

if __name__ == "__main__":
    passed, failed = main()
    exit(0 if failed == 0 else 1)
