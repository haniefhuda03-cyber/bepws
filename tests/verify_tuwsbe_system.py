
import os
import sys
import logging
import threading
from datetime import datetime, timezone
from flask import Flask
from sqlalchemy import text, inspect

# Add app to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import WeatherLogEcowitt, WeatherLogWunderground, WeatherLogConsole, PredictionLog
from app import scheduler

# Configure logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def check_config(app):
    logging.info("=== Checking Configuration ===")
    required_vars = [
        'WUNDERGROUND_URL', 'ECO_APP_KEY', 'ECO_API_KEY', 
        'ECO_MAC', 'DATABASE_URL', 'SECRET_KEY'
    ]
    missing = []
    for var in required_vars:
        if not app.config.get(var) and not os.environ.get(var):
            if var == 'DATABASE_URL' and app.config.get('SQLALCHEMY_DATABASE_URI'):
                continue
            missing.append(var)
    
    if missing:
        logging.warning(f"[MISSING] Missing Config/Env: {', '.join(missing)}")
    else:
        logging.info("[OK] Configuration keys present")
        
    # Check secrets
    try:
        from app.secrets import get_secret
        from app.config import API_READ_KEY
        if not API_READ_KEY:
             logging.warning("[WARN] API_READ_KEY is not set (API protection might be weak)")
        else:
             logging.info("[OK] API_READ_KEY is set")
    except ImportError:
        logging.warning("[WARN] Could not import secrets module")

def check_database(app):
    logging.info("=== Checking Database ===")
    with app.app_context():
        try:
            # Check connection
            db.session.execute(text('SELECT 1'))
            logging.info("[OK] Database connection successful")
            
            # Check tables
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            required_tables = [
                'weather_log_ecowitt', 
                'weather_log_wunderground', 
                'weather_log_console',
                'prediction_log',
                'data_xgboost',
                'data_lstm',
                'xgboost_prediction_result',
                'lstm_prediction_result',
                'models',
                'labels'
            ]
            
            missing_tables = [t for t in required_tables if t not in tables]
            if missing_tables:
                logging.error(f"[ERR] Missing Tables: {', '.join(missing_tables)}")
            else:
                logging.info(f"[OK] All {len(required_tables)} required tables found")
                
            # Check Row Counts
            counts = {
                'Ecowitt': db.session.query(WeatherLogEcowitt).count(),
                'Wunderground': db.session.query(WeatherLogWunderground).count(),
                'Console': db.session.query(WeatherLogConsole).count(),
                'Predictions': db.session.query(PredictionLog).count()
            }
            for k, v in counts.items():
                logging.info(f"   - {k}: {v} rows")
                
        except Exception as e:
            logging.error(f"[ERR] Database Error: {e}")

def check_redis_celery(app):
    logging.info("=== Checking Redis & Celery ===")
    redis_url = app.config.get('REDIS_URL') or os.environ.get('REDIS_URL')
    if not redis_url:
        logging.warning("[WARN] REDIS_URL not set. Celery might not work.")
        return

    try:
        import redis
        r = redis.from_url(redis_url)
        r.ping()
        logging.info("[OK] Redis connection successful")
    except Exception as e:
        logging.error(f"[ERR] Redis Connection Failed: {e}")

def check_scheduler(app):
    logging.info("=== Checking Scheduler ===")
    try:
        # Scheduler is initialized in create_app -> app.register_blueprint -> ...
        # But we need to access the global scheduler object from app
        if scheduler:
            jobs = scheduler.get_jobs()
            logging.info(f"[OK] Scheduler instance found. Jobs: {len(jobs)}")
            if len(jobs) == 0:
                logging.warning("[WARN] No jobs registered in scheduler!")
            for job in jobs:
                logging.info(f"   - Job: {job.id}")
        else:
            logging.warning("[WARN] Scheduler object is None")
    except Exception as e:
        logging.error(f"[ERR] Scheduler Check Error: {e}")

def check_api_endpoints(app):
    logging.info("=== Checking API Endpoints ===")
    client = app.test_client()
    
    # 1. Health
    res = client.get('/api/v3/health')
    if res.status_code == 200:
        logging.info("[OK] GET /api/v3/health: 200 OK")
    else:
        logging.error(f"[ERR] GET /api/v3/health: {res.status_code} - {res.get_json()}")
        
    # 2. History (Auth Required)
    # Mocking Authentication
    api_key = app.config.get('API_READ_KEY') or os.environ.get('API_READ_KEY') or 'secret'
    # Wait, require_auth checks X-APP-KEY vs os.environ.get('APPKEY')
    app_key = os.environ.get('APPKEY')
    
    if not app_key:
        logging.warning("[WARN] APPKEY env var not set, skipping auth tests")
        return

    headers = {'X-APP-KEY': app_key}
    
    # Test History
    res = client.get('/api/v3/weather/history?source=ecowitt&per_page=1', headers=headers)
    if res.status_code == 200:
        logging.info("[OK] GET /api/v3/weather/history: 200 OK")
    else:
        logging.warning(f"[WARN] GET /api/v3/weather/history: {res.status_code} (Might be empty DB or Auth fail)")

    # Test Console (No Auth)
    # We won't POST data to avoid polluting DB, but we can check if it rejects empty data
    res = client.post('/api/v3/weather/console', data={})
    if res.status_code == 400:
        logging.info("[OK] POST /api/v3/weather/console (Empty): 400 OK (Correctly rejected)")
    else:
        logging.error(f"[ERR] POST /api/v3/weather/console: Expected 400, got {res.status_code}")

if __name__ == "__main__":
    print("\n STARTING COMPREHENSIVE TUWSBE SYSTEM AUDIT \n")
    try:
        app = create_app()
        check_config(app)
        check_database(app)
        check_redis_celery(app)
        check_scheduler(app)
        check_api_endpoints(app)
        
        print("\n AUDIT COMPLETED \n")
    except Exception as e:
        logging.critical(f" FATAL ERROR DURING AUDIT: {e}")
        import traceback
        traceback.print_exc()
