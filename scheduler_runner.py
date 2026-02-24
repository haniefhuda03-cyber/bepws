"""
Standalone Scheduler Runner
===========================
Script ini digunakan untuk menjalankan APScheduler secara terpisah dari Web Server (Gunicorn).
Diperlukan saat deploy ke production agar scheduler tidak dijalankan ganda oleh multiple worker Gunicorn.

Cara pakai:
python scheduler_runner.py
"""

import time
import logging
import sys
from app import create_app

# Setup logging ke stdout agar tertangkap oleh Systemd/Docker logs
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Import fungsi startup dari run.py
# Pastikan run.py tidak menjalankan app.run() saat diimport
try:
    from run import _start_scheduler_and_jobs
except ImportError:
    logging.error("Gagal mengimport _start_scheduler_and_jobs dari run.py")
    sys.exit(1)

app = create_app()

if __name__ == '__main__':
    logging.info("Memulai Standalone Scheduler Service...")
    
    with app.app_context():
        try:
            # Jalankan logika inisialisasi yang sama dengan run.py
            _start_scheduler_and_jobs()
            
            logging.info("Scheduler berjalan di background process terpisah.")
            
            # Keep main thread alive
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logging.info("Scheduler service dihentikan oleh user.")
        except Exception as e:
            logging.exception(f"Scheduler service crash: {e}")
            sys.exit(1)
