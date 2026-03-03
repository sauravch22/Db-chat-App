"""
Example: Testing the Visualization Service
"""

import requests
import json

BASE_URL = "http://localhost:8001"

def test_health():
    """Test health endpoint"""
    response = requests.get(f"{BASE_URL}/health")
    print("Health Check:", response.json())
    print()

def test_category_numeric():
    """Test: Category + Numeric → Bar + Pie"""
    data = {
        "data": {
            "columns": [
                {"name": "billing_country", "type": "VARCHAR"},
                {"name": "total", "type": "NUMERIC"}
            ],
            "rows": [
                {"billing_country": "USA", "total": 50000},
                {"billing_country": "India", "total": 20000},
                {"billing_country": "UK", "total": 15000}
            ]
        },
        "max_recommendations": 3
    }
    
    response = requests.post(f"{BASE_URL}/analyze", json=data)
    result = response.json()
    
    print("=" * 80)
    print("TEST: Category + Numeric")
    print("=" * 80)
    print(f"Status: {result['status']}")
    print(f"\nData Summary:")
    print(json.dumps(result['data_summary'], indent=2))
    print(f"\nRecommendations ({len(result['recommendations'])}):")
    for rec in result['recommendations']:
        print(f"  {rec['priority']}. {rec['chart_type'].upper()}: {rec['title']}")
        print(f"     Reason: {rec['reason']}")
    print()

def test_time_series():
    """Test: Time + Numeric → Line"""
    data = {
        "data": {
            "columns": [
                {"name": "invoice_date", "type": "TIMESTAMP"},
                {"name": "total", "type": "NUMERIC"}
            ],
            "rows": [
                {"invoice_date": "2024-01-01", "total": 1000},
                {"invoice_date": "2024-02-01", "total": 1500},
                {"invoice_date": "2024-03-01", "total": 2000}
            ]
        },
        "max_recommendations": 2
    }
    
    response = requests.post(f"{BASE_URL}/analyze", json=data)
    result = response.json()
    
    print("=" * 80)
    print("TEST: Time Series")
    print("=" * 80)
    print(f"Status: {result['status']}")
    print(f"\nRecommendations:")
    for rec in result['recommendations']:
        print(f"  {rec['priority']}. {rec['chart_type'].upper()}: {rec['title']}")
        print(f"     Config: {json.dumps(rec['config'], indent=6)}")
    print()

def test_single_kpi():
    """Test: Single Numeric → KPI"""
    data = {
        "data": {
            "columns": [
                {"name": "total_revenue", "type": "NUMERIC"}
            ],
            "rows": [
                {"total_revenue": 123456.78}
            ]
        },
        "max_recommendations": 1
    }
    
    response = requests.post(f"{BASE_URL}/analyze", json=data)
    result = response.json()
    
    print("=" * 80)
    print("TEST: Single KPI")
    print("=" * 80)
    print(f"Status: {result['status']}")
    print(f"\nRecommendations:")
    for rec in result['recommendations']:
        print(f"  {rec['chart_type'].upper()}: {rec['title']}")
        print(f"  Value: {rec['config']['value']}")
    print()

def test_multi_category():
    """Test: 2 Categories + Numeric → Grouped Bar"""
    data = {
        "data": {
            "columns": [
                {"name": "country", "type": "VARCHAR"},
                {"name": "genre", "type": "VARCHAR"},
                {"name": "revenue", "type": "NUMERIC"}
            ],
            "rows": [
                {"country": "USA", "genre": "Rock", "revenue": 10000},
                {"country": "USA", "genre": "Jazz", "revenue": 5000},
                {"country": "India", "genre": "Rock", "revenue": 8000},
                {"country": "India", "genre": "Jazz", "revenue": 3000}
            ]
        },
        "max_recommendations": 2
    }
    
    response = requests.post(f"{BASE_URL}/analyze", json=data)
    result = response.json()
    
    print("=" * 80)
    print("TEST: Multiple Categories")
    print("=" * 80)
    print(f"Status: {result['status']}")
    print(f"\nData Summary: {result['data_summary']['category_columns']}")
    print(f"\nRecommendations:")
    for rec in result['recommendations']:
        print(f"  {rec['priority']}. {rec['chart_type'].upper()}")
        print(f"     {rec['reason']}")
    print()

if __name__ == "__main__":
    try:
        print("\n🚀 Testing DbChat Visualization Service\n")
        
        test_health()
        test_single_kpi()
        test_category_numeric()
        test_time_series()
        test_multi_category()
        
        print("✅ All tests completed!")
        
    except requests.exceptions.ConnectionError:
        print("❌ Error: Cannot connect to visualization service")
        print("   Make sure the service is running: uvicorn app:app --port 8001")
    except Exception as e:
        print(f"❌ Error: {e}")
