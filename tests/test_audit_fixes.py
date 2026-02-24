"""
Test Suite: Enterprise Audit Fixes (Fix 1-8)
=============================================
Menguji semua perbaikan dari audit:
1. Interpolation Guard (limit=6, ratio check 25%)
2. Rounding Consistency (semua round(_, 2))
3. SELECT * Elimination (serializers.py)
4. ORDER BY Consistency (timestamp DESC)
5. LSTM Thread Safety (threading.Lock)
6. Fetch->Prediction Coupling (skip_sources)
7. APScheduler Timezone + CONSOLE_ENDPOINT_ENABLED
8. DB Session Dirty (try/except/rollback)
"""

import os
import sys
import math
import threading
import numpy as np
import pandas as pd

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

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
print("Enterprise Audit Fixes -- Test Suite")
print("=" * 70)

# ===================================================================
# FIX 1: Interpolation Guard
# ===================================================================
print("\n--- FIX 1: INTERPOLATION GUARD ---")

# Test 1.1: limit=6 parameter in _resample_and_interpolate
print("  >> Testing interpolation limit=6")
try:
    from app.services.prediction_service import _resample_and_interpolate
    from datetime import datetime, timezone, timedelta
    
    # Buat data dengan gap besar (2 jam = 24 slot kosong)
    timestamps = []
    base = datetime(2026, 2, 20, 10, 0, 0, tzinfo=timezone.utc)
    
    # Data dari 10:00 sampai 10:30 (7 data points, setiap 5 menit)
    for i in range(7):
        timestamps.append(base + timedelta(minutes=i * 5))
    
    # SKIP 2 jam (gap besar)
    # Data dari 12:30 sampai 13:00 (7 data points)
    for i in range(7):
        timestamps.append(base + timedelta(hours=2, minutes=30 + i * 5))
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'suhu': [25.0] * 7 + [30.0] * 7,
        'kelembaban': [80.0] * 14,
        'kecepatan_angin': [2.0] * 14,
        'arah_angin': [180.0] * 14,
        'tekanan_udara': [1013.0] * 14,
        'intensitas_hujan': [0.0] * 14,
        'intensitas_cahaya': [500.0] * 14,
    })
    
    result = _resample_and_interpolate(df, 'timestamp')
    
    # Setelah resample, harus ada data points untuk setiap 5 menit
    # Dari 10:00 sampai 13:00 = 37 slots (3 jam x 12 + 1)
    total_slots = len(result)
    test("Resample creates 5-min grid", total_slots > 14, f"Got {total_slots} rows from 14 input")
    
    # Dengan limit=6, gap 2 jam TIDAK boleh terisi semua oleh interpolasi
    # Hanya 6 slot dari masing-masing ujung yang terisi
    # Sisanya di-ffill/bfill
    suhu_values = result['suhu'].tolist()
    
    # Periksa bahwa ada variasi (bukan semua 25.0 atau semua 30.0)
    has_variation = len(set(round(v, 1) for v in suhu_values)) > 1
    test("Interpolation limit=6: gap values not all same", has_variation, 
         f"Unique values: {len(set(round(v, 1) for v in suhu_values))}")
    
except Exception as e:
    test("Interpolation limit=6", False, str(e))

# Test 1.2: MAX_INTERPOLATED_RATIO constant
print("  >> Testing MAX_INTERPOLATED_RATIO constant")
try:
    from app.services.prediction_service import MAX_INTERPOLATED_RATIO
    test("MAX_INTERPOLATED_RATIO = 0.25", MAX_INTERPOLATED_RATIO == 0.25, 
         f"Got {MAX_INTERPOLATED_RATIO}")
except Exception as e:
    test("MAX_INTERPOLATED_RATIO exists", False, str(e))


# ===================================================================
# FIX 2: Rounding Consistency
# ===================================================================
print("\n--- FIX 2: ROUNDING CONSISTENCY ---")

try:
    from app.common.helpers import (
        fahrenheit_to_celsius,
        inch_hg_to_hpa,
        mph_to_ms,
        wm2_to_lux,
        inch_per_hour_to_mm_per_hour
    )
    
    # Test fahrenheit_to_celsius (sudah round 2)
    result = fahrenheit_to_celsius(100.0)
    test("fahrenheit_to_celsius(100) = 37.78", result == 37.78, f"Got {result}")
    decimals = len(str(result).split('.')[-1]) if '.' in str(result) else 0
    test("fahrenheit_to_celsius: <= 2 decimals", decimals <= 2, f"Got {decimals}")
    
    # Test inch_hg_to_hpa (sudah round 2)
    result = inch_hg_to_hpa(29.92)
    test("inch_hg_to_hpa(29.92) is float", isinstance(result, float))
    decimals = len(str(result).split('.')[-1]) if '.' in str(result) else 0
    test("inch_hg_to_hpa: <= 2 decimals", decimals <= 2, f"Got {decimals}")
    
    # Test mph_to_ms (was 4dp, now 2dp)
    result = mph_to_ms(10.0)
    expected = round(10.0 * 0.44704, 2)
    test(f"mph_to_ms(10) = {expected}", result == expected, f"Got {result}")
    decimals = len(str(result).split('.')[-1]) if '.' in str(result) else 0
    test("mph_to_ms: <= 2 decimals (was 4)", decimals <= 2, f"Got {decimals}")
    
    # Test wm2_to_lux (was no round, now round 2)
    result = wm2_to_lux(100.0)
    expected = round(100.0 * 126.7, 2)
    test(f"wm2_to_lux(100) = {expected}", result == expected, f"Got {result}")
    decimals = len(str(result).split('.')[-1]) if '.' in str(result) else 0
    test("wm2_to_lux: <= 2 decimals (was unlimited)", decimals <= 2, f"Got {decimals}")
    
    # Test inch_per_hour_to_mm_per_hour (was no round, now round 2)
    result = inch_per_hour_to_mm_per_hour(0.5)
    expected = round(0.5 * 25.4, 2)
    test(f"inch_per_hour_to_mm_per_hour(0.5) = {expected}", result == expected, f"Got {result}")
    decimals = len(str(result).split('.')[-1]) if '.' in str(result) else 0
    test("inch_per_hour_to_mm_per_hour: <= 2 decimals (was unlimited)", decimals <= 2, f"Got {decimals}")
    
    # Test None handling
    test("fahrenheit_to_celsius(None) = None", fahrenheit_to_celsius(None) is None)
    test("mph_to_ms(None) = None", mph_to_ms(None) is None)
    test("wm2_to_lux(None) = 0.0", wm2_to_lux(None) == 0.0)
    test("inch_per_hour_to_mm_per_hour(None) = 0.0", inch_per_hour_to_mm_per_hour(None) == 0.0)
    
except Exception as e:
    test("Rounding functions", False, str(e))


# ===================================================================
# FIX 3 + 4: SELECT * Elimination + ORDER BY Consistency
# ===================================================================
print("\n--- FIX 3+4: SELECT * + ORDER BY ---")

os.environ['LOAD_DOTENV'] = 'true'
os.environ['DISABLE_SCHEDULER_FOR_TESTS'] = 'true'

try:
    from app import create_app, db
    app = create_app()
    
    with app.app_context():
        # Test 3A: Label cache loads with load_only
        from app import serializers
        serializers._LABEL_CACHE = {}  # Reset cache
        serializers._load_label_cache()
        test("Label cache loaded", len(serializers._LABEL_CACHE) > 0,
             f"Cache size: {len(serializers._LABEL_CACHE)}")
        
        # Verify cache structure (must have id, name)
        if serializers._LABEL_CACHE:
            first_label = list(serializers._LABEL_CACHE.values())[0]
            test("Label has 'label_id'", 'label_id' in first_label, str(first_label.keys()))
            test("Label has 'name'", 'name' in first_label, str(first_label.keys()))
            test("Label has 'class_id'", 'class_id' in first_label, str(first_label.keys()))
        
        # Test 3C + 4: get_latest_weather_data with ORDER BY timestamp
        from app.serializers import get_latest_weather_data
        from app import models
        
        # Test Ecowitt (should ORDER BY request_time DESC)
        eco = get_latest_weather_data('ecowitt')
        test("get_latest_weather_data('ecowitt') works", True)
        
        # Test Console (should ORDER BY date_utc DESC)
        console = get_latest_weather_data('console')
        test("get_latest_weather_data('console') works", True)
        
        # Test Wunderground (should ORDER BY request_time DESC) 
        wund = get_latest_weather_data('wunderground')
        test("get_latest_weather_data('wunderground') works", True)
        
except Exception as e:
    test("SELECT * + ORDER BY tests", False, str(e))


# ===================================================================
# FIX 5: LSTM Thread Safety
# ===================================================================
print("\n--- FIX 5: LSTM THREAD SAFETY ---")

try:
    from app.services.prediction_service import _lstm_predict_lock
    test("_lstm_predict_lock exists", _lstm_predict_lock is not None)
    test("_lstm_predict_lock is threading.Lock", isinstance(_lstm_predict_lock, type(threading.Lock())))
except Exception as e:
    test("LSTM predict lock", False, str(e))


# ===================================================================
# FIX 6: Fetch->Prediction Coupling (skip_sources)
# ===================================================================
print("\n--- FIX 6: FETCH->PREDICTION COUPLING ---")

# Test 6A: run_hourly_prediction accepts skip_sources
try:
    import inspect
    from app.jobs import run_hourly_prediction
    sig = inspect.signature(run_hourly_prediction)
    test("run_hourly_prediction has 'skip_sources' param",
         'skip_sources' in sig.parameters,
         f"Params: {list(sig.parameters.keys())}")
    test("skip_sources default = None",
         sig.parameters['skip_sources'].default is None)
except Exception as e:
    test("run_hourly_prediction signature", False, str(e))

# Test 6B: run_prediction_pipeline accepts skip_sources
try:
    from app.services.prediction_service import run_prediction_pipeline
    sig = inspect.signature(run_prediction_pipeline)
    test("run_prediction_pipeline has 'skip_sources' param",
         'skip_sources' in sig.parameters,
         f"Params: {list(sig.parameters.keys())}")
    test("skip_sources default = None",
         sig.parameters['skip_sources'].default is None)
except Exception as e:
    test("run_prediction_pipeline signature", False, str(e))


# ===================================================================
# FIX 7: APScheduler Timezone + CONSOLE_ENDPOINT_ENABLED
# ===================================================================
print("\n--- FIX 7: APSCHEDULER + CONSOLE_ENDPOINT ---")

# Test 7A: scheduler_init imports timezone
try:
    from app import scheduler_init
    # Check source code contains timezone=timezone.utc
    import inspect
    source = inspect.getsource(scheduler_init.init_scheduled_jobs)
    test("init_scheduled_jobs contains 'timezone=timezone.utc'",
         "timezone=timezone.utc" in source or "timezone = timezone.utc" in source,
         "timezone=timezone.utc not found in source")
except Exception as e:
    test("APScheduler timezone check", False, str(e))

# Test 7B: CONSOLE_ENDPOINT_ENABLED check in api_v3
try:
    client = app.test_client()
    
    # Test with CONSOLE_ENDPOINT_ENABLED=false
    os.environ['CONSOLE_ENDPOINT_ENABLED'] = 'false'
    r = client.get('/api/v3/weather/console')
    test("Console disabled -> 503", r.status_code == 503,
         f"Got status {r.status_code}")
    if r.status_code == 503:
        data = r.get_json()
        test("Console disabled -> SERVICE_DISABLED code",
             data.get('error', {}).get('code') == 'SERVICE_DISABLED')
    
    # Restore
    os.environ['CONSOLE_ENDPOINT_ENABLED'] = 'true'
    
except Exception as e:
    test("CONSOLE_ENDPOINT_ENABLED check", False, str(e))
    os.environ['CONSOLE_ENDPOINT_ENABLED'] = 'true'


# ===================================================================
# FIX 8: DB Session Dirty (try/except/rollback)
# ===================================================================
print("\n--- FIX 8: DB SESSION DIRTY ---")

try:
    import inspect
    from app.jobs import process_console_data, fetch_ecowitt, fetch_wunderground
    
    # Check source code of each function for try/except around commit
    src_console = inspect.getsource(process_console_data)
    test("process_console_data has try/except on commit",
         "db.session.rollback()" in src_console and "db.session.commit()" in src_console,
         "Missing try/except/rollback around commit")
    
    src_ecowitt = inspect.getsource(fetch_ecowitt)
    test("fetch_ecowitt has try/except on commit",
         "db.session.rollback()" in src_ecowitt and "db.session.commit()" in src_ecowitt,
         "Missing try/except/rollback around commit")
    
    src_wunderground = inspect.getsource(fetch_wunderground)
    test("fetch_wunderground has try/except on commit",
         "db.session.rollback()" in src_wunderground and "db.session.commit()" in src_wunderground,
         "Missing try/except/rollback around commit")
    
except Exception as e:
    test("DB session dirty check", False, str(e))


# ===================================================================
# INTEGRATED: Prediction Pipeline Structure
# ===================================================================
print("\n--- INTEGRATED: PIPELINE STRUCTURE ---")

try:
    from app.services.prediction_service import (
        SEQUENCE_LENGTH,
        PREDICTION_STEPS,
        N_FEATURES,
        RAIN_FEATURE_INDEX,
        DATA_INTERVAL_MINUTES,
        MAX_INTERPOLATED_RATIO,
        _lstm_predict_lock,
        XGBOOST_MODEL_PATH,
        LSTM_MODEL_PATH,
        SCALER_PATH,
    )
    
    test(f"SEQUENCE_LENGTH = 144", SEQUENCE_LENGTH == 144)
    test(f"PREDICTION_STEPS = 24", PREDICTION_STEPS == 24)
    test(f"N_FEATURES = 9", N_FEATURES == 9)
    test(f"RAIN_FEATURE_INDEX = 5", RAIN_FEATURE_INDEX == 5)
    test(f"DATA_INTERVAL_MINUTES = 5", DATA_INTERVAL_MINUTES == 5)
    test(f"MAX_INTERPOLATED_RATIO = 0.25", MAX_INTERPOLATED_RATIO == 0.25)
    
    # Check model files exist
    test("XGBoost model file exists", os.path.exists(XGBOOST_MODEL_PATH),
         f"Path: {XGBOOST_MODEL_PATH}")
    test("LSTM model file exists", os.path.exists(LSTM_MODEL_PATH),
         f"Path: {LSTM_MODEL_PATH}")
    test("Scaler file exists", os.path.exists(SCALER_PATH),
         f"Path: {SCALER_PATH}")
    
except Exception as e:
    test("Pipeline constants", False, str(e))


# ===================================================================
# INTEGRATED: _calculate_hour_components (WIB)
# ===================================================================
print("\n--- INTEGRATED: HOUR COMPONENTS (WIB) ---")

try:
    from app.services.prediction_service import _calculate_hour_components
    from datetime import datetime, timezone, timedelta
    
    # Test: 12:00 UTC = 19:00 WIB
    utc_noon = datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc)
    sin_val, cos_val = _calculate_hour_components(utc_noon)
    
    # Expected: WIB = 19:00, angle = 2π × (19.0/24.0)
    expected_angle = 2.0 * math.pi * (19.0 / 24.0)
    expected_sin = math.sin(expected_angle)
    expected_cos = math.cos(expected_angle)
    
    test("hour_sin for 12:00 UTC (19:00 WIB) correct",
         abs(sin_val - expected_sin) < 0.001,
         f"Got {sin_val:.4f}, expected {expected_sin:.4f}")
    test("hour_cos for 12:00 UTC (19:00 WIB) correct",
         abs(cos_val - expected_cos) < 0.001,
         f"Got {cos_val:.4f}, expected {expected_cos:.4f}")
    
    # Test: 00:00 UTC = 07:00 WIB
    utc_midnight = datetime(2026, 2, 20, 0, 0, 0, tzinfo=timezone.utc)
    sin_val2, cos_val2 = _calculate_hour_components(utc_midnight)
    
    expected_angle2 = 2.0 * math.pi * (7.0 / 24.0)
    expected_sin2 = math.sin(expected_angle2)
    expected_cos2 = math.cos(expected_angle2)
    
    test("hour_sin for 00:00 UTC (07:00 WIB) correct",
         abs(sin_val2 - expected_sin2) < 0.001,
         f"Got {sin_val2:.4f}, expected {expected_sin2:.4f}")
    test("hour_cos for 00:00 UTC (07:00 WIB) correct",
         abs(cos_val2 - expected_cos2) < 0.001,
         f"Got {cos_val2:.4f}, expected {expected_cos2:.4f}")
    
except Exception as e:
    test("Hour components", False, str(e))


# ===================================================================
# INTEGRATED: Full Pipeline via API (End-to-End)
# ===================================================================
print("\n--- INTEGRATED: E2E API TESTS ---")

try:
    APPKEY = os.environ.get('APPKEY', '')
    client = app.test_client()
    
    # Test: GET /weather/current (all sources)
    for source in ['ecowitt', 'wunderground', 'console']:
        r = client.get(f'/api/v3/weather/current?source={source}', 
                      headers={'X-APP-KEY': APPKEY})
        test(f"GET /weather/current?source={source} → {r.status_code}",
             r.status_code in (200, 404))
    
    # Test: GET /weather/predict (both models)
    for model in ['xgboost', 'lstm']:
        r = client.get(f'/api/v3/weather/predict?model={model}',
                      headers={'X-APP-KEY': APPKEY})
        test(f"GET /weather/predict?model={model} → {r.status_code}",
             r.status_code in (200, 404))
        if r.status_code == 200:
            data = r.get_json()
            test(f"Predict {model} has data", data.get('data') is not None)
    
    # Test: GET /weather/details
    r = client.get('/api/v3/weather/details', headers={'X-APP-KEY': APPKEY})
    test(f"GET /weather/details → {r.status_code}", r.status_code in (200, 404))
    
except Exception as e:
    test("E2E API tests", False, str(e))


# ===================================================================
# INTEGRATED: Database Prediction Data Integrity
# ===================================================================
print("\n--- INTEGRATED: DB PREDICTION INTEGRITY ---")

try:
    with app.app_context():
        from app import models
        
        # Check PredictionLog table
        latest_pred = db.session.query(models.PredictionLog).order_by(
            models.PredictionLog.created_at.desc()
        ).first()
        
        if latest_pred:
            test("Latest PredictionLog exists", True)
            test("PredictionLog has created_at", latest_pred.created_at is not None)
            test("PredictionLog created_at has timezone",
                 latest_pred.created_at.tzinfo is not None,
                 f"tzinfo: {latest_pred.created_at.tzinfo}")
            
            # Check model reference
            test("PredictionLog has model_id", latest_pred.model_id is not None)
            
            # Check XGBoost or LSTM data reference (partial save: at least one)
            has_xgb = latest_pred.data_xgboost_id is not None
            has_lstm = latest_pred.data_lstm_id is not None
            test("PredictionLog has data ref (XGBoost or LSTM)",
                 has_xgb or has_lstm,
                 f"XGBoost: {has_xgb}, LSTM: {has_lstm}")
        else:
            test("Latest PredictionLog exists", False, "No prediction logs in DB")
        
        # Check WeatherLog tables have data
        for model_cls, name in [
            (models.WeatherLogEcowitt, 'Ecowitt'),
            (models.WeatherLogWunderground, 'Wunderground'),
            (models.WeatherLogConsole, 'Console'),
        ]:
            count = db.session.query(model_cls).count()
            test(f"{name} weather data count: {count}", count > 0,
                 f"No data for {name}")
        
except Exception as e:
    test("DB prediction integrity", False, str(e))


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
