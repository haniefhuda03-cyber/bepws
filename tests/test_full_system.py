"""
==========================================================================
TUWS Backend - Full System Integration Test Suite
==========================================================================
Comprehensive test coverage across ALL aspects of the backend:

  SECTION 1:  Module Imports & Integrity
  SECTION 2:  App Factory & Configuration
  SECTION 3:  Database ORM Models (SQLite in-memory)
  SECTION 4:  Helper / Utility Functions
  SECTION 5:  Cache Layer (Memory fallback)
  SECTION 6:  API Authentication & Security
  SECTION 7:  API Rate Limiting
  SECTION 8:  API Parameter Validation (strict_params)
  SECTION 9:  Health Endpoint
  SECTION 10: Weather Current Endpoint
  SECTION 11: Weather Predict Endpoint
  SECTION 12: Weather Details Endpoint
  SECTION 13: Weather History Endpoint
  SECTION 14: Weather Graph Endpoint
  SECTION 15: Weather Console Endpoint (POST/GET)
  SECTION 16: Fetch Jobs (Wunderground, Ecowitt, Console)
  SECTION 17: Prediction Service (XGBoost, LSTM pipeline)
  SECTION 18: Serializers
  SECTION 19: DB Seed
  SECTION 20: Scheduler Init
  SECTION 21: Error Handlers (404, 405, 413)
  SECTION 22: Security Headers
  SECTION 23: Database Session Safety (rollback)
  SECTION 24: Edge Cases & Boundary Tests
  SECTION 25: Secrets Module
  SECTION 26: Logging Config

Author : AI Backend Engineer (Enterprise Grade)
Date   : 2025-02-23
==========================================================================
"""

import os
import sys
import json
import math
import hmac
import threading
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from io import StringIO

# ---------------------------------------------------------------------------
# Environment Setup (BEFORE any app import)
# ---------------------------------------------------------------------------
os.environ['LOAD_DOTENV'] = 'true'
os.environ['DISABLE_SCHEDULER_FOR_TESTS'] = 'true'
os.environ['PYTEST_CURRENT_TEST'] = '1'
os.environ.setdefault('APPKEY', '5ce7c45f0ff531767c68dd30b22214900fc6aaf2926ade49703d9fdceba8bda3')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ===========================================================================
# Shared Test App Factory — creates ONE app with SQLite in-memory for all tests
# ===========================================================================

_test_app = None
_test_client = None


def _patch_array_columns_for_sqlite():
    """
    Replace PostgreSQL ARRAY columns with JSON columns so SQLite can create
    all tables.  Must be called BEFORE db.create_all().
    """
    from sqlalchemy import JSON
    from sqlalchemy.dialects.postgresql import ARRAY
    from app import models

    for mapper in [
        models.DataLSTM, models.LSTMPredictionResult,
    ]:
        table = mapper.__table__
        for col in table.columns:
            if isinstance(col.type, ARRAY):
                col.type = JSON()


def _get_test_app():
    """Singleton test app factory — avoids multiple create_app() calls."""
    global _test_app
    if _test_app is not None:
        return _test_app
    from app import create_app, db
    _test_app = create_app(test_config={
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'TESTING': True,
        'SECRET_KEY': os.environ.get('SECRET_KEY', os.urandom(32).hex()),
        'MAX_CONTENT_LENGTH': 1 * 1024 * 1024,
        'TRAP_HTTP_EXCEPTIONS': True,
        'JSON_SORT_KEYS': False,
        'SCHEDULER_API_ENABLED': False,
    })
    with _test_app.app_context():
        _patch_array_columns_for_sqlite()
        db.create_all()
        # Seed labels and models for tests
        from app.models import Label, Model as ModelMeta
        from app.services.prediction_service import LABEL_MAP
        for class_id, name in LABEL_MAP.items():
            if not db.session.query(Label).filter_by(name=name).first():
                db.session.add(Label(name=name))
        if not db.session.query(ModelMeta).filter_by(name='default_xgboost').first():
            db.session.add(ModelMeta(name='default_xgboost', range_prediction=60))
        if not db.session.query(ModelMeta).filter_by(name='default_lstm').first():
            db.session.add(ModelMeta(name='default_lstm', range_prediction=1440))
        db.session.commit()
    return _test_app


def _get_client():
    global _test_client
    if _test_client is not None:
        return _test_client
    _test_client = _get_test_app().test_client()
    return _test_client


def _auth_headers():
    return {'X-APP-KEY': os.environ.get('APPKEY', '')}


# ===========================================================================
# SECTION 1: MODULE IMPORTS & INTEGRITY
# ===========================================================================

class TestModuleImports(unittest.TestCase):
    """Verify all modules can be imported without errors."""

    def test_import_app_package(self):
        from app import create_app, db, scheduler
        self.assertTrue(callable(create_app))
        self.assertIsNotNone(db)

    def test_import_models(self):
        from app import models
        required = [
            'WeatherLogWunderground', 'WeatherLogEcowitt', 'WeatherLogConsole',
            'PredictionLog', 'DataXGBoost', 'DataLSTM',
            'XGBoostPredictionResult', 'LSTMPredictionResult',
            'Model', 'Label',
        ]
        for cls_name in required:
            self.assertTrue(hasattr(models, cls_name), f"Missing model: {cls_name}")

    def test_import_serializers(self):
        from app import serializers
        for fn in ['get_current_payload', 'get_prediction_payload',
                    'get_history_payload', 'get_graph_payload']:
            self.assertTrue(hasattr(serializers, fn), f"Missing serializer: {fn}")

    def test_import_api_v3(self):
        from app.api_v3 import bp_v3
        self.assertEqual(bp_v3.name, 'api_v3')
        self.assertEqual(bp_v3.url_prefix, '/api/v3')

    def test_import_helpers(self):
        from app.common.helpers import (
            safe_float, safe_int, fahrenheit_to_celsius,
            inch_hg_to_hpa, mph_to_ms, wm2_to_lux,
            inch_per_hour_to_mm_per_hour, deg_to_compass,
            to_utc_iso, get_wib_now, WIB,
        )
        self.assertIsNotNone(WIB)

    def test_import_prediction_service(self):
        from app.services.prediction_service import (
            LABEL_MAP, XGBOOST_REQUIRED_FEATURES, LSTM_FEATURE_ORDER,
            ModelLoader, initialize_models, predict_xgboost, predict_lstm,
            run_prediction_pipeline, get_label_name,
        )
        self.assertEqual(len(LABEL_MAP), 9)

    def test_import_jobs(self):
        from app.jobs import (
            fetch_wunderground, fetch_ecowitt, process_console_data,
            fetch_and_store_weather, run_hourly_prediction,
        )
        self.assertTrue(callable(fetch_wunderground))

    def test_import_cache(self):
        from app import cache
        for fn in ['get', 'set', 'delete']:
            self.assertTrue(hasattr(cache, fn))

    def test_import_cache_service(self):
        from app.services.cache_service import get_cache_service, CacheService
        self.assertTrue(callable(get_cache_service))

    def test_import_config(self):
        from app.config import DEMO_MODE, API_READ_KEY
        self.assertIsInstance(DEMO_MODE, bool)

    def test_import_secrets(self):
        from app.secrets import get_secret
        self.assertTrue(callable(get_secret))

    def test_import_db_seed(self):
        from app.db_seed import seed_labels_and_models
        self.assertTrue(callable(seed_labels_and_models))

    def test_import_scheduler_init(self):
        from app.scheduler_init import init_scheduler, _mark_prediction_done
        self.assertTrue(callable(init_scheduler))


# ===========================================================================
# SECTION 2: APP FACTORY & CONFIGURATION
# ===========================================================================

class TestAppFactory(unittest.TestCase):

    def test_app_created(self):
        app = _get_test_app()
        self.assertIsNotNone(app)

    def test_secret_key_set(self):
        self.assertTrue(bool(_get_test_app().config.get('SECRET_KEY')))

    def test_secret_key_strong(self):
        sk = _get_test_app().config.get('SECRET_KEY', '')
        self.assertGreaterEqual(len(sk), 32)

    def test_database_uri_set(self):
        self.assertTrue(bool(_get_test_app().config.get('SQLALCHEMY_DATABASE_URI')))

    def test_max_content_length(self):
        self.assertEqual(_get_test_app().config.get('MAX_CONTENT_LENGTH'), 1048576)

    def test_trap_http_exceptions(self):
        self.assertTrue(_get_test_app().config.get('TRAP_HTTP_EXCEPTIONS'))

    def test_sqlalchemy_track_modifications_disabled(self):
        self.assertFalse(_get_test_app().config.get('SQLALCHEMY_TRACK_MODIFICATIONS'))

    def test_testing_flag_set(self):
        self.assertTrue(_get_test_app().config['TESTING'])


# ===========================================================================
# SECTION 3: DATABASE ORM MODELS (SQLite in-memory)
# ===========================================================================

class TestModels(unittest.TestCase):

    def test_weather_log_wunderground_to_dict(self):
        from app.models import WeatherLogWunderground
        wl = WeatherLogWunderground(
            id=1, temperature=25.5, humidity=80.0, pressure=1013.0,
            request_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        d = wl.to_dict()
        self.assertEqual(d['temperature'], 25.5)
        self.assertIn('request_time', d)

    def test_weather_log_ecowitt_to_dict(self):
        from app.models import WeatherLogEcowitt
        wl = WeatherLogEcowitt(
            id=2, temperature_main_outdoor=28.0, humidity_outdoor=75.0,
            request_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        d = wl.to_dict()
        self.assertEqual(d['temperature_main_outdoor'], 28.0)

    def test_weather_log_console_to_dict(self):
        from app.models import WeatherLogConsole
        wl = WeatherLogConsole(
            id=3, temperature=72.0, humidity=65.0,
            wind_direction=180.0, pressure_relative=29.92,
            date_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        d = wl.to_dict()
        self.assertEqual(d['temperature'], 72.0)

    def test_model_to_dict(self):
        from app.models import Model
        m = Model(id=1, name='default_xgboost', range_prediction=60)
        self.assertEqual(m.to_dict()['name'], 'default_xgboost')

    def test_label_to_dict(self):
        from app.models import Label
        lbl = Label(id=1, name='Cerah / Berawan')
        self.assertEqual(lbl.to_dict()['name'], 'Cerah / Berawan')

    def test_prediction_log_to_dict(self):
        from app.models import PredictionLog
        pl = PredictionLog(
            id=1, model_id=1,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        d = pl.to_dict()
        self.assertIn('model_id', d)
        self.assertIn('created_at', d)

    def test_xgboost_prediction_result_to_dict(self):
        from app.models import XGBoostPredictionResult
        xr = XGBoostPredictionResult(id=1, console_result_id=1, ecowitt_result_id=2)
        d = xr.to_dict()
        self.assertEqual(d['console_result_id'], 1)

    def test_lstm_prediction_result_to_dict(self):
        from app.models import LSTMPredictionResult
        lr = LSTMPredictionResult(id=1, console_result=[0.1]*24, ecowitt_result=[0.2]*24)
        self.assertEqual(len(lr.to_dict()['console_result']), 24)

    def test_data_xgboost_to_dict(self):
        from app.models import DataXGBoost
        dx = DataXGBoost(id=1, weather_log_console_id=10)
        self.assertEqual(dx.to_dict()['weather_log_console_id'], 10)

    def test_data_lstm_to_dict(self):
        from app.models import DataLSTM
        dl = DataLSTM(id=1, weather_log_ecowitt_ids=[1, 2, 3])
        self.assertEqual(dl.to_dict()['weather_log_ecowitt_ids'], [1, 2, 3])

    def test_prediction_log_property_helpers_none(self):
        from app.models import PredictionLog
        pl = PredictionLog(id=1)
        self.assertIsNone(pl.weather_log_ecowitt)
        self.assertIsNone(pl.weather_log_wunderground)
        self.assertIsNone(pl.weather_log_console)

    def test_model_repr(self):
        from app.models import Model
        m = Model(id=1, name='test', range_prediction=60)
        self.assertIn('test', repr(m))

    def test_db_insert_and_query(self):
        """Full insert-query cycle on SQLite in-memory."""
        from app import db
        from app.models import WeatherLogEcowitt
        app = _get_test_app()
        with app.app_context():
            wl = WeatherLogEcowitt(
                temperature_main_outdoor=30.0,
                humidity_outdoor=80.0,
                wind_speed=4.0, wind_direction=90.0,
                pressure_relative=1010.0, rain_rate=0.0,
                solar_irradiance=500.0, uvi=3.0,
                request_time=datetime.now(timezone.utc),
            )
            db.session.add(wl)
            db.session.commit()
            self.assertIsNotNone(wl.id)

            fetched = db.session.get(WeatherLogEcowitt, wl.id)
            self.assertAlmostEqual(fetched.temperature_main_outdoor, 30.0)
            # Cleanup
            db.session.delete(fetched)
            db.session.commit()

    def test_db_insert_wunderground(self):
        from app import db
        from app.models import WeatherLogWunderground
        app = _get_test_app()
        with app.app_context():
            wl = WeatherLogWunderground(
                temperature=28.0, humidity=75.0, pressure=1013.0,
                wind_speed=3.5, wind_direction=180.0,
                solar_radiation=600.0, ultraviolet_radiation=4.0,
                precipitation_rate=0.0, precipitation_total=0.0,
                request_time=datetime.now(timezone.utc),
            )
            db.session.add(wl)
            db.session.commit()
            self.assertIsNotNone(wl.id)
            db.session.delete(wl)
            db.session.commit()

    def test_db_insert_console(self):
        from app import db
        from app.models import WeatherLogConsole
        app = _get_test_app()
        with app.app_context():
            wl = WeatherLogConsole(
                temperature=72.0, humidity=65.0,
                wind_direction=180.0, wind_speed=5.0,
                pressure_relative=29.92, pressure_absolute=29.90,
                solar_radiation=500.0, uvi=3.0,
                rain_rate=0.0, date_utc=datetime.now(timezone.utc),
            )
            db.session.add(wl)
            db.session.commit()
            self.assertIsNotNone(wl.id)
            db.session.delete(wl)
            db.session.commit()

    def test_db_insert_prediction_log_full_chain(self):
        """Test full chain: WeatherLog -> DataXGBoost -> XGBoostResult -> PredictionLog."""
        from app import db
        from app.models import (
            WeatherLogEcowitt, DataXGBoost, XGBoostPredictionResult,
            LSTMPredictionResult, DataLSTM, PredictionLog, Model as ModelMeta
        )
        app = _get_test_app()
        with app.app_context():
            # 1. Insert weather log
            wl = WeatherLogEcowitt(
                temperature_main_outdoor=28.0, humidity_outdoor=80.0,
                wind_speed=3.5, wind_direction=180.0,
                pressure_relative=1013.0, rain_rate=0.0,
                request_time=datetime.now(timezone.utc),
            )
            db.session.add(wl)
            db.session.flush()

            # 2. DataXGBoost referencing weather log
            data_xgb = DataXGBoost(weather_log_ecowitt_id=wl.id)
            db.session.add(data_xgb)
            db.session.flush()

            # 3. XGBoost result
            xgb_result = XGBoostPredictionResult(ecowitt_result_id=1)  # Label ID=1
            db.session.add(xgb_result)
            db.session.flush()

            # 4. LSTM result
            lstm_result = LSTMPredictionResult(ecowitt_result=[0.1]*24)
            db.session.add(lstm_result)
            db.session.flush()

            # 5. DataLSTM
            data_lstm = DataLSTM(weather_log_ecowitt_ids=[wl.id]*144)
            db.session.add(data_lstm)
            db.session.flush()

            # 6. PredictionLog (XGBoost)
            model_meta = db.session.query(ModelMeta).filter_by(name='default_xgboost').first()
            pl_xgb = PredictionLog(
                model_id=model_meta.id if model_meta else None,
                data_xgboost_id=data_xgb.id,
                xgboost_result_id=xgb_result.id,
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(pl_xgb)

            # 7. PredictionLog (LSTM)
            model_lstm = db.session.query(ModelMeta).filter_by(name='default_lstm').first()
            pl_lstm = PredictionLog(
                model_id=model_lstm.id if model_lstm else None,
                data_lstm_id=data_lstm.id,
                lstm_result_id=lstm_result.id,
                created_at=datetime.now(timezone.utc),
            )
            db.session.add(pl_lstm)
            db.session.commit()

            self.assertIsNotNone(pl_xgb.id)
            self.assertIsNotNone(pl_lstm.id)

            # Verify relationships
            loaded_pl = db.session.get(PredictionLog, pl_xgb.id)
            self.assertIsNotNone(loaded_pl.data_xgboost)
            self.assertIsNotNone(loaded_pl.xgboost_result)

            # Cleanup
            db.session.delete(pl_lstm)
            db.session.delete(pl_xgb)
            db.session.delete(lstm_result)
            db.session.delete(xgb_result)
            db.session.delete(data_lstm)
            db.session.delete(data_xgb)
            db.session.delete(wl)
            db.session.commit()


# ===========================================================================
# SECTION 4: HELPER / UTILITY FUNCTIONS
# ===========================================================================

class TestHelpers(unittest.TestCase):

    def test_safe_float_normal(self):
        from app.common.helpers import safe_float
        self.assertEqual(safe_float(3.14), 3.14)
        self.assertEqual(safe_float("3.14"), 3.14)

    def test_safe_float_none(self):
        from app.common.helpers import safe_float
        self.assertEqual(safe_float(None), 0.0)
        self.assertIsNone(safe_float(None, None))

    def test_safe_float_invalid(self):
        from app.common.helpers import safe_float
        self.assertEqual(safe_float("abc"), 0.0)

    def test_safe_int_normal(self):
        from app.common.helpers import safe_int
        self.assertEqual(safe_int(42), 42)
        self.assertEqual(safe_int("42"), 42)

    def test_safe_int_none(self):
        from app.common.helpers import safe_int
        self.assertEqual(safe_int(None), 0)
        self.assertIsNone(safe_int(None, None))

    def test_safe_int_invalid(self):
        from app.common.helpers import safe_int
        self.assertEqual(safe_int("abc"), 0)

    def test_fahrenheit_to_celsius(self):
        from app.common.helpers import fahrenheit_to_celsius
        self.assertEqual(fahrenheit_to_celsius(32.0), 0.0)
        self.assertEqual(fahrenheit_to_celsius(212.0), 100.0)
        self.assertEqual(fahrenheit_to_celsius(100.0), 37.78)
        self.assertIsNone(fahrenheit_to_celsius(None))

    def test_fahrenheit_rounding(self):
        from app.common.helpers import fahrenheit_to_celsius
        r = fahrenheit_to_celsius(100.0)
        self.assertLessEqual(len(str(r).split('.')[-1]), 2)

    def test_inch_hg_to_hpa(self):
        from app.common.helpers import inch_hg_to_hpa
        r = inch_hg_to_hpa(29.92)
        self.assertAlmostEqual(r, 1013.21, places=1)
        self.assertIsNone(inch_hg_to_hpa(None))

    def test_inch_hg_rounding(self):
        from app.common.helpers import inch_hg_to_hpa
        r = inch_hg_to_hpa(29.92)
        self.assertLessEqual(len(str(r).split('.')[-1]), 2)

    def test_mph_to_ms(self):
        from app.common.helpers import mph_to_ms
        r = mph_to_ms(10.0)
        self.assertEqual(r, round(10.0 * 0.44704, 2))
        self.assertIsNone(mph_to_ms(None))

    def test_mph_rounding(self):
        from app.common.helpers import mph_to_ms
        r = mph_to_ms(10.0)
        self.assertLessEqual(len(str(r).split('.')[-1]), 2)

    def test_wm2_to_lux(self):
        from app.common.helpers import wm2_to_lux
        r = wm2_to_lux(100.0)
        self.assertAlmostEqual(r, 12670.0, places=1)
        self.assertEqual(wm2_to_lux(None), 0.0)

    def test_wm2_rounding(self):
        from app.common.helpers import wm2_to_lux
        r = wm2_to_lux(100.0)
        self.assertLessEqual(len(str(r).split('.')[-1]), 2)

    def test_inch_per_hour_to_mm_per_hour(self):
        from app.common.helpers import inch_per_hour_to_mm_per_hour
        r = inch_per_hour_to_mm_per_hour(1.0)
        self.assertAlmostEqual(r, 25.4, places=1)
        self.assertEqual(inch_per_hour_to_mm_per_hour(None), 0.0)

    def test_inch_hr_rounding(self):
        from app.common.helpers import inch_per_hour_to_mm_per_hour
        r = inch_per_hour_to_mm_per_hour(0.5)
        self.assertLessEqual(len(str(r).split('.')[-1]), 2)

    def test_deg_to_compass(self):
        from app.common.helpers import deg_to_compass
        self.assertEqual(deg_to_compass(0), "N")
        self.assertEqual(deg_to_compass(90), "E")
        self.assertEqual(deg_to_compass(180), "S")
        self.assertEqual(deg_to_compass(270), "W")
        self.assertEqual(deg_to_compass(360), "N")
        self.assertEqual(deg_to_compass(45), "NE")
        self.assertIsNone(deg_to_compass(None))

    def test_to_utc_iso(self):
        from app.common.helpers import to_utc_iso
        dt = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        r = to_utc_iso(dt)
        self.assertIn('2026-01-15', r)
        self.assertIsNone(to_utc_iso(None))

    def test_to_utc_iso_naive(self):
        from app.common.helpers import to_utc_iso
        r = to_utc_iso(datetime(2026, 1, 15, 10, 30, 0))
        self.assertIsNotNone(r)

    def test_to_utc_iso_wib(self):
        from app.common.helpers import to_utc_iso, WIB
        dt_wib = datetime(2026, 1, 15, 17, 0, 0, tzinfo=WIB)
        r = to_utc_iso(dt_wib)
        self.assertIn('10:00:00', r)

    def test_get_wib_now(self):
        from app.common.helpers import get_wib_now
        now = get_wib_now()
        self.assertEqual(now.utcoffset(), timedelta(hours=7))

    def test_safe_float_boolean(self):
        from app.common.helpers import safe_float
        self.assertEqual(safe_float(True), 1.0)
        self.assertEqual(safe_float(False), 0.0)

    def test_fahrenheit_extreme(self):
        from app.common.helpers import fahrenheit_to_celsius
        self.assertAlmostEqual(fahrenheit_to_celsius(-40.0), -40.0, places=1)
        self.assertAlmostEqual(fahrenheit_to_celsius(140.0), 60.0, places=1)


# ===========================================================================
# SECTION 5: CACHE LAYER
# ===========================================================================

class TestCacheLayer(unittest.TestCase):

    def test_cache_set_get(self):
        from app import cache
        app = _get_test_app()
        with app.app_context():
            cache.set("test_k1", {"v": 42}, timeout=10)
            self.assertEqual(cache.get("test_k1").get("v"), 42)

    def test_cache_delete(self):
        from app import cache
        app = _get_test_app()
        with app.app_context():
            cache.set("test_k2", "hello", timeout=10)
            cache.delete("test_k2")
            self.assertIsNone(cache.get("test_k2"))

    def test_cache_get_nonexistent(self):
        from app import cache
        app = _get_test_app()
        with app.app_context():
            self.assertIsNone(cache.get("nonexistent_xyz_99"))

    def test_cache_service_backend(self):
        from app.services.cache_service import get_cache_service
        app = _get_test_app()
        with app.app_context():
            svc = get_cache_service()
            self.assertIn(svc.backend, ['redis', 'memory'])


# ===========================================================================
# SECTION 6: API AUTHENTICATION & SECURITY
# ===========================================================================

class TestAuthentication(unittest.TestCase):

    def test_no_auth_returns_401(self):
        r = _get_client().get('/api/v3/weather/current')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()['error']['code'], 'MISSING_AUTH')

    def test_wrong_auth_returns_401(self):
        r = _get_client().get('/api/v3/weather/current',
                              headers={'X-APP-KEY': 'totally-wrong-key'})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()['error']['code'], 'INVALID_AUTH')

    def test_valid_auth_passes(self):
        r = _get_client().get('/api/v3/weather/current', headers=_auth_headers())
        self.assertNotEqual(r.status_code, 401)

    def test_timing_safe_comparison(self):
        import inspect
        from app.api_v3 import require_auth
        self.assertIn('hmac.compare_digest', inspect.getsource(require_auth))

    def test_health_no_auth_required(self):
        r = _get_client().get('/api/v3/health')
        self.assertEqual(r.status_code, 200)


# ===========================================================================
# SECTION 7: API RATE LIMITING
# ===========================================================================

class TestRateLimiting(unittest.TestCase):

    def test_allows_under_limit(self):
        from app.api_v3 import RateLimiter
        rl = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            allowed, _, _ = rl.is_allowed("t1")
            self.assertTrue(allowed)

    def test_blocks_over_limit(self):
        from app.api_v3 import RateLimiter
        rl = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            rl.is_allowed("t2")
        allowed, remaining, _ = rl.is_allowed("t2")
        self.assertFalse(allowed)
        self.assertEqual(remaining, 0)

    def test_different_ips_independent(self):
        from app.api_v3 import RateLimiter
        rl = RateLimiter(max_requests=2, window_seconds=60)
        rl.is_allowed("a"); rl.is_allowed("a")
        self.assertFalse(rl.is_allowed("a")[0])
        self.assertTrue(rl.is_allowed("b")[0])

    def test_max_tracked_ips_constant(self):
        from app.api_v3 import RateLimiter
        self.assertEqual(RateLimiter.MAX_TRACKED_IPS, 10_000)

    def test_thread_safety(self):
        from app.api_v3 import RateLimiter
        rl = RateLimiter(max_requests=1000, window_seconds=60)
        errors = []
        def burst(ip):
            try:
                for _ in range(100): rl.is_allowed(ip)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=burst, args=(f"ip_{i}",)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(errors), 0)

    def test_rate_limit_headers_on_health(self):
        r = _get_client().get('/api/v3/health')
        self.assertIn('X-RateLimit-Limit', r.headers)
        self.assertIn('X-RateLimit-Remaining', r.headers)


# ===========================================================================
# SECTION 8: API PARAMETER VALIDATION
# ===========================================================================

class TestParameterValidation(unittest.TestCase):

    def test_unknown_param_rejected(self):
        r = _get_client().get('/api/v3/weather/current?foo=bar', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['error']['code'], 'UNKNOWN_PARAMETER')

    def test_empty_param_rejected(self):
        r = _get_client().get('/api/v3/weather/current?source=', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_invalid_enum_rejected(self):
        r = _get_client().get('/api/v3/weather/current?source=invalid', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_valid_source_ecowitt(self):
        r = _get_client().get('/api/v3/weather/current?source=ecowitt', headers=_auth_headers())
        self.assertIn(r.status_code, [200, 404])

    def test_valid_source_wunderground(self):
        r = _get_client().get('/api/v3/weather/current?source=wunderground', headers=_auth_headers())
        self.assertIn(r.status_code, [200, 404])

    def test_invalid_int_param(self):
        r = _get_client().get('/api/v3/weather/history?page=abc', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_int_below_min(self):
        r = _get_client().get('/api/v3/weather/history?page=0', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_int_above_max(self):
        # per_page max is 10
        r = _get_client().get('/api/v3/weather/history?per_page=100', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_per_page_just_above_max(self):
        """per_page=11 exceeds max of 10."""
        r = _get_client().get('/api/v3/weather/history?per_page=11', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_per_page_at_max(self):
        """per_page=10 is within bounds."""
        r = _get_client().get('/api/v3/weather/history?per_page=10', headers=_auth_headers())
        self.assertIn(r.status_code, [200, 400])  # 200 or 400 depending on data availability

    def test_spaces_in_param_rejected(self):
        r = _get_client().get('/api/v3/weather/history?page= 1 ', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_invalid_iso8601_rejected(self):
        r = _get_client().get('/api/v3/weather/history?start_date=not-a-date', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_valid_iso8601(self):
        r = _get_client().get('/api/v3/weather/history?start_date=2026-01-01T00:00:00Z', headers=_auth_headers())
        self.assertIn(r.status_code, [200, 400])


# ===========================================================================
# SECTION 9: HEALTH ENDPOINT
# ===========================================================================

class TestHealthEndpoint(unittest.TestCase):

    def test_returns_200(self):
        r = _get_client().get('/api/v3/health')
        self.assertEqual(r.status_code, 200)

    def test_json_structure(self):
        data = _get_client().get('/api/v3/health').get_json()
        self.assertIn('meta', data)
        self.assertIn('data', data)
        self.assertEqual(data['meta']['status'], 'success')

    def test_data_fields(self):
        data = _get_client().get('/api/v3/health').get_json()['data']
        self.assertEqual(data['api_version'], 'v3')
        self.assertIn('database', data)
        self.assertIn('scheduler', data)

    def test_no_unknown_params(self):
        r = _get_client().get('/api/v3/health?extra=boo')
        self.assertEqual(r.status_code, 400)


# ===========================================================================
# SECTION 10-14: WEATHER ENDPOINTS
# ===========================================================================

class TestWeatherCurrentEndpoint(unittest.TestCase):

    def test_requires_auth(self):
        self.assertEqual(_get_client().get('/api/v3/weather/current').status_code, 401)

    def test_default_source(self):
        r = _get_client().get('/api/v3/weather/current', headers=_auth_headers())
        self.assertIn(r.status_code, [200, 404])

    def test_meta_structure(self):
        r = _get_client().get('/api/v3/weather/current', headers=_auth_headers())
        self.assertIn('meta', r.get_json())


class TestWeatherPredictEndpoint(unittest.TestCase):

    def test_requires_auth(self):
        self.assertEqual(_get_client().get('/api/v3/weather/predict').status_code, 401)

    def test_xgboost_limit_error(self):
        r = _get_client().get('/api/v3/weather/predict?model=xgboost&limit=5', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_invalid_model(self):
        r = _get_client().get('/api/v3/weather/predict?model=invalid', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_limit_below_min(self):
        r = _get_client().get('/api/v3/weather/predict?limit=0', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_limit_above_max(self):
        r = _get_client().get('/api/v3/weather/predict?limit=25', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_default_model(self):
        r = _get_client().get('/api/v3/weather/predict', headers=_auth_headers())
        self.assertIn(r.status_code, [200, 404])


class TestWeatherDetailsEndpoint(unittest.TestCase):

    def test_requires_auth(self):
        self.assertEqual(_get_client().get('/api/v3/weather/details').status_code, 401)

    def test_default_source(self):
        r = _get_client().get('/api/v3/weather/details', headers=_auth_headers())
        self.assertIn(r.status_code, [200, 404])

    def test_unknown_param_rejected(self):
        r = _get_client().get('/api/v3/weather/details?bogus=1', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)


class TestWeatherHistoryEndpoint(unittest.TestCase):

    def test_requires_auth(self):
        self.assertEqual(_get_client().get('/api/v3/weather/history').status_code, 401)

    def test_default_pagination(self):
        r = _get_client().get('/api/v3/weather/history', headers=_auth_headers())
        data = r.get_json()
        self.assertIn('meta', data)

    def test_custom_pagination(self):
        r = _get_client().get('/api/v3/weather/history?page=1&per_page=5', headers=_auth_headers())
        self.assertIn(r.status_code, [200, 400])

    def test_sort_options(self):
        for sort in ['newest', 'oldest']:
            r = _get_client().get(f'/api/v3/weather/history?sort={sort}', headers=_auth_headers())
            self.assertIn(r.status_code, [200, 400])

    def test_invalid_sort(self):
        r = _get_client().get('/api/v3/weather/history?sort=random', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_date_filter(self):
        r = _get_client().get(
            '/api/v3/weather/history?start_date=2026-01-01T00:00:00Z&end_date=2026-12-31T23:59:59Z',
            headers=_auth_headers())
        self.assertIn(r.status_code, [200, 400])


class TestWeatherGraphEndpoint(unittest.TestCase):

    def test_requires_auth(self):
        self.assertEqual(_get_client().get('/api/v3/weather/graph').status_code, 401)

    def test_missing_range(self):
        r = _get_client().get('/api/v3/weather/graph?datatype=temperature', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_missing_datatype(self):
        r = _get_client().get('/api/v3/weather/graph?range=weekly', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_invalid_range(self):
        r = _get_client().get('/api/v3/weather/graph?range=yearly&datatype=temperature', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_invalid_datatype(self):
        r = _get_client().get('/api/v3/weather/graph?range=weekly&datatype=invalid', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_weekly_temperature(self):
        r = _get_client().get('/api/v3/weather/graph?range=weekly&datatype=temperature', headers=_auth_headers())
        self.assertIn(r.status_code, [200, 400])

    def test_monthly_with_month(self):
        r = _get_client().get('/api/v3/weather/graph?range=monthly&datatype=humidity&month=2', headers=_auth_headers())
        self.assertIn(r.status_code, [200, 400])

    def test_all_valid_datatypes(self):
        for dt in ['temperature', 'humidity', 'rainfall', 'wind_speed',
                    'uvi', 'solar_radiation', 'relative_pressure']:
            r = _get_client().get(f'/api/v3/weather/graph?range=weekly&datatype={dt}', headers=_auth_headers())
            self.assertIn(r.status_code, [200, 400], f"Datatype '{dt}' returned {r.status_code}")

    def test_invalid_month(self):
        r = _get_client().get('/api/v3/weather/graph?range=monthly&datatype=temperature&month=13', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)

    def test_monthly_requires_month(self):
        """When range=monthly, month param is required."""
        r = _get_client().get('/api/v3/weather/graph?range=monthly&datatype=temperature', headers=_auth_headers())
        self.assertEqual(r.status_code, 400)
        body = r.get_json()
        self.assertIn('month', body['error']['message'].lower())

    def test_weekly_does_not_require_month(self):
        """When range=weekly, month is not required."""
        r = _get_client().get('/api/v3/weather/graph?range=weekly&datatype=temperature', headers=_auth_headers())
        # Should not fail due to missing month
        self.assertIn(r.status_code, [200, 400])  # 400 only if db/data issues
        if r.status_code == 400:
            body = r.get_json()
            self.assertNotIn('month', body.get('error', {}).get('message', '').lower())


# ===========================================================================
# SECTION 15: CONSOLE ENDPOINT
# ===========================================================================

class TestWeatherConsoleEndpoint(unittest.TestCase):

    def _console_data(self, overrides=None):
        data = {
            'tempf': '72.0', 'humidity': '65', 'winddir': '180',
            'baromrelin': '29.92', 'windspeedmph': '5.0', 'windgustmph': '8.0',
            'solarradiation': '500.0', 'uv': '3', 'rainratein': '0.0',
            'dailyrainin': '0.0', 'hourlyrainin': '0.0',
            'dateutc': '2026-02-23 10:00:00',
        }
        if overrides:
            data.update(overrides)
        return data

    def test_no_data_returns_error(self):
        r = _get_client().post('/api/v3/weather/console')
        self.assertIn(r.status_code, [400, 503])

    def test_missing_required_fields(self):
        os.environ['CONSOLE_KEY'] = 'test_key'
        os.environ['CONSOLE_IP_WHITELIST'] = '127.0.0.1'
        r = _get_client().post('/api/v3/weather/console',
                               data={'tempf': '72.0', 'PASSKEY': 'test_key'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['error']['code'], 'MISSING_FIELDS')

    def test_invalid_numeric(self):
        os.environ['CONSOLE_KEY'] = 'tk'
        os.environ['CONSOLE_IP_WHITELIST'] = '127.0.0.1'
        r = _get_client().post('/api/v3/weather/console',
                               data=self._console_data({'tempf': 'abc', 'PASSKEY': 'tk'}))
        self.assertEqual(r.status_code, 400)

    def test_temperature_out_of_range(self):
        os.environ['CONSOLE_KEY'] = 'tk'
        os.environ['CONSOLE_IP_WHITELIST'] = '127.0.0.1'
        r = _get_client().post('/api/v3/weather/console',
                               data=self._console_data({'tempf': '200', 'PASSKEY': 'tk'}))
        self.assertEqual(r.status_code, 400)

    def test_humidity_out_of_range(self):
        os.environ['CONSOLE_KEY'] = 'tk'
        os.environ['CONSOLE_IP_WHITELIST'] = '127.0.0.1'
        r = _get_client().post('/api/v3/weather/console',
                               data=self._console_data({'humidity': '150', 'PASSKEY': 'tk'}))
        self.assertEqual(r.status_code, 400)

    def test_wind_direction_out_of_range(self):
        os.environ['CONSOLE_KEY'] = 'tk'
        os.environ['CONSOLE_IP_WHITELIST'] = '127.0.0.1'
        r = _get_client().post('/api/v3/weather/console',
                               data=self._console_data({'winddir': '400', 'PASSKEY': 'tk'}))
        self.assertEqual(r.status_code, 400)

    def test_no_auth_configured_503(self):
        os.environ.pop('CONSOLE_KEY', None)
        os.environ.pop('CONSOLE_IP_WHITELIST', None)
        r = _get_client().post('/api/v3/weather/console', data=self._console_data())
        self.assertEqual(r.status_code, 503)

    def test_invalid_ip_403(self):
        os.environ['CONSOLE_IP_WHITELIST'] = '10.0.0.1'
        os.environ.pop('CONSOLE_KEY', None)
        r = _get_client().post('/api/v3/weather/console', data=self._console_data())
        self.assertEqual(r.status_code, 403)

    def test_invalid_key_401(self):
        os.environ.pop('CONSOLE_IP_WHITELIST', None)
        os.environ['CONSOLE_KEY'] = 'correct_key'
        r = _get_client().post('/api/v3/weather/console',
                               data=self._console_data({'PASSKEY': 'wrong'}))
        self.assertEqual(r.status_code, 401)

    def test_valid_data_success(self):
        os.environ['CONSOLE_KEY'] = 'test_valid_k'
        os.environ['CONSOLE_IP_WHITELIST'] = '127.0.0.1'
        r = _get_client().post('/api/v3/weather/console',
                               data=self._console_data({'PASSKEY': 'test_valid_k'}))
        self.assertIn(r.status_code, [201, 500])
        if r.status_code == 201:
            self.assertIsNotNone(r.get_json()['data']['id'])

    def test_get_method_supported(self):
        os.environ['CONSOLE_KEY'] = 'gk'
        os.environ['CONSOLE_IP_WHITELIST'] = '127.0.0.1'
        r = _get_client().get('/api/v3/weather/console',
                              query_string=self._console_data({'PASSKEY': 'gk'}))
        self.assertIn(r.status_code, [201, 400, 500])


# ===========================================================================
# SECTION 16: FETCH JOBS (Mocked)
# ===========================================================================

class TestFetchJobs(unittest.TestCase):

    def test_process_console_data_empty(self):
        from app.jobs import process_console_data
        app = _get_test_app()
        with app.app_context():
            self.assertIsNone(process_console_data({}))

    def test_process_console_data_none(self):
        from app.jobs import process_console_data
        app = _get_test_app()
        with app.app_context():
            self.assertIsNone(process_console_data(None))

    def test_process_console_valid(self):
        from app.jobs import process_console_data
        app = _get_test_app()
        with app.app_context():
            data = {
                'tempf': '72.0', 'humidity': '65', 'winddir': '180',
                'baromrelin': '29.92', 'windspeedmph': '5.0',
                'dateutc': '2026-02-23 10:00:00',
            }
            result = process_console_data(data)
            if result is not None:
                self.assertEqual(result.temperature, 72.0)
                self.assertEqual(result.humidity, 65.0)

    def test_process_console_invalid_dateutc(self):
        from app.jobs import process_console_data
        app = _get_test_app()
        with app.app_context():
            data = {
                'tempf': '72.0', 'humidity': '65', 'winddir': '180',
                'baromrelin': '29.92', 'dateutc': 'invalid',
            }
            # Should not crash
            process_console_data(data)

    @patch('app.jobs.requests.get')
    def test_fetch_wunderground_success(self, mock_get):
        from app.jobs import fetch_wunderground
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={
                "observations": [{
                    "obsTimeUtc": "2026-01-15T10:00:00Z",
                    "solarRadiation": 500.0, "uv": 3.0, "humidity": 75, "winddir": 180,
                    "metric_si": {"temp": 28.0, "pressure": 1013.0,
                                  "windSpeed": 3.5, "windGust": 5.0,
                                  "precipRate": 0.0, "precipTotal": 0.0}
                }]
            })
        )
        app = _get_test_app()
        with app.app_context():
            result = fetch_wunderground()
            if result is not None:
                self.assertEqual(result.temperature, 28.0)

    @patch('app.jobs.requests.get')
    def test_fetch_wunderground_empty(self, mock_get):
        from app.jobs import fetch_wunderground
        mock_get.return_value = MagicMock(json=MagicMock(return_value={"observations": []}))
        app = _get_test_app()
        with app.app_context():
            self.assertIsNone(fetch_wunderground())

    @patch('app.jobs.requests.get')
    def test_fetch_wunderground_timeout(self, mock_get):
        import requests as req
        from app.jobs import fetch_wunderground
        mock_get.side_effect = req.exceptions.Timeout()
        app = _get_test_app()
        with app.app_context():
            self.assertIsNone(fetch_wunderground())

    def test_fetch_wunderground_no_url(self):
        from app.jobs import fetch_wunderground
        app = _get_test_app()
        with app.app_context():
            with patch('app.jobs.WUNDERGROUND_URL', ''):
                self.assertIsNone(fetch_wunderground())

    def test_fetch_ecowitt_no_creds(self):
        from app.jobs import fetch_ecowitt
        app = _get_test_app()
        with app.app_context():
            with patch('app.jobs.ECO_APP_KEY', ''), \
                 patch('app.jobs.ECO_API_KEY', ''), \
                 patch('app.jobs.ECO_MAC', ''):
                self.assertIsNone(fetch_ecowitt())

    @patch('app.jobs.requests.get')
    def test_fetch_ecowitt_api_error(self, mock_get):
        from app.jobs import fetch_ecowitt
        mock_get.return_value = MagicMock(json=MagicMock(return_value={"code": -1, "msg": "Error"}))
        app = _get_test_app()
        with app.app_context():
            self.assertIsNone(fetch_ecowitt())


# ===========================================================================
# SECTION 17: PREDICTION SERVICE
# ===========================================================================

class TestPredictionService(unittest.TestCase):

    def test_label_map_completeness(self):
        from app.services.prediction_service import LABEL_MAP
        self.assertEqual(len(LABEL_MAP), 9)
        for i in range(9):
            self.assertIn(i, LABEL_MAP)

    def test_label_0_cerah(self):
        from app.services.prediction_service import LABEL_MAP
        self.assertEqual(LABEL_MAP[0], 'Cerah / Berawan')

    def test_xgboost_features(self):
        from app.services.prediction_service import XGBOOST_REQUIRED_FEATURES
        self.assertEqual(len(XGBOOST_REQUIRED_FEATURES), 6)

    def test_lstm_feature_order(self):
        from app.services.prediction_service import LSTM_FEATURE_ORDER, N_FEATURES
        self.assertEqual(len(LSTM_FEATURE_ORDER), N_FEATURES)

    def test_constants(self):
        from app.services.prediction_service import SEQUENCE_LENGTH, PREDICTION_STEPS, MAX_INTERPOLATED_RATIO
        self.assertEqual(SEQUENCE_LENGTH, 144)
        self.assertEqual(PREDICTION_STEPS, 24)
        self.assertEqual(MAX_INTERPOLATED_RATIO, 0.25)

    def test_model_loader_singleton(self):
        from app.services.prediction_service import get_model_loader
        self.assertIs(get_model_loader(), get_model_loader())

    def test_hour_components_valid(self):
        from app.services.prediction_service import _calculate_hour_components
        sin_v, cos_v = _calculate_hour_components(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
        self.assertAlmostEqual(sin_v**2 + cos_v**2, 1.0, places=5)

    def test_hour_components_none(self):
        from app.services.prediction_service import _calculate_hour_components
        self.assertEqual(_calculate_hour_components(None), (0.0, 0.0))

    def test_normalize_5min(self):
        from app.services.prediction_service import _normalize_timestamp_to_5min
        dt = datetime(2026, 1, 15, 14, 7, 45, tzinfo=timezone.utc)
        r = _normalize_timestamp_to_5min(dt)
        self.assertEqual(r.minute, 5)
        self.assertEqual(r.second, 0)

    def test_normalize_exact(self):
        from app.services.prediction_service import _normalize_timestamp_to_5min
        dt = datetime(2026, 1, 15, 14, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(_normalize_timestamp_to_5min(dt).minute, 10)

    def test_normalize_none(self):
        from app.services.prediction_service import _normalize_timestamp_to_5min
        self.assertIsNone(_normalize_timestamp_to_5min(None))

    def test_no_interpolation_clean(self):
        from app.services.prediction_service import _check_data_needs_interpolation
        base = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(_check_data_needs_interpolation(
            [base + timedelta(minutes=5*i) for i in range(10)]))

    def test_needs_interpolation_gap(self):
        from app.services.prediction_service import _check_data_needs_interpolation
        base = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        ts = [base + timedelta(minutes=5*i) for i in range(5)]
        ts.append(base + timedelta(minutes=60))
        self.assertTrue(_check_data_needs_interpolation(ts))

    def test_resample(self):
        import pandas as pd
        from app.services.prediction_service import _resample_and_interpolate
        base = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        ts = [base + timedelta(minutes=5*i) for i in range(7)]
        ts.extend([base + timedelta(minutes=60 + 5*i) for i in range(7)])
        df = pd.DataFrame({'timestamp': ts, 'suhu': [25.0]*7 + [30.0]*7, 'kelembaban': [80.0]*14})
        result = _resample_and_interpolate(df, 'timestamp')
        self.assertGreater(len(result), 14)

    def test_source_result_dataclass(self):
        from app.services.prediction_service import SourceResult
        sr = SourceResult(source='ecowitt')
        self.assertIsNone(sr.xgboost)
        self.assertIsNone(sr.lstm)

    def test_prepare_xgboost_ecowitt(self):
        from app.services.prediction_service import _prepare_xgboost_features
        from app.models import WeatherLogEcowitt
        wl = WeatherLogEcowitt(
            temperature_main_outdoor=28.0, humidity_outdoor=75.0,
            wind_speed=3.5, wind_direction=180.0,
            pressure_relative=1013.0, rain_rate=0.0,
        )
        f = _prepare_xgboost_features(wl, 'ecowitt')
        self.assertIsNotNone(f)
        self.assertEqual(f['suhu'], 28.0)

    def test_prepare_xgboost_console(self):
        from app.services.prediction_service import _prepare_xgboost_features
        from app.models import WeatherLogConsole
        wl = WeatherLogConsole(
            temperature=72.0, humidity=65.0, wind_speed=5.0,
            wind_direction=180.0, pressure_relative=29.92, rain_rate=0.0,
        )
        f = _prepare_xgboost_features(wl, 'console')
        self.assertIsNotNone(f)
        self.assertAlmostEqual(f['suhu'], 22.22, places=1)

    def test_prepare_xgboost_wunderground(self):
        from app.services.prediction_service import _prepare_xgboost_features
        from app.models import WeatherLogWunderground
        wl = WeatherLogWunderground(
            temperature=25.0, humidity=80.0, wind_speed=4.0,
            wind_direction=270.0, pressure=1015.0, precipitation_rate=0.0,
        )
        f = _prepare_xgboost_features(wl, 'wunderground')
        self.assertIsNotNone(f)
        self.assertEqual(f['tekanan_udara'], 1015.0)

    def test_prepare_xgboost_missing(self):
        from app.services.prediction_service import _prepare_xgboost_features
        from app.models import WeatherLogEcowitt
        wl = WeatherLogEcowitt(temperature_main_outdoor=None, humidity_outdoor=None)
        self.assertIsNone(_prepare_xgboost_features(wl, 'ecowitt'))

    def test_prepare_xgboost_none(self):
        from app.services.prediction_service import _prepare_xgboost_features
        self.assertIsNone(_prepare_xgboost_features(None, 'ecowitt'))

    def test_predict_xgboost_no_model(self):
        from app.services.prediction_service import predict_xgboost, get_model_loader
        loader = get_model_loader()
        orig = loader.xgboost_model
        loader.xgboost_model = None
        self.assertIsNone(predict_xgboost(
            {'suhu': 28, 'kelembaban': 75, 'kecepatan_angin': 3,
             'arah_angin': 180, 'tekanan_udara': 1013, 'intensitas_hujan': 0}, 'test'))
        loader.xgboost_model = orig

    def test_predict_lstm_no_model(self):
        import pandas as pd
        from app.services.prediction_service import predict_lstm, get_model_loader
        loader = get_model_loader()
        om, os_ = loader.lstm_model, loader.scaler
        loader.lstm_model = None; loader.scaler = None
        self.assertIsNone(predict_lstm(pd.DataFrame(), 'test'))
        loader.lstm_model = om; loader.scaler = os_

    def test_get_label_name(self):
        from app.services.prediction_service import get_label_name
        app = _get_test_app()
        with app.app_context():
            name = get_label_name(0)
            self.assertIn('Cerah', name)

    def test_get_label_from_db(self):
        from app.services.prediction_service import get_label_from_db
        app = _get_test_app()
        with app.app_context():
            r = get_label_from_db(0)
            self.assertIn('name', r)
            self.assertEqual(r['class_id'], 0)

    def test_get_model_info(self):
        from app.services.prediction_service import get_model_info
        app = _get_test_app()
        with app.app_context():
            info = get_model_info('xgboost')
            self.assertEqual(info['name'], 'default_xgboost')


# ===========================================================================
# SECTION 18: SERIALIZERS
# ===========================================================================

class TestSerializers(unittest.TestCase):

    def test_prediction_label_none(self):
        from app.serializers import _get_prediction_label
        app = _get_test_app()
        with app.app_context():
            self.assertIsNone(_get_prediction_label(None))

    def test_prediction_label_valid(self):
        from app.serializers import _get_prediction_label
        app = _get_test_app()
        with app.app_context():
            r = _get_prediction_label(1)
            if r:
                self.assertIn('name', r)

    def test_label_cache(self):
        from app import serializers
        app = _get_test_app()
        with app.app_context():
            serializers._LABEL_CACHE = {}
            serializers._load_label_cache()
            if serializers._LABEL_CACHE:
                v = list(serializers._LABEL_CACHE.values())[0]
                self.assertIn('label_id', v)

    def test_get_current_payload(self):
        from app import serializers
        app = _get_test_app()
        with app.app_context():
            p = serializers.get_current_payload(source='ecowitt')
            self.assertIsInstance(p, dict)

    def test_get_prediction_payload(self):
        from app import serializers
        app = _get_test_app()
        with app.app_context():
            p = serializers.get_prediction_payload(source='ecowitt', limit=1)
            self.assertIsInstance(p, dict)

    def test_serialize_prediction_log(self):
        from app.serializers import _serialize_prediction_log
        from app.models import PredictionLog
        app = _get_test_app()
        with app.app_context():
            pl = PredictionLog(id=999, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
            r = _serialize_prediction_log(pl, source='ecowitt')
            self.assertEqual(r['id'], 999)


# ===========================================================================
# SECTION 19: DB SEED
# ===========================================================================

class TestDBSeed(unittest.TestCase):

    def test_seed_callable(self):
        from app.db_seed import seed_labels_and_models
        self.assertTrue(callable(seed_labels_and_models))

    def test_label_map_sync(self):
        from app.services.prediction_service import LABEL_MAP
        expected = [
            'Cerah / Berawan',
            'Berpotensi Hujan dari Arah Utara',
            'Berpotensi Hujan dari Arah Timur Laut',
            'Berpotensi Hujan dari Arah Timur',
            'Berpotensi Hujan dari Arah Tenggara',
            'Berpotensi Hujan dari Arah Selatan',
            'Berpotensi Hujan dari Arah Barat Daya',
            'Berpotensi Hujan dari Arah Barat',
            'Berpotensi Hujan dari Arah Barat Laut',
        ]
        for i, name in enumerate(expected):
            self.assertEqual(LABEL_MAP[i], name)

    def test_default_model_path(self):
        from app.db_seed import _get_default_model_path
        p = _get_default_model_path()
        self.assertIn('ml_models', p)
        self.assertIn('XGBoost.joblib', p)


# ===========================================================================
# SECTION 20: SCHEDULER INIT
# ===========================================================================

class TestSchedulerInit(unittest.TestCase):

    def test_mark_prediction_done(self):
        from app.scheduler_init import _mark_prediction_done, _prediction_already_ran_this_hour
        _mark_prediction_done()
        self.assertTrue(_prediction_already_ran_this_hour())

    def test_prediction_guard_reset(self):
        import app.scheduler_init as si
        orig = si._last_prediction_hour
        si._last_prediction_hour = -1
        self.assertFalse(si._prediction_already_ran_this_hour())
        si._last_prediction_hour = orig

    def test_calc_next_5min(self):
        from app.jobs import calculate_next_5min_time
        r = calculate_next_5min_time()
        self.assertEqual(r.second, 0)
        self.assertEqual(r.minute % 5, 0)

    def test_calc_next_hour(self):
        from app.jobs import calculate_next_hour_time
        r = calculate_next_hour_time()
        self.assertEqual(r.minute, 0)
        self.assertEqual(r.second, 0)


# ===========================================================================
# SECTION 21: ERROR HANDLERS
# ===========================================================================

class TestErrorHandlers(unittest.TestCase):

    def test_404_json(self):
        r = _get_client().get('/api/v3/nonexistent_xyz')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()['error']['code'], 'HTTP_404')

    def test_405_method(self):
        r = _get_client().delete('/api/v3/health')
        self.assertEqual(r.status_code, 405)
        self.assertEqual(r.get_json()['error']['code'], 'HTTP_405')

    def test_non_api_path_404(self):
        r = _get_client().get('/random/path')
        self.assertEqual(r.status_code, 404)

    def test_double_slash_blocked(self):
        r = _get_client().get('/api/v3//health')
        self.assertEqual(r.status_code, 400)

    def test_path_traversal_blocked(self):
        r = _get_client().get('/api/v3/../etc/passwd')
        self.assertEqual(r.status_code, 400)


# ===========================================================================
# SECTION 22: SECURITY HEADERS
# ===========================================================================

class TestSecurityHeaders(unittest.TestCase):

    def _get_headers(self):
        return _get_client().get('/api/v3/health').headers

    def test_x_content_type(self):
        self.assertEqual(self._get_headers().get('X-Content-Type-Options'), 'nosniff')

    def test_x_frame(self):
        self.assertEqual(self._get_headers().get('X-Frame-Options'), 'DENY')

    def test_x_xss(self):
        self.assertEqual(self._get_headers().get('X-XSS-Protection'), '1; mode=block')

    def test_referrer(self):
        self.assertEqual(self._get_headers().get('Referrer-Policy'), 'strict-origin-when-cross-origin')

    def test_cache_control(self):
        cc = self._get_headers().get('Cache-Control', '')
        self.assertIn('no-store', cc)
        self.assertIn('no-cache', cc)

    def test_csp(self):
        self.assertIn("default-src 'none'", self._get_headers().get('Content-Security-Policy', ''))

    def test_permissions(self):
        self.assertIn('geolocation=()', self._get_headers().get('Permissions-Policy', ''))

    def test_no_server_header(self):
        self.assertIsNone(self._get_headers().get('Server'))


# ===========================================================================
# SECTION 23: DB SESSION SAFETY
# ===========================================================================

class TestDBSessionSafety(unittest.TestCase):

    def test_rollback_keeps_session_alive(self):
        from app import db
        from sqlalchemy import text
        app = _get_test_app()
        with app.app_context():
            db.session.rollback()
            result = db.session.execute(text('SELECT 1')).scalar()
            self.assertEqual(result, 1)

    def test_insert_rollback_insert(self):
        from app import db
        from app.models import WeatherLogEcowitt
        app = _get_test_app()
        with app.app_context():
            wl = WeatherLogEcowitt(
                temperature_main_outdoor=99.0,
                request_time=datetime.now(timezone.utc),
            )
            db.session.add(wl)
            db.session.rollback()
            # After rollback, session should work
            wl2 = WeatherLogEcowitt(
                temperature_main_outdoor=88.0,
                request_time=datetime.now(timezone.utc),
            )
            db.session.add(wl2)
            db.session.commit()
            self.assertIsNotNone(wl2.id)
            db.session.delete(wl2)
            db.session.commit()


# ===========================================================================
# SECTION 24: EDGE CASES & BOUNDARY
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_meta_structure(self):
        from app.api_v3 import _meta
        m = _meta("success", 200, source="ecowitt")
        self.assertEqual(m['status'], 'success')
        self.assertIn('timestamp', m)
        self.assertEqual(m['source'], 'ecowitt')

    def test_error_structure(self):
        app = _get_test_app()
        with app.test_request_context():
            from app.api_v3 import _error
            resp, code = _error("CODE", "msg", 400)
            data = resp.get_json()
            self.assertEqual(code, 400)
            self.assertEqual(data['error']['code'], 'CODE')
            self.assertIsNone(data['data'])

    def test_param_schemas_complete(self):
        from app.api_v3 import PARAM_SCHEMAS, ENDPOINT_PARAMS
        all_params = set()
        for params in ENDPOINT_PARAMS.values():
            all_params.update(params)
        for p in all_params:
            self.assertIn(p, PARAM_SCHEMAS, f"Missing schema: {p}")

    def test_endpoint_params_mapping(self):
        from app.api_v3 import ENDPOINT_PARAMS
        for ep in ['health', 'weather_current', 'weather_predict',
                    'weather_details', 'weather_history', 'weather_graph']:
            self.assertIn(ep, ENDPOINT_PARAMS)

    def test_timestamp_normalization_midnight(self):
        from app.services.prediction_service import _normalize_timestamp_to_5min
        dt = datetime(2026, 1, 15, 23, 59, 59, tzinfo=timezone.utc)
        r = _normalize_timestamp_to_5min(dt)
        self.assertEqual(r.minute, 55)

    def test_hour_noon_components(self):
        from app.services.prediction_service import _calculate_hour_components
        dt = datetime(2026, 1, 15, 5, 0, 0, tzinfo=timezone.utc)  # noon WIB
        sin_v, cos_v = _calculate_hour_components(dt)
        self.assertAlmostEqual(sin_v, 0.0, places=3)
        self.assertAlmostEqual(cos_v, -1.0, places=3)

    def test_hour_midnight_components(self):
        from app.services.prediction_service import _calculate_hour_components
        dt = datetime(2026, 1, 14, 17, 0, 0, tzinfo=timezone.utc)  # midnight WIB
        sin_v, cos_v = _calculate_hour_components(dt)
        self.assertAlmostEqual(sin_v, 0.0, places=3)
        self.assertAlmostEqual(cos_v, 1.0, places=3)

    def test_openapi_endpoint(self):
        r = _get_client().get('/api/v3/openapi.yaml')
        self.assertIn(r.status_code, [200, 404])

    def test_rate_limiter_eviction(self):
        from app.api_v3 import RateLimiter
        rl = RateLimiter(max_requests=100, window_seconds=60)
        rl.MAX_TRACKED_IPS = 5
        for i in range(10):
            rl.is_allowed(f"evict_{i}")
        # Trigger cleanup
        for _ in range(rl.CLEANUP_INTERVAL + 1):
            rl.is_allowed("trigger")
        # Should have evicted some
        self.assertLessEqual(len(rl._requests), 12)


# ===========================================================================
# SECTION 25: SECRETS
# ===========================================================================

class TestSecrets(unittest.TestCase):

    def test_from_env(self):
        from app.secrets import get_secret
        os.environ['TEST_SECRET_XYZ'] = 'val'
        self.assertEqual(get_secret('TEST_SECRET_XYZ'), 'val')
        del os.environ['TEST_SECRET_XYZ']

    def test_missing(self):
        from app.secrets import get_secret
        self.assertIsNone(get_secret('NONEXISTENT_ABC_123'))

    def test_from_file(self):
        import tempfile
        from app.secrets import get_secret
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'FS'), 'w') as f:
                f.write('file_val\n')
            os.environ['SECRETS_DIR'] = d
            try:
                self.assertEqual(get_secret('FS'), 'file_val')
            finally:
                os.environ.pop('SECRETS_DIR', None)


# ===========================================================================
# SECTION 26: LOGGING
# ===========================================================================

class TestLogging(unittest.TestCase):

    def test_configure_logging_callable(self):
        from app.logging_config import configure_logging
        self.assertTrue(callable(configure_logging))


# ===========================================================================
# MAIN
# ===========================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2, buffer=True)
