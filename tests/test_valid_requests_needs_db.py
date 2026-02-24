
import unittest
import sys
import os
import json

# Add project root to path
sys.path.append(os.getcwd())

from app import create_app

class TestValidRequests(unittest.TestCase):
    def setUp(self):
        # Set dummy APPKEY for testing
        os.environ['APPKEY'] = 'test_secret_key_32_chars_long_exactly_xyz'
        
        # Use dict config
        test_config = {
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_ENGINE_OPTIONS': {} # Clear Postgres options
        }
        self.app = create_app(test_config=test_config)
        self.client = self.app.test_client()
        
        # Initialize DB
        with self.app.app_context():
            from app import db
            db.create_all()
            
        # Set dummy APPKEY for testing
        os.environ['APPKEY'] = 'test_secret_key_32_chars_long_exactly_xyz'
        self.headers = {'X-APP-KEY': 'test_secret_key_32_chars_long_exactly_xyz'}
    
    def _print_error(self, response):
        if response.status_code >= 400:
            print(f"\n[DEBUG] Status: {response.status_code}")
            try:
                print(f"[DEBUG] Data: {json.dumps(response.get_json(), indent=2)}")
            except:
                print(f"[DEBUG] Raw: {response.data}")

    def test_current_weather_valid(self):
        """Test valid current weather request"""
        response = self.client.get('/api/v3/weather/current?source=ecowitt', headers=self.headers)
        self._print_error(response)
        # Should be 200 or 404 (if no data), but NOT 400 (Invalid Parameter) or 500

        self.assertIn(response.status_code, [200, 404])
        if response.status_code == 200:
            data = response.get_json()
            self.assertEqual(data['meta']['status'], 'success')
            self.assertEqual(data['meta']['source'], 'ecowitt')

    def test_details_valid(self):
        """Test valid details request"""
        response = self.client.get('/api/v3/weather/details?source=wunderground', headers=self.headers)
        self.assertIn(response.status_code, [200, 404])

    def test_history_valid_defaults(self):
        """Test history request with defaults"""
        response = self.client.get('/api/v3/weather/history', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['meta']['source'], 'ecowitt') # Default

    def test_predict_valid(self):
        """Test valid predict request"""
        response = self.client.get('/api/v3/weather/predict?model=lstm&limit=12', headers=self.headers)
        self.assertIn(response.status_code, [200, 404])

    def test_graph_valid(self):
        """Test valid graph request"""
        response = self.client.get('/api/v3/weather/graph?range=weekly&datatype=temperature', headers=self.headers)
        self._print_error(response)
        self.assertIn(response.status_code, [200, 404])

if __name__ == '__main__':
    unittest.main()
