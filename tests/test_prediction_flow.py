"""
Test Prediction Flow
====================
Script test untuk mensimulasikan jalannya satu siklus prediksi
dan memvalidasi data tersimpan di DB dengan format JSON yang valid.

Jalankan dengan: python -m tests.test_prediction_flow
Atau: pytest tests/test_prediction_flow.py -v -s
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set environment variable untuk testing
os.environ['DISABLE_SCHEDULER_FOR_TESTS'] = '1'
os.environ['TESTING'] = '1'


def print_header(title: str):
    """Print formatted header."""
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def print_section(title: str):
    """Print formatted section."""
    print("\n" + "-" * 50)
    print(f" {title}")
    print("-" * 50)


def test_model_structure():
    """Test 1: Verifikasi struktur tabel PredictionLog memiliki 10 kolom."""
    print_header("TEST 1: Verifikasi Struktur Model PredictionLog")
    
    from app.models import PredictionLog
    from sqlalchemy import inspect
    
    # Dapatkan semua kolom dari model
    mapper = inspect(PredictionLog)
    columns = [c.key for c in mapper.columns]
    
    expected_columns = [
        'id',
        'weather_log_wunderground_id',
        'weather_log_ecowitt_id',
        'xgboost_model_id',
        'lstm_model_id',
        'ecowitt_predict_result',
        'wunderground_predict_result',
        'ecowitt_predict_data',
        'wunderground_predict_data',
        'created_at',
    ]
    
    print(f"\nKolom yang ditemukan ({len(columns)}):")
    for col in columns:
        status = "✓" if col in expected_columns else "?"
        print(f"  {status} {col}")
    
    print(f"\nKolom yang diharapkan ({len(expected_columns)}):")
    for col in expected_columns:
        status = "✓" if col in columns else "✗"
        print(f"  {status} {col}")
    
    # Validasi
    missing = set(expected_columns) - set(columns)
    extra = set(columns) - set(expected_columns)
    
    if missing:
        print(f"\n⚠ Kolom yang hilang: {missing}")
    if extra:
        print(f"\n⚠ Kolom tambahan: {extra}")
    
    assert len(columns) == 10, f"Expected 10 columns, got {len(columns)}"
    assert not missing, f"Missing columns: {missing}"
    
    print("\n✓ TEST 1 PASSED: Model PredictionLog memiliki tepat 10 kolom")
    return True


def test_singleton_model_loading():
    """Test 2: Verifikasi singleton model loading."""
    print_header("TEST 2: Verifikasi Singleton Model Loading")
    
    from app.services.prediction_service import get_model_loader, initialize_models
    
    # Initialize models
    print("\nMenginisialisasi models...")
    initialize_models()
    
    # Get loader instances
    loader1 = get_model_loader()
    loader2 = get_model_loader()
    
    print(f"\nLoader 1 ID: {id(loader1)}")
    print(f"Loader 2 ID: {id(loader2)}")
    print(f"Same instance: {loader1 is loader2}")
    
    # Check status
    print(f"\nModel Status:")
    print(f"  - XGBoost loaded: {loader1.xgboost_model is not None}")
    print(f"  - LSTM loaded: {loader1.lstm_model is not None}")
    print(f"  - Scaler loaded: {loader1.scaler is not None}")
    
    assert loader1 is loader2, "ModelLoader should be singleton"
    
    print("\n✓ TEST 2 PASSED: Singleton model loading berfungsi dengan benar")
    return True


def test_interpolation_logic():
    """Test 3: Verifikasi logika interpolasi."""
    print_header("TEST 3: Verifikasi Logika Interpolasi")
    
    from app.services.prediction_service import (
        _check_data_needs_interpolation,
        _resample_and_interpolate
    )
    import pandas as pd
    
    # Test case 1: Data sudah rapi (tidak perlu interpolasi)
    print_section("Case 1: Data sudah rapi (interval 5 menit)")
    now = datetime.now(timezone.utc)
    timestamps_clean = [now - timedelta(minutes=5*i) for i in range(10, 0, -1)]
    needs_interp = _check_data_needs_interpolation(timestamps_clean)
    print(f"  Needs interpolation: {needs_interp}")
    assert not needs_interp, "Clean data should not need interpolation"
    
    # Test case 2: Data dengan gap (perlu interpolasi)
    print_section("Case 2: Data dengan gap")
    timestamps_gap = [
        now - timedelta(minutes=50),
        now - timedelta(minutes=45),
        now - timedelta(minutes=40),
        # Gap di sini (seharusnya menit ke-35)
        now - timedelta(minutes=25),
        now - timedelta(minutes=20),
    ]
    needs_interp = _check_data_needs_interpolation(timestamps_gap)
    print(f"  Needs interpolation: {needs_interp}")
    assert needs_interp, "Data with gaps should need interpolation"
    
    # Test case 3: Resample dan interpolasi
    print_section("Case 3: Test resampling function")
    df_test = pd.DataFrame({
        'timestamp': [
            now - timedelta(minutes=15),
            now - timedelta(minutes=10),
            # Gap
            now,
        ],
        'value': [10.0, 20.0, 40.0]
    })
    print(f"  Before: {len(df_test)} rows")
    df_resampled = _resample_and_interpolate(df_test, 'timestamp')
    print(f"  After: {len(df_resampled)} rows")
    print(f"  Values: {df_resampled['value'].tolist()}")
    
    print("\n✓ TEST 3 PASSED: Logika interpolasi berfungsi dengan benar")
    return True


def test_prediction_pipeline():
    """Test 4: Simulasi satu siklus prediksi penuh."""
    print_header("TEST 4: Simulasi Siklus Prediksi Penuh")
    
    from app import create_app, db
    from app.services.prediction_service import run_prediction_pipeline, initialize_models
    from app.models import PredictionLog
    
    app = create_app()
    
    with app.app_context():
        # Initialize models
        print("\n1. Menginisialisasi models...")
        initialize_models()
        
        # Check if we have enough data
        from app.models import WeatherLogEcowitt, WeatherLogWunderground
        
        eco_count = db.session.query(WeatherLogEcowitt).count()
        wu_count = db.session.query(WeatherLogWunderground).count()
        
        print(f"\n2. Data tersedia di database:")
        print(f"   - Ecowitt records: {eco_count}")
        print(f"   - Wunderground records: {wu_count}")
        
        if eco_count < 144 and wu_count < 144:
            print("\n⚠ WARNING: Tidak cukup data untuk LSTM (minimal 144 records)")
            print("   Test akan dilanjutkan tapi LSTM mungkin return None")
        
        # Run prediction pipeline
        print("\n3. Menjalankan prediction pipeline...")
        result = run_prediction_pipeline()
        
        if result:
            print(f"\n4. Hasil PredictionLog:")
            print(f"   - ID: {result.id}")
            print(f"   - Created at: {result.created_at}")
            print(f"   - Ecowitt Weather ID: {result.weather_log_ecowitt_id}")
            print(f"   - Wunderground Weather ID: {result.weather_log_wunderground_id}")
            print(f"   - XGBoost Model ID: {result.xgboost_model_id}")
            print(f"   - LSTM Model ID: {result.lstm_model_id}")
            print(f"   - Ecowitt XGBoost Result: {result.ecowitt_predict_result}")
            print(f"   - Wunderground XGBoost Result: {result.wunderground_predict_result}")
            
            # Validate JSON data
            print("\n5. Validasi JSON data:")
            
            if result.ecowitt_predict_data:
                eco_json = result.ecowitt_predict_data
                print(f"   - Ecowitt LSTM data: {len(eco_json)} values")
                print(f"   - First 5 values: {eco_json[:5]}")
                assert isinstance(eco_json, list), "ecowitt_predict_data should be a list"
                assert len(eco_json) == 24, f"Expected 24 values, got {len(eco_json)}"
            else:
                print("   - Ecowitt LSTM data: None (mungkin tidak cukup data)")
            
            if result.wunderground_predict_data:
                wu_json = result.wunderground_predict_data
                print(f"   - Wunderground LSTM data: {len(wu_json)} values")
                print(f"   - First 5 values: {wu_json[:5]}")
                assert isinstance(wu_json, list), "wunderground_predict_data should be a list"
                assert len(wu_json) == 24, f"Expected 24 values, got {len(wu_json)}"
            else:
                print("   - Wunderground LSTM data: None (mungkin tidak cukup data)")
            
            # Verify record is in database
            print("\n6. Verifikasi record di database:")
            db_record = db.session.query(PredictionLog).filter_by(id=result.id).first()
            assert db_record is not None, "Record should exist in database"
            print(f"   - Record found: ID {db_record.id}")
            print(f"   - to_dict() output:")
            print(f"     {json.dumps(db_record.to_dict(), indent=6, default=str)}")
            
            print("\n✓ TEST 4 PASSED: Siklus prediksi berjalan dengan benar")
            return True
        else:
            print("\n⚠ Pipeline tidak menghasilkan data")
            print("   Ini bisa terjadi jika tidak ada data cuaca di database")
            return False


def test_api_endpoint():
    """Test 5: Verifikasi API endpoint."""
    print_header("TEST 5: Verifikasi API Endpoint")
    
    from app import create_app
    
    app = create_app()
    
    with app.test_client() as client:
        # Test 1: LSTM endpoint (default)
        print_section("Test /api/data?type=hourly (default: lstm)")
        resp = client.get('/api/data?type=hourly')
        print(f"  Status: {resp.status_code}")
        data = resp.get_json()
        print(f"  Response: {json.dumps(data, indent=4)[:500]}...")
        
        # Test 2: LSTM endpoint explicit - verify model info from database
        print_section("Test /api/data?type=hourly&model=lstm")
        resp = client.get('/api/data?type=hourly&model=lstm')
        print(f"  Status: {resp.status_code}")
        data = resp.get_json()
        if data.get('ok'):
            # Verify model info is from database
            model_info = data.get('model', {})
            prediction_info = data.get('prediction', {})
            print(f"  Model Info from DB:")
            print(f"    - ID: {model_info.get('id')}")
            print(f"    - Name: {model_info.get('name')}")
            print(f"    - Range: {model_info.get('range_prediction')}")
            print(f"  Prediction Info:")
            print(f"    - ID: {prediction_info.get('id')}")
            print(f"    - Source: {prediction_info.get('source')}")
            print(f"    - Predicted At: {prediction_info.get('predicted_at')}")
            print(f"    - Total Hours: {prediction_info.get('total_hours')}")
            print(f"    - Showing: {prediction_info.get('showing')}")
            print(f"    - Limit Applied: {prediction_info.get('limit_applied')}")
            assert model_info.get('id') is not None, "Model ID should be from database"
            assert model_info.get('name') is not None, "Model name should be from database"
            assert model_info.get('range_prediction') == 1440, "LSTM range should be 1440"
            assert prediction_info.get('total_hours') == 24, "Total hours should be 24"
            assert prediction_info.get('showing') == 24, "Showing should be 24 without limit"
            print(f"  Data count: {len(data.get('data', []))}")
        else:
            print(f"  Response: {data}")
        
        # Test 2b: LSTM endpoint with limit
        print_section("Test /api/data?type=hourly&model=lstm&limit=5")
        resp = client.get('/api/data?type=hourly&model=lstm&limit=5')
        print(f"  Status: {resp.status_code}")
        data = resp.get_json()
        if data.get('ok'):
            prediction_info = data.get('prediction', {})
            print(f"  Limit Applied: {prediction_info.get('limit_applied')}")
            print(f"  Showing: {prediction_info.get('showing')}")
            print(f"  Data count: {len(data.get('data', []))}")
            assert prediction_info.get('limit_applied') == 5, "Limit should be 5"
            assert prediction_info.get('showing') == 5, "Showing should be 5"
            assert len(data.get('data', [])) == 5, "Data should have 5 items"
        else:
            print(f"  Response: {data}")
        
        # Test 3: XGBoost endpoint - verify label from database
        print_section("Test /api/data?type=hourly&model=xgboost")
        resp = client.get('/api/data?type=hourly&model=xgboost')
        print(f"  Status: {resp.status_code}")
        data = resp.get_json()
        if data.get('ok'):
            result = data.get('data', {})
            model_info = result.get('model', {})
            label_info = result.get('label', {})
            print(f"  Model Info from DB:")
            print(f"    - Type: {model_info.get('type')}")
            print(f"    - ID: {model_info.get('id')}")
            print(f"    - Name: {model_info.get('name')}")
            print(f"    - Range: {model_info.get('range_prediction')}")
            print(f"  Label Info from DB:")
            print(f"    - Label ID: {label_info.get('label_id')}")
            print(f"    - Class ID: {label_info.get('class_id')}")
            print(f"    - Name: {label_info.get('name')}")
            assert model_info.get('id') is not None, "Model ID should be from database"
            assert label_info.get('label_id') is not None, "Label ID should be from database"
            assert label_info.get('name') is not None, "Label name should be from database"
        else:
            print(f"  Response: {data}")
        
        # Test 4: Invalid model
        print_section("Test /api/data?type=hourly&model=invalid")
        resp = client.get('/api/data?type=hourly&model=invalid')
        print(f"  Status: {resp.status_code}")
        data = resp.get_json()
        print(f"  Response: {data}")
        assert resp.status_code == 400, "Invalid model should return 400"
    
    print("\n✓ TEST 5 PASSED: API endpoints berfungsi dengan benar")
    return True


def run_all_tests():
    """Run all tests."""
    print_header("PREDICTION FLOW TEST SUITE")
    print(f"Tanggal: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    try:
        # Test 1: Model structure
        results['model_structure'] = test_model_structure()
    except Exception as e:
        print(f"\n✗ TEST 1 FAILED: {e}")
        results['model_structure'] = False
    
    try:
        # Test 2: Singleton model loading
        results['singleton_loading'] = test_singleton_model_loading()
    except Exception as e:
        print(f"\n✗ TEST 2 FAILED: {e}")
        results['singleton_loading'] = False
    
    try:
        # Test 3: Interpolation logic
        results['interpolation'] = test_interpolation_logic()
    except Exception as e:
        print(f"\n✗ TEST 3 FAILED: {e}")
        results['interpolation'] = False
    
    try:
        # Test 4: Prediction pipeline
        results['prediction_pipeline'] = test_prediction_pipeline()
    except Exception as e:
        print(f"\n✗ TEST 4 FAILED: {e}")
        import traceback
        traceback.print_exc()
        results['prediction_pipeline'] = False
    
    try:
        # Test 5: API endpoint
        results['api_endpoint'] = test_api_endpoint()
    except Exception as e:
        print(f"\n✗ TEST 5 FAILED: {e}")
        import traceback
        traceback.print_exc()
        results['api_endpoint'] = False
    
    # Summary
    print_header("TEST SUMMARY")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"  {status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print("\n⚠ SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    exit_code = run_all_tests()
    sys.exit(exit_code)
