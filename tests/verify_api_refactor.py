
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import json
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app import models

class TestAPIRefactor(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        # db.create_all() # Skipped because SQLite doesn't support ARRAY and we mock serializers
        
        # Setup Auth
        os.environ['APPKEY'] = 'test_secret_key_32_chars_longggggg'
        self.headers = {'X-APP-KEY': 'test_secret_key_32_chars_longggggg'}

    def tearDown(self):
        db.session.remove()
        # db.drop_all()
        self.app_context.pop()

    @patch('app.serializers.get_latest_weather_data')
    def test_weather_current_structure(self, mock_get_latest):
        # Setup mock return using a class to control attributes
        class MockWeatherLog:
            id = 1
            created_at = datetime.now(timezone.utc)
            temperature_main_outdoor = 25.5
            humidity_outdoor = 60
            dew_point_outdoor = 20.0
            pressure_relative = 1013.25
            rain_rate = 0.0
            wind_speed = 5.0
            wind_direction = 180
            
        mock_wl = MockWeatherLog()
        mock_get_latest.return_value = mock_wl

        # We actually refactored valid logic into serializers.get_current_payload
        # But wait, serializers.get_current_payload calls get_latest_weather_data internally?
        # Let's check serializers.py content again.
        # It calls `get_latest_weather_data` at line 278 (re-read from context).
        
        # So mocking get_latest_weather_data in serializers should work if we patch it there.
        with patch('app.serializers.get_latest_weather_data', return_value=mock_wl):
             resp = self.client.get('/api/v3/weather/current?source=ecowitt', headers=self.headers)
             
             self.assertEqual(resp.status_code, 200)
             data = resp.get_json()
             self.assertTrue(data['meta']['status'], 'success')
             self.assertEqual(data['data']['temp'], 25.5)
             
    @patch('app.serializers.get_prediction_payload')
    def test_weather_predict_structure(self, mock_get_pred):
        # Mock what get_prediction_payload returns (list of dicts)
        mock_get_pred.return_value = {
            "ok": True,
            "data": [{
                "id": 100,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ecowitt_prediction": {"name": "Hujan Ringan"},
                "ecowitt_lstm_data": [0.1, 0.2, 0.3]
            }]
        }
        
        # Test XGBoost
        resp = self.client.get('/api/v3/weather/predict?source=ecowitt&model=xgboost', headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['data']['weather_predict'], "Hujan Ringan")
        
        # Test LSTM
        resp = self.client.get('/api/v3/weather/predict?source=ecowitt&model=lstm&limit=3', headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(isinstance(data['data'], list))
        self.assertEqual(len(data['data']), 3)

    @patch('app.serializers.get_history_payload')
    def test_weather_history_structure(self, mock_get_hist):
        mock_get_hist.return_value = {
            "ok": True,
            "source": "ecowitt",
            "total": 10,
            "data": [
                {"id": 1, "temp": 25.0, "time": "2023-01-01T00:00:00+00:00"}
            ]
        }
        
        resp = self.client.get('/api/v3/weather/history?source=ecowitt', headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data['data']), 1)
        self.assertEqual(data['meta']['total'], 10)

if __name__ == '__main__':
    unittest.main()
