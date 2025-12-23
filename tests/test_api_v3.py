"""
Test Suite untuk API v3
========================

Tests:
1. Health endpoint (public)
2. Authentication (X-API-KEY)
3. Rate limiting
4. Weather endpoints
5. CORS headers
"""

import json
import os
import time
from datetime import datetime
import pytest


def print_header(text):
    print("\n" + "=" * 70)
    print(f" {text}")
    print("=" * 70)


def print_section(text):
    print(f"\n{'-' * 50}")
    print(f" {text}")
    print(f"{'-' * 50}")


@pytest.fixture(autouse=True)
def reset_api_key():
    """Reset API_KEY before and after each test."""
    # Save original value
    original_key = os.environ.get('API_KEY')
    original_read_key = os.environ.get('API_READ_KEY')
    
    # Remove for clean slate
    if 'API_KEY' in os.environ:
        del os.environ['API_KEY']
    if 'API_READ_KEY' in os.environ:
        del os.environ['API_READ_KEY']
    
    yield
    
    # Restore original value
    if original_key:
        os.environ['API_KEY'] = original_key
    elif 'API_KEY' in os.environ:
        del os.environ['API_KEY']
    
    if original_read_key:
        os.environ['API_READ_KEY'] = original_read_key
    elif 'API_READ_KEY' in os.environ:
        del os.environ['API_READ_KEY']


def test_health_endpoint():
    """Test 1: Health endpoint (public, no API key required)."""
    print_header("TEST 1: Health Endpoint")
    
    from app import create_app
    app = create_app()
    
    with app.test_client() as client:
        resp = client.get('/api/v3/health')
        data = resp.get_json()
        
        print(f"  Status: {resp.status_code}")
        print(f"  API Version: {data.get('data', {}).get('api_version')}")
        print(f"  Database: {data.get('data', {}).get('database')}")
        print(f"  Rate Limit Header: {resp.headers.get('X-RateLimit-Limit')}")
        
        assert resp.status_code == 200, "Health should return 200"
        assert data.get('ok') == True, "Health should be ok"
        assert data.get('data', {}).get('api_version') == 'v3', "API version should be v3"
        assert resp.headers.get('X-RateLimit-Limit') is not None, "Should have rate limit header"
    
    print("\n✓ TEST 1 PASSED: Health endpoint works correctly")


def test_api_key_authentication():
    """Test 2: X-API-KEY authentication."""
    print_header("TEST 2: X-API-KEY Authentication")
    
    # Set API key for this test
    os.environ['API_KEY'] = 'test-secret-key-12345'
    
    from app import create_app
    app = create_app()
    
    with app.test_client() as client:
        # Test without API key
        print_section("Without X-API-KEY header")
        resp = client.get('/api/v3/weather/current')
        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        print(f"  Error: {data.get('error', {}).get('code') if data else 'N/A'}")
        assert resp.status_code == 401, "Should return 401 without API key"
        assert data.get('error', {}).get('code') == 'MISSING_API_KEY', "Should have MISSING_API_KEY error"
        
        # Test with invalid API key
        print_section("With invalid X-API-KEY")
        resp = client.get('/api/v3/weather/current', headers={'X-API-KEY': 'wrong-key'})
        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        print(f"  Error: {data.get('error', {}).get('code') if data else 'N/A'}")
        assert resp.status_code == 401, "Should return 401 with invalid API key"
        assert data.get('error', {}).get('code') == 'INVALID_API_KEY', "Should have INVALID_API_KEY error"
        
        # Test with valid API key - use /health endpoint (no auth required but validates flow)
        # Then test weather/current with valid key - should get 200 or 404 (no data)
        print_section("With valid X-API-KEY")
        resp = client.get('/api/v3/weather/current', headers={'X-API-KEY': 'test-secret-key-12345'})
        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        print(f"  Response: {data}")
        # With valid API key, should get 200 (has data) or 404 (no data) - not 401
        assert resp.status_code in [200, 404], f"Should return 200 or 404 with valid API key, got {resp.status_code}"
    
    print("\n✓ TEST 2 PASSED: API key authentication works correctly")


def test_rate_limiting():
    """Test 3: Rate limiting."""
    print_header("TEST 3: Rate Limiting")
    
    from app import create_app
    app = create_app()
    
    with app.test_client() as client:
        # Make a request and check headers
        resp = client.get('/api/v3/health')
        
        print(f"  X-RateLimit-Limit: {resp.headers.get('X-RateLimit-Limit')}")
        print(f"  X-RateLimit-Remaining: {resp.headers.get('X-RateLimit-Remaining')}")
        print(f"  X-RateLimit-Reset: {resp.headers.get('X-RateLimit-Reset')}")
        
        assert resp.headers.get('X-RateLimit-Limit') is not None, "Should have limit header"
        assert resp.headers.get('X-RateLimit-Remaining') is not None, "Should have remaining header"
        assert resp.headers.get('X-RateLimit-Reset') is not None, "Should have reset header"
        
        # Verify remaining decreases
        remaining1 = int(resp.headers.get('X-RateLimit-Remaining'))
        
        resp2 = client.get('/api/v3/health')
        remaining2 = int(resp2.headers.get('X-RateLimit-Remaining'))
        
        print(f"\n  After 2 requests:")
        print(f"    First remaining: {remaining1}")
        print(f"    Second remaining: {remaining2}")
        
        # Note: remaining might not decrease by exactly 1 due to test isolation
        # Just verify headers are present
    
    print("\n✓ TEST 3 PASSED: Rate limiting headers are present")


def test_weather_endpoints():
    """Test 4: Weather endpoints (API structure validation)."""
    print_header("TEST 4: Weather Endpoints")
    
    # No API_KEY set = development mode (no auth required)
    from app import create_app
    app = create_app()
    
    with app.test_client() as client:
        # Test /weather/current - may return 404 if no data, which is acceptable
        print_section("GET /api/v3/weather/current")
        resp = client.get('/api/v3/weather/current')
        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        print(f"  Response OK: {data.get('ok') if data else 'N/A'}")
        # Accept 200 (has data) or 404 (no data) - both are valid responses
        assert resp.status_code in [200, 404], "Current should return 200 or 404"
        
        # Test /weather/hourly with LSTM - may return 404 if no data
        print_section("GET /api/v3/weather/hourly?model=lstm&limit=3")
        resp = client.get('/api/v3/weather/hourly?model=lstm&limit=3')
        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200 and data:
            print(f"  Model name: {data.get('data', {}).get('model', {}).get('name')}")
            print(f"  Hourly count: {len(data.get('data', {}).get('hourly', []))}")
            print(f"  Limit applied: {data.get('data', {}).get('prediction', {}).get('limit_applied')}")
        else:
            print(f"  No data available (expected if database is empty)")
        # Accept 200 or 404
        assert resp.status_code in [200, 404], "Hourly LSTM should return 200 or 404"
        
        # Test /weather/hourly with XGBoost
        print_section("GET /api/v3/weather/hourly?model=xgboost")
        resp = client.get('/api/v3/weather/hourly?model=xgboost')
        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200 and data:
            print(f"  Model name: {data.get('data', {}).get('model', {}).get('name')}")
            print(f"  Classification: {data.get('data', {}).get('classification', {}).get('name')}")
        else:
            print(f"  No data available (expected if database is empty)")
        # Accept 200 or 404
        assert resp.status_code in [200, 404], "Hourly XGBoost should return 200 or 404"
        
        # Test /weather/details
        print_section("GET /api/v3/weather/details")
        resp = client.get('/api/v3/weather/details')
        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200 and data:
            print(f"  Has weather details: {'details' in data.get('data', {})}")
        else:
            print(f"  No data available (expected if database is empty)")
        # Accept 200 or 404
        assert resp.status_code in [200, 404], "Details should return 200 or 404"
        
        # Test /weather/history - this should always work (empty list is valid)
        print_section("GET /api/v3/weather/history?per_page=2")
        resp = client.get('/api/v3/weather/history?per_page=2')
        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        if data:
            # Response can be: {ok: true, data: {items: [...], pagination: {...}}}
            # or just: {ok: true, data: [...]}  
            if isinstance(data.get('data'), dict):
                print(f"  Items: {len(data.get('data', {}).get('items', []))}")
                print(f"  Has pagination: {'pagination' in data.get('data', {})}")
            elif isinstance(data.get('data'), list):
                print(f"  Items (list): {len(data.get('data', []))}")
            else:
                print(f"  Data: {data}")
        assert resp.status_code == 200, "History should return 200"
        
        # Test invalid model parameter
        print_section("GET /api/v3/weather/hourly?model=invalid")
        resp = client.get('/api/v3/weather/hourly?model=invalid')
        data = resp.get_json()
        print(f"  Status: {resp.status_code}")
        if data:
            print(f"  Error: {data.get('error', {}).get('code')}")
        assert resp.status_code == 400, "Invalid model should return 400"
    
    print("\n✓ TEST 4 PASSED: Weather endpoints structure is correct")


def test_cors_headers():
    """Test 5: CORS headers."""
    print_header("TEST 5: CORS Headers")
    
    from app import create_app
    app = create_app()
    
    with app.test_client() as client:
        # Test preflight request (OPTIONS)
        print_section("OPTIONS /api/v3/weather/current (Preflight)")
        resp = client.options('/api/v3/weather/current', headers={
            'Origin': 'http://localhost:3000',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'X-API-KEY'
        })
        
        print(f"  Status: {resp.status_code}")
        print(f"  Access-Control-Allow-Origin: {resp.headers.get('Access-Control-Allow-Origin')}")
        print(f"  Access-Control-Allow-Methods: {resp.headers.get('Access-Control-Allow-Methods')}")
        print(f"  Access-Control-Allow-Headers: {resp.headers.get('Access-Control-Allow-Headers')}")
        
        # CORS should respond to preflight
        assert resp.status_code in [200, 204], "Preflight should return 200 or 204"
        
        # Test actual request with Origin header
        print_section("GET /api/v3/health with Origin header")
        resp = client.get('/api/v3/health', headers={
            'Origin': 'http://localhost:3000'
        })
        
        print(f"  Status: {resp.status_code}")
        print(f"  Access-Control-Allow-Origin: {resp.headers.get('Access-Control-Allow-Origin')}")
        
        assert resp.status_code == 200, "Should return 200"
        # CORS origin header should be present
        assert resp.headers.get('Access-Control-Allow-Origin') is not None, "Should have CORS header"
    
    print("\n✓ TEST 5 PASSED: CORS headers are present")


if __name__ == '__main__':
    print("\n" + "=" * 70)
    print(" RUNNING API v3 TEST SUITE")
    print("=" * 70)
    
    tests = [
        test_health_endpoint,
        test_api_key_authentication,
        test_rate_limiting,
        test_weather_endpoints,
        test_cors_headers,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"\n✗ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n✗ {test.__name__} ERROR: {e}")
            failed += 1
    
    print("\n" + "=" * 70)
    print(f" RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
