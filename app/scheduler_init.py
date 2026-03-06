import logging
import os
from datetime import datetime, timedelta, timezone


# =====================================================================
# PREDICTION DEDUPLICATION GUARD (Redis + DB Fallback)
# =====================================================================
# Layer 1: Redis key "prediction_guard:{UTC_hour}" dengan TTL 3600s
#          → Cepat, survive app restart selama Redis hidup
# Layer 2: Query prediction_log (EXISTS, tanpa SELECT *)
#          → Fallback jika Redis mati, source of truth dari DB
# =====================================================================
_GUARD_KEY_PREFIX = "prediction_guard"
_GUARD_TTL_SECONDS = 3600  # 1 jam


def _get_redis_for_guard():
    """Ambil Redis client langsung (bypass cache.py memory fallback)."""
    try:
        from .cache import _get_redis_client
        return _get_redis_client()
    except Exception:
        return None


def _mark_prediction_done():
    """
    Tandai bahwa prediksi sudah dijalankan pada jam ini.
    Best-effort ke Redis — jika gagal, DB sudah merekam via prediction_log.
    """
    now = datetime.now(timezone.utc)
    key = f"{_GUARD_KEY_PREFIX}:{now.hour}"

    client = _get_redis_for_guard()
    if client:
        try:
            client.setex(key, _GUARD_TTL_SECONDS, "1")
            logging.debug(f"[GUARD] Redis SET {key} (TTL {_GUARD_TTL_SECONDS}s)")
        except Exception as e:
            logging.warning(f"[GUARD] Redis SET gagal (tidak masalah, DB sudah merekam): {e}")


def _prediction_already_ran_this_hour() -> bool:
    """
    Cek apakah prediksi sudah berjalan pada jam UTC saat ini.
    Layer 1: Redis (cepat) → Layer 2: DB prediction_log (fallback).
    """
    now = datetime.now(timezone.utc)
    key = f"{_GUARD_KEY_PREFIX}:{now.hour}"

    # Layer 1: Redis
    client = _get_redis_for_guard()
    if client:
        try:
            if client.exists(key):
                logging.debug(f"[GUARD] Redis HIT: {key}")
                return True
            logging.debug(f"[GUARD] Redis MISS: {key}")
            return False
        except Exception as e:
            logging.warning(f"[GUARD] Redis cek gagal, fallback ke DB: {e}")

    # Layer 2: DB — query ringan (EXISTS, tanpa load kolom)
    try:
        from . import db
        from .models import PredictionLog

        hour_start = now.replace(minute=0, second=0, microsecond=0)
        exists = db.session.query(
            db.session.query(PredictionLog.id)
            .filter(PredictionLog.created_at >= hour_start)
            .exists()
        ).scalar()

        if exists:
            logging.info(f"[GUARD] DB fallback: prediksi DITEMUKAN pada jam {now.hour} UTC")
        else:
            logging.info(f"[GUARD] DB fallback: prediksi BELUM ADA pada jam {now.hour} UTC")
        return exists
    except Exception as e:
        logging.error(f"[GUARD] DB fallback gagal: {e}")
        # Jika Redis + DB gagal → return False (lebih baik jalan daripada skip)
        return False


def init_scheduler(app, scheduler, start=True):
    """
    Inisialisasi jobs untuk scheduler.
    Dipanggil oleh create_app (start=False) atau run.py (start=True).
    
    Arsitektur Job (Enterprise):
    ────────────────────────────
    1. fetch-weather (cron 5 min):
       Mengambil data cuaca dari API eksternal.
       Pada jam pas (menit < 5), fetch OTOMATIS memicu run_hourly_prediction()
       secara sinkron setelah data tersimpan ke database (PRIMARY trigger).
    
    2. hourly-prediction-safety (cron setiap jam, menit ke-8):
       Safety net — hanya berjalan jika event-driven trigger GAGAL
       atau fetch terlambat melewati menit ke-5 pada jam tersebut.
       Menggunakan deduplication guard agar tidak menjalankan prediksi dua kali.
    
    Alasan Arsitektur Dual-Trigger:
    ───────────────────────────────
    - PRIMARY (event-driven): Menjamin data terbaru sudah di DB sebelum prediksi.
    - SAFETY (cron independen): Menjamin prediksi tetap berjalan TIAP JAM
      walaupun fetch gagal, timeout, atau terlambat.
    - Guard: _prediction_already_ran_this_hour() mencegah duplikasi.
    
    Params:
    - start: Jalankan scheduler.start() (Default: True)
    """
    from app import jobs
    from app.jobs import calculate_next_5min_time, calculate_next_hour_time
    
    wib = timezone(timedelta(hours=7))
    
    try:
        # =====================================================
        # Job 1: Fetch Weather Data (Primary, setiap 5 menit)
        # =====================================================
        if scheduler.get_job('fetch-weather'):
            scheduler.remove_job('fetch-weather')
        
        next_fetch = calculate_next_5min_time()
        
        scheduler.add_job(
            id='fetch-weather',
            func=jobs.fetch_and_store_weather,
            trigger='cron',
            minute='0,5,10,15,20,25,30,35,40,45,50,55',
            second=0,
            timezone=timezone.utc,
            next_run_time=next_fetch,
            max_instances=1,   # Cegah overlapping runs
            coalesce=True,     # Jika missed, jalankan hanya sekali
            misfire_grace_time=60, # Tolelir keterlambatan hingga 60 detik
        )
        logging.info(f"[Scheduler] Job 'fetch-weather' registered. Next: {next_fetch.astimezone(wib).strftime('%H:%M:%S')} WIB")
        
        # =====================================================
        # Job 2: Hourly Prediction Safety Net (setiap jam, menit ke-8)
        # =====================================================
        # Menit ke-8 dipilih karena:
        # - Fetch berjalan di menit 0 dan 5
        # - Event-driven trigger terjadi di menit 0-4
        # - Jika sampai menit ke-8 belum ada prediksi → safety net ambil alih
        # =====================================================
        if scheduler.get_job('hourly-prediction-safety'):
            scheduler.remove_job('hourly-prediction-safety')
        
        scheduler.add_job(
            id='hourly-prediction-safety',
            func=_run_prediction_safety,
            trigger='cron',
            minute=8,
            second=0,
            timezone=timezone.utc,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60, # Tolelir keterlambatan hingga 60 detik
        )
        logging.info("[Scheduler] Job 'hourly-prediction-safety' (Backup Prediction) registered at minute 8 every hour (safety net, setiap jam menit ke-8).")
        logging.info(f"[Scheduler] PRIMARY: Prediction dipicu event-driven oleh fetch-weather pada jam pas")
        logging.info(f"[Scheduler] SAFETY:  Jika primary gagal, safety net akan menjalankan prediksi di menit ke-8")
        
        # Bersihkan job lama jika ada (backward compatibility)
        for legacy_id in ['hourly-prediction']:
            if scheduler.get_job(legacy_id):
                scheduler.remove_job(legacy_id)
                logging.info(f"[Scheduler] Removed legacy '{legacy_id}' job")
        
        # Start Scheduler if requested
        if start and not scheduler.running:
            try:
                scheduler.start()
                logging.info("[Scheduler] Scheduler started")
            except Exception as e:
                logging.warning(f"[Scheduler] Scheduler start warning: {e}")
        
    except Exception as e:
        logging.error(f"[Scheduler] Failed to init jobs: {e}")


def _run_prediction_safety():
    """
    Safety net untuk prediksi per jam.
    
    Logika:
    1. Cek apakah prediksi sudah berjalan pada jam ini (via _last_prediction_hour)
    2. Jika sudah → SKIP (event-driven trigger berhasil)
    3. Jika belum → Jalankan prediksi (fetch gagal/terlambat)
    
    Job ini terdaftar di cron menit ke-8 setiap jam.
    """
    from flask import current_app
    from app.jobs import scheduler
    
    appctx = None
    if getattr(scheduler, 'app', None) is not None:
        appctx = scheduler.app.app_context()
    else:
        appctx = current_app.app_context()
    
    with appctx:
        now_utc = datetime.now(timezone.utc)
        wib = now_utc.astimezone(timezone(timedelta(hours=7)))
        
        if _prediction_already_ran_this_hour():
            logging.info(
                f"[SAFETY] Prediksi sudah berjalan pada jam {wib.strftime('%H')} WIB "
                f"(dipicu oleh fetch). SKIP."
            )
            return
        
        logging.warning(
            f"[SAFETY] Prediksi BELUM berjalan pada jam {wib.strftime('%H')} WIB! "
            f"Fetch mungkin gagal/terlambat. Menjalankan prediksi via safety net..."
        )
        
        try:
            from app.services.prediction_service import run_prediction_pipeline, initialize_models
            initialize_models()
            
            from app.jobs import run_hourly_prediction
            run_hourly_prediction()
            _mark_prediction_done()
            logging.info("[SAFETY] Prediksi berhasil via safety net. Dedup guard updated.")
        except Exception as e:
            logging.error(f"[SAFETY] Gagal menjalankan prediksi: {e}")

