"""
TUWS Backend - Main Entry Point
=================================

Aplikasi ini menjalankan:
1. Flask RESTful API (v1/v2 legacy dan v3)
2. Scheduler untuk fetch data cuaca (setiap 5 menit)
3. Scheduler untuk prediksi (setiap jam pas)
4. Endpoint untuk menerima data dari Console Station (POST)

Urutan startup:
1. Load environment variables
2. Create Flask app
3. Initialize ML models (XGBoost, LSTM, Scaler)
4. Start scheduler dengan jobs
5. Run Flask server
"""

from app import create_app, scheduler
import os
import logging
from datetime import datetime, timezone, timedelta

app = create_app()


if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() in ('1', 'true', 'yes')
    host = os.environ.get('FLASK_HOST', '0.0.0.0')  # Default listen semua interface
    port = int(os.environ.get('FLASK_PORT', '5000'))

    disable_scheduler = os.environ.get('DISABLE_SCHEDULER_FOR_TESTS', '').lower() in ('1', 'true', 'yes')
    
    if not disable_scheduler:
        # Hindari double-start saat debug mode dengan reloader
        if (not debug) or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            # Initialize Cache/ML Models first (from old logic, but models are lazy loaded or inside init_scheduler?)
            # Wait, run.py had custom logic for cache/models.
            # We should preserve that or move it?
            # Existing _start_scheduler_and_jobs had Steps 1-4.
            # Step 1 (Cache) & Step 2 (Models) are good to have on startup.
            # Step 3 (Scheduler) -> init_scheduler
            # Step 4 (Fetch) -> init_scheduler(initial_fetch=True)
            
            # Let's import the extraction function if we want to clean up run.py completely, 
            # OR just keep Cache/ML logic here and delegate Scheduler to init_scheduler.
            
            # Re-implement startup logic cleanly here:
            logging.info("="*60)
            logging.info("[STARTUP] Memulai TUWS Backend")
            logging.info("="*60)

            # 1. Cache
            try:
                from app.services.cache_service import get_cache_service
                cache_svc = get_cache_service()
                logging.info(f"[STARTUP] [OK] Cache service aktif (backend: {cache_svc.backend})")
            except Exception as e:
                logging.warning(f"[STARTUP] [!] Cache service error: {e}")

            # 2. ML Models
            try:
                from app.services.prediction_service import initialize_models
                logging.info("[STARTUP] Memuat model ML...")
                initialize_models()
                logging.info("[STARTUP] [OK] Model ML berhasil dimuat")
            except Exception as e:
                logging.warning(f"[STARTUP] [!] Gagal memuat model ML: {e}")

            # 3. Scheduler (Start — no initial fetch, scheduler handles everything)
            from app.scheduler_init import init_scheduler
            init_scheduler(app, scheduler, start=True)
            
            logging.info("="*60)
            logging.info("[STARTUP] TUWS Backend siap!")
            logging.info("="*60)

    logging.info(f"[SERVER] Flask berjalan di http://{host}:{port}")
    logging.info(f"[SERVER] Console endpoint (/api/v3/console) listen di port {port}")
    logging.info(f"[SERVER] Debug mode: {debug}")
    
    app.run(host=host, port=port, debug=debug, use_reloader=debug)