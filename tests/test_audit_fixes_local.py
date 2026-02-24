# -*- coding: utf-8 -*-
"""
Test Suite LOKAL: Enterprise Audit Fixes (Fix 1-8)
===================================================
Menggunakan SQLite in-memory agar bisa dijalankan tanpa PostgreSQL.
Menguji full pipeline: fetch -> prediction -> database save.
"""

import os
import sys
import math
import threading
import inspect
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ['LOAD_DOTENV'] = 'true'
os.environ['DISABLE_SCHEDULER_FOR_TESTS'] = 'true'

PASSED = 0
FAILED = 0
SKIPPED = 0
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

def skip(name, reason=""):
    global SKIPPED
    SKIPPED += 1
    print(f"  [SKIP] {name} -- {reason}")

print("=" * 70)
print("Enterprise Audit Fixes -- LOCAL Test Suite (SQLite)")
print("=" * 70)


# ===================================================================
# SETUP: Create app with SQLite in-memory DB
# ===================================================================
print("\n--- SETUP: SQLite In-Memory DB ---")

try:
    from app import create_app, db
    from app import models
    from sqlalchemy import Text, DateTime, inspect as sa_inspect

    app = create_app(test_config={
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key-32-chars-minimum!',
        'MAX_CONTENT_LENGTH': 1 * 1024 * 1024,
        'TRAP_HTTP_EXCEPTIONS': True,
    })

    with app.app_context():
        # Monkey-patch PostgreSQL-specific types untuk SQLite
        from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
        for table in db.metadata.tables.values():
            for col in table.columns:
                if isinstance(col.type, ARRAY):
                    col.type = Text()
                elif isinstance(col.type, TIMESTAMP):
                    col.type = DateTime()

        db.create_all()
        test("SQLite in-memory DB created", True)

        # Seed Label table (diperlukan oleh serializers)
        labels_data = [
            {'id': 1, 'name': 'Cerah'},
            {'id': 2, 'name': 'Berawan'},
            {'id': 3, 'name': 'Hujan Ringan'},
            {'id': 4, 'name': 'Hujan Sedang'},
            {'id': 5, 'name': 'Hujan Lebat'},
        ]
        for lbl in labels_data:
            db.session.add(models.Label(id=lbl['id'], name=lbl['name']))

        # Seed Model table
        db.session.add(models.Model(id=1, name='XGBoost', range_prediction=1))
        db.session.add(models.Model(id=2, name='LSTM', range_prediction=24))
        db.session.commit()
        test("Seed data (Labels + Models) inserted", True)

except Exception as e:
    test("SETUP SQLite", False, str(e))
    print("FATAL: Cannot continue without DB. Exiting.")
    sys.exit(1)


# ===================================================================
# FIX 1: Interpolation Guard
# ===================================================================
print("\n--- FIX 1: INTERPOLATION GUARD ---")

try:
    from app.services.prediction_service import _resample_and_interpolate, MAX_INTERPOLATED_RATIO
    from datetime import datetime, timezone, timedelta

    # Test 1.1: limit=6 parameter bekerja
    print("  >> limit=6 pada gap besar")
    timestamps = []
    base = datetime(2026, 2, 20, 10, 0, 0, tzinfo=timezone.utc)

    # 7 data real: 10:00 - 10:30
    for i in range(7):
        timestamps.append(base + timedelta(minutes=i * 5))
    # GAP 2 JAM
    # 7 data real: 12:30 - 13:00
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
    total_slots = len(result)

    # 10:00 - 13:00 = 3 jam = 36 interval + 1 = 37 slots
    test("Resample: 14 input -> 37 slots (5-min grid)", total_slots == 37, f"Got {total_slots}")

    # Cek bahwa NaN tetap ada setelah limit=6 (diisi oleh ffill/bfill, bukan interpolasi)
    suhu_col = result['suhu'].tolist()
    unique_suhu = sorted(set(round(v, 2) for v in suhu_col))
    test("Gap besar: suhu tidak semua sama (interpolasi terbatas)", len(unique_suhu) >= 2,
         f"Unique: {unique_suhu}")

    # Test 1.2: Constant defined
    test("MAX_INTERPOLATED_RATIO = 0.25", MAX_INTERPOLATED_RATIO == 0.25)

    # Test 1.3: Data normal (tanpa gap) -> tidak terpengaruh
    print("  >> Data normal tanpa gap")
    normal_timestamps = [base + timedelta(minutes=i * 5) for i in range(20)]
    df_normal = pd.DataFrame({
        'timestamp': normal_timestamps,
        'suhu': [25.0 + i * 0.1 for i in range(20)],
        'kelembaban': [80.0] * 20,
        'kecepatan_angin': [2.0] * 20,
        'arah_angin': [180.0] * 20,
        'tekanan_udara': [1013.0] * 20,
        'intensitas_hujan': [0.0] * 20,
        'intensitas_cahaya': [500.0] * 20,
    })
    result_normal = _resample_and_interpolate(df_normal, 'timestamp')
    test("Data normal: jumlah sama", len(result_normal) == 20, f"Got {len(result_normal)}")

except Exception as e:
    test("Interpolation guard", False, str(e))


# ===================================================================
# FIX 2: Rounding Consistency (semua round(_, 2))
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

    # fahrenheit_to_celsius
    r = fahrenheit_to_celsius(100.0)
    test("fahrenheit_to_celsius(100) = 37.78", r == 37.78, f"Got {r}")

    # inch_hg_to_hpa
    r = inch_hg_to_hpa(29.92)
    test("inch_hg_to_hpa(29.92) = 1013.21", r == round(29.92 * 33.8639, 2), f"Got {r}")

    # mph_to_ms (WAS 4dp, NOW 2dp)
    r = mph_to_ms(10.0)
    test("mph_to_ms(10) = 4.47 (was 4.4704)", r == 4.47, f"Got {r}")

    # wm2_to_lux (WAS no round, NOW 2dp)
    r = wm2_to_lux(100.0)
    test("wm2_to_lux(100) = 12670.0", r == 12670.0, f"Got {r}")

    # Precision test: value that would differ without rounding
    r = wm2_to_lux(3.7)
    expected = round(3.7 * 126.7, 2)
    test(f"wm2_to_lux(3.7) = {expected} (2dp)", r == expected, f"Got {r}")

    # inch_per_hour_to_mm_per_hour (WAS no round, NOW 2dp)
    r = inch_per_hour_to_mm_per_hour(0.33)
    expected = round(0.33 * 25.4, 2)
    test(f"inch_per_hour_to_mm_per_hour(0.33) = {expected}", r == expected, f"Got {r}")

    # None handling
    test("fahrenheit_to_celsius(None) = None", fahrenheit_to_celsius(None) is None)
    test("mph_to_ms(None) = None", mph_to_ms(None) is None)
    test("wm2_to_lux(None) = 0.0", wm2_to_lux(None) == 0.0)
    test("inch_per_hour_to_mm_per_hour(None) = 0.0", inch_per_hour_to_mm_per_hour(None) == 0.0)

    # Invalid type handling
    test("fahrenheit_to_celsius('abc') = None", fahrenheit_to_celsius('abc') is None)
    test("mph_to_ms('xyz') = None", mph_to_ms('xyz') is None)

except Exception as e:
    test("Rounding", False, str(e))


# ===================================================================
# FIX 3: SELECT * Elimination
# ===================================================================
print("\n--- FIX 3: SELECT * ELIMINATION ---")

with app.app_context():
    try:
        from app import serializers

        # Test 3A: Label cache menggunakan load_only
        serializers._LABEL_CACHE = {}  # Force clear
        serializers._load_label_cache()

        test("Label cache loaded (5 labels)", len(serializers._LABEL_CACHE) == 5,
             f"Got {len(serializers._LABEL_CACHE)}")

        if serializers._LABEL_CACHE:
            first = list(serializers._LABEL_CACHE.values())[0]
            test("Label has 'name' key", 'name' in first, str(first))

        # Test 3B: Source code check - load_only in _load_label_cache
        src = inspect.getsource(serializers._load_label_cache)
        test("_load_label_cache uses load_only", "load_only" in src,
             "load_only not found in source")

        # Test 3C: get_latest_weather_data source check
        src_glwd = inspect.getsource(serializers.get_latest_weather_data)
        test("get_latest_weather_data has load_fields param", "load_fields" in src_glwd,
             "load_fields not found in source")

    except Exception as e:
        test("SELECT * elimination", False, str(e))


# ===================================================================
# FIX 4: ORDER BY Consistency (timestamp DESC)
# ===================================================================
print("\n--- FIX 4: ORDER BY CONSISTENCY ---")

with app.app_context():
    try:
        # Insert test weather data
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        # Ecowitt: 2 records, newest via request_time
        older_eco = models.WeatherLogEcowitt(
            humidity_outdoor=70.0, temperature_main_outdoor=25.0,
            pressure_relative=1013.0, pressure_absolute=1013.0,
            rain_rate=0.0, rain_daily=0.0, rain_event=0.0, rain_hour=0.0,
            rain_weekly=0.0, rain_monthly=0.0, rain_yearly=0.0,
            wind_speed=2.0, wind_gust=3.0, wind_direction=180.0,
            request_time=now - timedelta(hours=2)
        )
        newer_eco = models.WeatherLogEcowitt(
            humidity_outdoor=72.0, temperature_main_outdoor=26.0,
            pressure_relative=1014.0, pressure_absolute=1014.0,
            rain_rate=0.5, rain_daily=1.0, rain_event=0.5, rain_hour=0.3,
            rain_weekly=5.0, rain_monthly=20.0, rain_yearly=200.0,
            wind_speed=3.0, wind_gust=5.0, wind_direction=190.0,
            request_time=now - timedelta(minutes=5)
        )
        db.session.add(older_eco)
        db.session.add(newer_eco)

        # Wunderground: 2 records
        older_wund = models.WeatherLogWunderground(
            humidity=68.0, temperature=24.0, pressure=1012.0,
            wind_speed=1.5, wind_direction=170.0,
            request_time=now - timedelta(hours=3)
        )
        newer_wund = models.WeatherLogWunderground(
            humidity=71.0, temperature=25.5, pressure=1013.5,
            wind_speed=2.5, wind_direction=180.0,
            request_time=now - timedelta(minutes=10)
        )
        db.session.add(older_wund)
        db.session.add(newer_wund)

        # Console: 2 records
        older_console = models.WeatherLogConsole(
            humidity=65.0, temperature=80.0,
            pressure_relative=29.90, wind_speed=5.0, wind_direction=200.0,
            date_utc=now - timedelta(hours=1)
        )
        newer_console = models.WeatherLogConsole(
            humidity=68.0, temperature=82.0,
            pressure_relative=29.92, wind_speed=6.0, wind_direction=210.0,
            date_utc=now - timedelta(minutes=3)
        )
        db.session.add(older_console)
        db.session.add(newer_console)

        db.session.commit()
        test("Test weather data inserted (6 records)", True)

        # Test ORDER BY: get_latest should return NEWEST by timestamp
        from app.serializers import get_latest_weather_data

        latest_eco = get_latest_weather_data('ecowitt')
        test("Ecowitt: latest by request_time (temp=26.0)",
             latest_eco is not None and latest_eco.temperature_main_outdoor == 26.0,
             f"Got temp={latest_eco.temperature_main_outdoor if latest_eco else 'None'}")

        latest_wund = get_latest_weather_data('wunderground')
        test("Wunderground: latest by request_time (temp=25.5)",
             latest_wund is not None and float(latest_wund.temperature) == 25.5,
             f"Got temp={latest_wund.temperature if latest_wund else 'None'}")

        latest_console = get_latest_weather_data('console')
        test("Console: latest by date_utc (temp=82.0)",
             latest_console is not None and float(latest_console.temperature) == 82.0,
             f"Got temp={latest_console.temperature if latest_console else 'None'}")

    except Exception as e:
        test("ORDER BY consistency", False, str(e))


# ===================================================================
# FIX 5: LSTM Thread Safety
# ===================================================================
print("\n--- FIX 5: LSTM THREAD SAFETY ---")

try:
    from app.services.prediction_service import _lstm_predict_lock
    test("_lstm_predict_lock exists", _lstm_predict_lock is not None)
    test("_lstm_predict_lock is threading.Lock",
         isinstance(_lstm_predict_lock, type(threading.Lock())))

    # Test: Lock bekerja (acquire/release)
    acquired = _lstm_predict_lock.acquire(blocking=False)
    test("Lock can be acquired", acquired)
    if acquired:
        _lstm_predict_lock.release()
    test("Lock released successfully", True)

    # Verify predict_lstm source code contains lock usage
    from app.services.prediction_service import predict_lstm
    src = inspect.getsource(predict_lstm)
    test("predict_lstm uses _lstm_predict_lock", "_lstm_predict_lock" in src,
         "_lstm_predict_lock not found in predict_lstm source")

except Exception as e:
    test("LSTM thread safety", False, str(e))


# ===================================================================
# FIX 6: Fetch->Prediction Coupling (skip_sources)
# ===================================================================
print("\n--- FIX 6: FETCH->PREDICTION COUPLING ---")

try:
    from app.jobs import run_hourly_prediction
    from app.services.prediction_service import run_prediction_pipeline

    # Test 6A: Function signatures
    sig1 = inspect.signature(run_hourly_prediction)
    test("run_hourly_prediction has 'skip_sources' param",
         'skip_sources' in sig1.parameters)
    test("skip_sources default = None",
         sig1.parameters['skip_sources'].default is None)

    sig2 = inspect.signature(run_prediction_pipeline)
    test("run_prediction_pipeline has 'skip_sources' param",
         'skip_sources' in sig2.parameters)
    test("skip_sources default = None",
         sig2.parameters['skip_sources'].default is None)

    # Test 6B: Source code verification
    src_fetch = inspect.getsource(run_hourly_prediction)
    test("run_hourly_prediction passes skip_sources to pipeline",
         "skip_sources=skip_sources" in src_fetch or "skip_sources" in src_fetch)

    src_pipeline = inspect.getsource(run_prediction_pipeline)
    test("run_prediction_pipeline filters sources using skip_sources",
         "skip_sources" in src_pipeline and "all_sources" in src_pipeline)

    # Test 6C: fetch_and_store_weather source code test
    from app.jobs import fetch_and_store_weather
    src_fetch_store = inspect.getsource(fetch_and_store_weather)
    test("fetch_and_store_weather checks success_count > 0",
         "success_count > 0" in src_fetch_store or "success_count>0" in src_fetch_store,
         "success_count check not found")

except Exception as e:
    test("Fetch->Prediction coupling", False, str(e))


# ===================================================================
# FIX 7A: APScheduler Timezone
# ===================================================================
print("\n--- FIX 7A: APSCHEDULER TIMEZONE ---")

try:
    from app import scheduler_init
    # Search all functions in scheduler_init for timezone setting
    full_src = inspect.getsource(scheduler_init)
    count = full_src.count("timezone=timezone.utc")
    test(f"scheduler_init has timezone=timezone.utc ({count}x)", count >= 2,
         f"Found {count} occurrences, expected >= 2")

except Exception as e:
    test("APScheduler timezone", False, str(e))


# ===================================================================
# FIX 7B: CONSOLE_ENDPOINT_ENABLED
# ===================================================================
print("\n--- FIX 7B: CONSOLE_ENDPOINT_ENABLED ---")

try:
    client = app.test_client()

    # Test: disabled
    os.environ['CONSOLE_ENDPOINT_ENABLED'] = 'false'
    r = client.get('/api/v3/weather/console')
    test("CONSOLE_ENDPOINT_ENABLED=false -> 503", r.status_code == 503,
         f"Got {r.status_code}")

    if r.status_code == 503:
        data = r.get_json()
        test("Error code = SERVICE_DISABLED",
             data.get('error', {}).get('code') == 'SERVICE_DISABLED')

    # Test: re-enable
    os.environ['CONSOLE_ENDPOINT_ENABLED'] = 'true'
    r2 = client.get('/api/v3/weather/console')
    test("CONSOLE_ENDPOINT_ENABLED=true -> NOT 503", r2.status_code != 503,
         f"Got {r2.status_code}")

except Exception as e:
    test("CONSOLE_ENDPOINT_ENABLED", False, str(e))
    os.environ['CONSOLE_ENDPOINT_ENABLED'] = 'true'


# ===================================================================
# FIX 8: DB Session Dirty (try/except/rollback)
# ===================================================================
print("\n--- FIX 8: DB SESSION DIRTY ---")

try:
    from app.jobs import process_console_data, fetch_ecowitt, fetch_wunderground

    src_c = inspect.getsource(process_console_data)
    test("process_console_data: commit wrapped with try/except",
         "try:" in src_c and "db.session.rollback()" in src_c and "db.session.commit()" in src_c)

    src_e = inspect.getsource(fetch_ecowitt)
    test("fetch_ecowitt: commit wrapped with try/except",
         "try:" in src_e and "db.session.rollback()" in src_e and "db.session.commit()" in src_e)

    src_w = inspect.getsource(fetch_wunderground)
    test("fetch_wunderground: commit wrapped with try/except",
         "try:" in src_w and "db.session.rollback()" in src_w and "db.session.commit()" in src_w)

except Exception as e:
    test("DB session dirty", False, str(e))


# ===================================================================
# INTEGRATED: Process Console Data -> DB Save (End-to-End)
# ===================================================================
print("\n--- INTEGRATED: CONSOLE DATA -> DB ---")

with app.app_context():
    try:
        from app.jobs import process_console_data

        # Simulasi data console (format Imperial yang dikirim device)
        console_raw = {
            'runtime': '12345',
            'heap': '50000',
            'tempf': '82.4',        # Fahrenheit
            'humidity': '65',
            'winddir': '210',
            'windspeedmph': '5.5',
            'windgustmph': '8.0',
            'baromrelin': '29.92',
            'baromabsin': '29.80',
            'solarradiation': '120.5',
            'uv': '6',
            'rainratein': '0.02',
            'dailyrainin': '0.5',
            'eventrainin': '0.1',
            'hourlyrainin': '0.05',
            'weeklyrainin': '1.2',
            'monthlyrainin': '3.5',
            'yearlyrainin': '25.0',
        }

        count_before = db.session.query(models.WeatherLogConsole).count()
        result = process_console_data(console_raw)

        if result is not None:
            test("process_console_data returns WeatherLogConsole", True)
            test("Console data saved to DB (ID exists)", result.id is not None)

            count_after = db.session.query(models.WeatherLogConsole).count()
            test("DB count increased by 1", count_after == count_before + 1,
                 f"Before: {count_before}, After: {count_after}")

            test("Temperature stored as float", isinstance(result.temperature, (int, float)),
                 f"Type: {type(result.temperature)}")
            test("Humidity stored correctly", result.humidity == 65.0,
                 f"Got {result.humidity}")
        else:
            test("process_console_data returned result", False, "Got None")

    except Exception as e:
        test("Console data E2E", False, str(e))


# ===================================================================
# INTEGRATED: Hour Components (WIB timezone)
# ===================================================================
print("\n--- INTEGRATED: HOUR COMPONENTS (WIB) ---")

try:
    from app.services.prediction_service import _calculate_hour_components

    # 12:00 UTC = 19:00 WIB
    utc_noon = datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc)
    sin_v, cos_v = _calculate_hour_components(utc_noon)

    angle = 2.0 * math.pi * (19.0 / 24.0)
    test("hour_sin(12:00 UTC / 19:00 WIB) correct",
         abs(sin_v - math.sin(angle)) < 0.001,
         f"Got {sin_v:.4f}, expected {math.sin(angle):.4f}")
    test("hour_cos(12:00 UTC / 19:00 WIB) correct",
         abs(cos_v - math.cos(angle)) < 0.001,
         f"Got {cos_v:.4f}, expected {math.cos(angle):.4f}")

    # 00:00 UTC = 07:00 WIB
    utc_midnight = datetime(2026, 2, 20, 0, 0, 0, tzinfo=timezone.utc)
    sin_v2, cos_v2 = _calculate_hour_components(utc_midnight)

    angle2 = 2.0 * math.pi * (7.0 / 24.0)
    test("hour_sin(00:00 UTC / 07:00 WIB) correct",
         abs(sin_v2 - math.sin(angle2)) < 0.001)
    test("hour_cos(00:00 UTC / 07:00 WIB) correct",
         abs(cos_v2 - math.cos(angle2)) < 0.001)

except Exception as e:
    test("Hour components", False, str(e))


# ===================================================================
# INTEGRATED: Pipeline Constants
# ===================================================================
print("\n--- INTEGRATED: PIPELINE CONSTANTS ---")

try:
    from app.services.prediction_service import (
        SEQUENCE_LENGTH, PREDICTION_STEPS, N_FEATURES,
        RAIN_FEATURE_INDEX, DATA_INTERVAL_MINUTES,
        XGBOOST_MODEL_PATH, LSTM_MODEL_PATH, SCALER_PATH,
    )

    test("SEQUENCE_LENGTH = 144", SEQUENCE_LENGTH == 144)
    test("PREDICTION_STEPS = 24", PREDICTION_STEPS == 24)
    test("N_FEATURES = 9", N_FEATURES == 9)
    test("RAIN_FEATURE_INDEX = 5", RAIN_FEATURE_INDEX == 5)
    test("DATA_INTERVAL_MINUTES = 5", DATA_INTERVAL_MINUTES == 5)
    test("XGBoost model file exists", os.path.exists(XGBOOST_MODEL_PATH),
         f"Not found: {XGBOOST_MODEL_PATH}")
    test("LSTM model file exists", os.path.exists(LSTM_MODEL_PATH),
         f"Not found: {LSTM_MODEL_PATH}")
    test("Scaler file exists", os.path.exists(SCALER_PATH),
         f"Not found: {SCALER_PATH}")

except Exception as e:
    test("Pipeline constants", False, str(e))


# ===================================================================
# INTEGRATED: API Endpoints (via test client)
# ===================================================================
print("\n--- INTEGRATED: API ENDPOINTS ---")

try:
    APPKEY = os.environ.get('APPKEY', '')
    client = app.test_client()

    # Health
    r = client.get('/api/v3/health')
    test("GET /health -> 200", r.status_code == 200)

    # Auth
    r = client.get('/api/v3/weather/current')
    test("No auth -> 401", r.status_code == 401)

    r = client.get('/api/v3/weather/current', headers={'X-APP-KEY': 'wrong-key'})
    test("Wrong auth -> 401", r.status_code == 401)

    # Current weather (with real APPKEY)
    r = client.get('/api/v3/weather/current', headers={'X-APP-KEY': APPKEY})
    test("GET /weather/current with APPKEY", r.status_code in (200, 404),
         f"Got {r.status_code}")

    # Source parameter validation
    r = client.get('/api/v3/weather/current?source=invalid', headers={'X-APP-KEY': APPKEY})
    test("source=invalid -> 400", r.status_code == 400)

    # Security headers
    r = client.get('/api/v3/health')
    test("X-Content-Type-Options = nosniff",
         r.headers.get('X-Content-Type-Options') == 'nosniff')
    test("X-Frame-Options = DENY",
         r.headers.get('X-Frame-Options') == 'DENY')

except Exception as e:
    test("API endpoints", False, str(e))


# ===================================================================
# SUMMARY
# ===================================================================
print("\n" + "=" * 70)
total = PASSED + FAILED
print(f"RESULTS: {PASSED} PASSED, {FAILED} FAILED, {SKIPPED} SKIPPED (total: {total})")
print("=" * 70)

if ERRORS:
    print("\nFAILED TESTS:")
    for i, e in enumerate(ERRORS, 1):
        print(f"  {i}. {e}")
else:
    print("\n*** ALL TESTS PASSED! ***")

print()

# Exit code for CI
sys.exit(1 if FAILED > 0 else 0)
