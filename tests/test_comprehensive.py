"""
Comprehensive Backend Test Suite - TUWS Backend
================================================
Menguji seluruh aspek backend:
1. Module Imports
2. App Creation & Configuration
3. Database Connection
4. Cache Service
5. API Endpoints (Auth, Params, Responses)
6. Date/Time Validation
7. Security Headers
8. Error Handlers
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json

# Force development mode agar .env dimuat
os.environ['LOAD_DOTENV'] = 'true'
os.environ['DISABLE_SCHEDULER_FOR_TESTS'] = 'true'

PASSED = 0
FAILED = 0
ERRORS = []

def test(name, condition, detail=""):
    global PASSED, FAILED, ERRORS
    if condition:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  [FAIL] {name} -- {detail}")

print("=" * 70)
print("TUWS Backend - Comprehensive Test Suite")
print("=" * 70)

# ===================================================================
# SECTION 1: Module Imports
# ===================================================================
print("\n--- 1. MODULE IMPORTS ---")

try:
    from app import create_app, db, scheduler
    test("Import app (create_app, db, scheduler)", True)
except Exception as e:
    test("Import app", False, str(e))

try:
    from app import models
    test("Import models", True)
except Exception as e:
    test("Import models", False, str(e))

try:
    from app import serializers
    test("Import serializers", True)
except Exception as e:
    test("Import serializers", False, str(e))

try:
    from app.api_v3 import bp_v3
    test("Import api_v3 blueprint", True)
except Exception as e:
    test("Import api_v3", False, str(e))

try:
    from app.services.cache_service import get_cache_service
    test("Import cache_service", True)
except Exception as e:
    test("Import cache_service", False, str(e))

try:
    from app import cache
    test("Import cache module", True)
except Exception as e:
    test("Import cache module", False, str(e))

try:
    from app.common import helpers
    test("Import helpers", True)
except Exception as e:
    test("Import helpers", False, str(e))

try:
    from app.services.prediction_service import initialize_models
    test("Import prediction_service", True)
except Exception as e:
    test("Import prediction_service", False, str(e))

try:
    from app import jobs
    test("Import jobs", True)
except Exception as e:
    test("Import jobs", False, str(e))


# ===================================================================
# SECTION 2: App Creation & Configuration
# ===================================================================
print("\n--- 2. APP CREATION & CONFIGURATION ---")

try:
    app = create_app()
    test("App creation", app is not None)
except Exception as e:
    test("App creation", False, str(e))
    print("FATAL: Cannot continue without app. Exiting.")
    sys.exit(1)

with app.app_context():
    test("SECRET_KEY is set", bool(app.config.get('SECRET_KEY')))
    test("SECRET_KEY length >= 32", len(app.config.get('SECRET_KEY', '')) >= 32, 
         f"Length: {len(app.config.get('SECRET_KEY', ''))}")
    test("SQLALCHEMY_DATABASE_URI is set", bool(app.config.get('SQLALCHEMY_DATABASE_URI')))
    test("MAX_CONTENT_LENGTH = 1MB", app.config.get('MAX_CONTENT_LENGTH') == 1 * 1024 * 1024)
    test("TRAP_HTTP_EXCEPTIONS = True", app.config.get('TRAP_HTTP_EXCEPTIONS') is True)

    # ===================================================================
    # SECTION 3: Database Connection
    # ===================================================================
    print("\n--- 3. DATABASE CONNECTION ---")
    try:
        result = db.session.execute(db.text('SELECT 1')).scalar()
        test("Database connection", result == 1)
    except Exception as e:
        test("Database connection", False, str(e))

    try:
        eco_count = db.session.query(models.WeatherLogEcowitt).count()
        test(f"WeatherLogEcowitt table accessible (count: {eco_count})", True)
    except Exception as e:
        test("WeatherLogEcowitt table", False, str(e))

    try:
        wund_count = db.session.query(models.WeatherLogWunderground).count()
        test(f"WeatherLogWunderground table accessible (count: {wund_count})", True)
    except Exception as e:
        test("WeatherLogWunderground table", False, str(e))

    try:
        pred_count = db.session.query(models.PredictionLog).count()
        test(f"PredictionLog table accessible (count: {pred_count})", True)
    except Exception as e:
        test("PredictionLog table", False, str(e))

    # ===================================================================
    # SECTION 4: Cache Service
    # ===================================================================
    print("\n--- 4. CACHE SERVICE ---")
    try:
        svc = get_cache_service()
        test(f"Cache service init (backend: {svc.backend})", svc is not None)
    except Exception as e:
        test("Cache service init", False, str(e))

    try:
        cache.set("test_key", {"data": "hello"}, timeout=10)
        val = cache.get("test_key")
        test("Cache set/get", val is not None and val.get("data") == "hello", f"Got: {val}")
        cache.delete("test_key")
        val2 = cache.get("test_key")
        test("Cache delete", val2 is None)
    except Exception as e:
        test("Cache operations", False, str(e))


# ===================================================================
# SECTION 5: API Endpoints (Flask Test Client)
# ===================================================================
print("\n--- 5. API ENDPOINTS ---")

client = app.test_client()
APPKEY = os.environ.get('APPKEY', '')

# --- 5.1 Health (no auth) ---
print("  >> /health")
r = client.get('/api/v3/health')
test("GET /health status=200", r.status_code == 200)
data = r.get_json()
test("Health response has meta.status=success", data.get('meta', {}).get('status') == 'success')
test("Health response has data.database", 'database' in data.get('data', {}))

# --- 5.2 Auth Tests ---
print("  >> Auth Tests")
r = client.get('/api/v3/weather/current')
test("No auth => 401", r.status_code == 401)

r = client.get('/api/v3/weather/current', headers={'X-APP-KEY': 'wrong-key-12345'})
test("Wrong auth => 401", r.status_code == 401)

# --- 5.3 Current Weather ---
print("  >> /weather/current")
r = client.get('/api/v3/weather/current', headers={'X-APP-KEY': APPKEY})
test("GET /weather/current status=200 or 404", r.status_code in (200, 404))
data = r.get_json()
test("Current response has meta", 'meta' in data)

r = client.get('/api/v3/weather/current?source=ecowitt', headers={'X-APP-KEY': APPKEY})
test("source=ecowitt accepted", r.status_code in (200, 404))

r = client.get('/api/v3/weather/current?source=wunderground', headers={'X-APP-KEY': APPKEY})
test("source=wunderground accepted", r.status_code in (200, 404))

r = client.get('/api/v3/weather/current?source=invalid', headers={'X-APP-KEY': APPKEY})
test("source=invalid => 400", r.status_code == 400)

# --- 5.4 Strict Params (unknown params rejected) ---
print("  >> Strict Parameter Validation")
r = client.get('/api/v3/weather/current?source=ecowitt&garbage=1', headers={'X-APP-KEY': APPKEY})
test("Unknown param 'garbage' => 400", r.status_code == 400)
data = r.get_json()
test("Error code = UNKNOWN_PARAMETER", data.get('error', {}).get('code') == 'UNKNOWN_PARAMETER')

r = client.get('/api/v3/weather/current?hbsdgvfsg', headers={'X-APP-KEY': APPKEY})
test("Random param 'hbsdgvfsg' => 400", r.status_code == 400)

r = client.get('/api/v3/health?xyz=1')
test("Health with unknown param => 400", r.status_code == 400)

# --- 5.5 Weather Predict ---
print("  >> /weather/predict")
r = client.get('/api/v3/weather/predict', headers={'X-APP-KEY': APPKEY})
test("GET /weather/predict default", r.status_code in (200, 404))

r = client.get('/api/v3/weather/predict?model=xgboost&limit=5', headers={'X-APP-KEY': APPKEY})
test("XGBoost + limit => 400 (limit not allowed)", r.status_code == 400)

r = client.get('/api/v3/weather/predict?model=invalid', headers={'X-APP-KEY': APPKEY})
test("model=invalid => 400", r.status_code == 400)

# --- 5.6 Weather Details ---
print("  >> /weather/details")
r = client.get('/api/v3/weather/details', headers={'X-APP-KEY': APPKEY})
test("GET /weather/details", r.status_code in (200, 404))

# --- 5.7 Weather History ---
print("  >> /weather/history")
r = client.get('/api/v3/weather/history', headers={'X-APP-KEY': APPKEY})
test("GET /weather/history default", r.status_code == 200)
data = r.get_json()
test("History has meta.page", 'page' in data.get('meta', {}))
test("History has meta.total", 'total' in data.get('meta', {}))
test("History data is list", isinstance(data.get('data'), list))

# Pagination
r = client.get('/api/v3/weather/history?page=1&per_page=5', headers={'X-APP-KEY': APPKEY})
test("History page=1, per_page=5", r.status_code == 200)
data = r.get_json()
test("per_page in meta = 5", data.get('meta', {}).get('per_page') == 5)

r = client.get('/api/v3/weather/history?page=1&per_page=invalid', headers={'X-APP-KEY': APPKEY})
test("History per_page=invalid => 400", r.status_code == 400)

r = client.get('/api/v3/weather/history?page=abc', headers={'X-APP-KEY': APPKEY})
test("History page=abc => 400", r.status_code == 400)

# --- 5.8 Weather Graph ---
print("  >> /weather/graph")
r = client.get('/api/v3/weather/graph', headers={'X-APP-KEY': APPKEY})
test("Graph without params => 400 (range required)", r.status_code == 400)

r = client.get('/api/v3/weather/graph?range=weekly&datatype=temperature', headers={'X-APP-KEY': APPKEY})
test("Graph weekly temperature", r.status_code == 200)

r = client.get('/api/v3/weather/graph?range=monthly&datatype=humidity', headers={'X-APP-KEY': APPKEY})
test("Graph monthly humidity", r.status_code == 200)

r = client.get('/api/v3/weather/graph?range=weekly&datatype=invalid_type', headers={'X-APP-KEY': APPKEY})
test("Graph datatype=invalid => 400", r.status_code == 400)

r = client.get('/api/v3/weather/graph?range=invalid&datatype=temperature', headers={'X-APP-KEY': APPKEY})
test("Graph range=invalid => 400", r.status_code == 400)


# ===================================================================
# SECTION 6: Date/Time Validation (REMOVED)
# ===================================================================
# Feature removed as per user request.


# ===================================================================
# SECTION 7: Security Headers
# ===================================================================
print("\n--- 7. SECURITY HEADERS ---")

r = client.get('/api/v3/health')
test("X-Content-Type-Options = nosniff", r.headers.get('X-Content-Type-Options') == 'nosniff')
test("X-Frame-Options = DENY", r.headers.get('X-Frame-Options') == 'DENY')
test("X-XSS-Protection present", r.headers.get('X-XSS-Protection') is not None)
test("Content-Security-Policy present", r.headers.get('Content-Security-Policy') is not None)
test("Cache-Control = no-store", 'no-store' in (r.headers.get('Cache-Control') or ''))
test("Permissions-Policy present", r.headers.get('Permissions-Policy') is not None)

# Rate limit headers
test("X-RateLimit-Limit present", r.headers.get('X-RateLimit-Limit') is not None)
test("X-RateLimit-Remaining present", r.headers.get('X-RateLimit-Remaining') is not None)


# ===================================================================
# SECTION 8: Error Handlers
# ===================================================================
print("\n--- 8. ERROR HANDLERS ---")

r = client.get('/api/v3/nonexistent-endpoint', headers={'X-APP-KEY': APPKEY})
test("404 returns JSON", r.content_type and 'json' in r.content_type)
test("404 has error structure", 'error' in (r.get_json() or {}))

r = client.post('/api/v3/health')
test("POST /health => 405 (Method Not Allowed)", r.status_code == 405)

r = client.get('/random/path/outside/api')
test("Non-API path => 404 JSON", r.status_code == 404)


# ===================================================================
# SUMMARY
# ===================================================================
print("\n" + "=" * 70)
print(f"RESULTS: {PASSED} PASSED, {FAILED} FAILED (total: {PASSED + FAILED})")
print("=" * 70)

if ERRORS:
    print("\nFAILED TESTS:")
    for i, e in enumerate(ERRORS, 1):
        print(f"  {i}. {e}")
else:
    print("\nALL TESTS PASSED!")

print()
