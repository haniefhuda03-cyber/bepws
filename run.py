from app import create_app, scheduler
from app import jobs
import os
import logging

app = create_app()


def _start_scheduler_and_jobs():
    from datetime import datetime
    try:
        if not scheduler.running:
            scheduler.start()
        if scheduler.get_job('fetch-weather'):
            scheduler.remove_job('fetch-weather')
        scheduler.add_job(
            id='fetch-weather',
            func=jobs.fetch_and_store_weather,
            trigger='interval',
            minutes=5,
            next_run_time=datetime.now()
        )
        logging.info("Scheduler dimulai dan job 'fetch-weather' didaftarkan (interval 5 menit, run segera saat startup).")
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