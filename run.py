from app import create_app, scheduler
import os
import logging

app = create_app()

def _start_scheduler_and_jobs():
    from datetime import datetime
    # Import jobs here to avoid importing ML modules (tf/joblib) at module
    # import time. This prevents ML libraries from being loaded during
    # management commands like `flask db migrate` / `flask db upgrade`.
    from app import jobs
    
    # Inisialisasi model ML saat startup
    try:
        from app.services.prediction_service import initialize_models
        initialize_models()
        logging.info("Model ML berhasil diinisialisasi saat startup.")
    except Exception as e:
        logging.warning(f"Gagal menginisialisasi model ML: {e}")
    
    try:
        if not scheduler.running:
            scheduler.start()
        
        # =====================================================
        # Job 1: Fetch Weather Data (setiap 5 menit)
        # =====================================================
        if scheduler.get_job('fetch-weather'):
            scheduler.remove_job('fetch-weather')
        scheduler.add_job(
            id='fetch-weather',
            func=jobs.fetch_and_store_weather,
            trigger='interval',
            minutes=5,
            next_run_time=datetime.now()
        )
        logging.info("Job 'fetch-weather' didaftarkan (interval 5 menit).")
        
        # =====================================================
        # Job 2: Hourly Prediction (setiap jam, menit ke-00)
        # =====================================================
        if scheduler.get_job('hourly-prediction'):
            scheduler.remove_job('hourly-prediction')
        scheduler.add_job(
            id='hourly-prediction',
            func=jobs.run_hourly_prediction,
            trigger='cron',
            minute=0,  # Berjalan setiap jam di menit ke-00
            next_run_time=datetime.now()  # Jalankan juga saat startup
        )
        logging.info("Job 'hourly-prediction' didaftarkan (setiap jam di menit ke-00).")
        
        logging.info("Scheduler dimulai dengan 2 jobs: fetch-weather (5 min) dan hourly-prediction (setiap jam).")
    except Exception as e:
        logging.warning(f"Gagal memulai scheduler atau menambah job: {e}")

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', '5000'))

    disable_scheduler_for_tests = os.environ.get('DISABLE_SCHEDULER_FOR_TESTS', '').lower() in ('1', 'true', 'yes')
    if not disable_scheduler_for_tests:
        if (not debug) or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            _start_scheduler_and_jobs()

    app.run(host=host, port=port, debug=debug, use_reloader=debug)