"""
Jobs Module - Scheduler Tasks untuk Pengambilan Data Cuaca dan Prediksi
=========================================================================

Fitur:
- Fetch data dari 3 sumber secara PARALEL (Console, Ecowitt, Wunderground)
- Interval 5 menit (toleransi detik saja, menit harus pas: 00, 05, 10, dst)
- Prediksi hanya berjalan setiap jam pas (00:00, 01:00, dst)
- Quality Control otomatis pada semua data
- Urutan prediksi: Console -> Ecowitt -> Wunderground
"""

import requests
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, Dict, Tuple, List
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from flask import current_app

from . import scheduler, db
from .models import (
    WeatherLogWunderground,
    WeatherLogEcowitt,
    WeatherLogConsole,
)
from .secrets import get_secret
from .set_variables import *
from .common.helpers import (
    safe_float,
    safe_int,
)

# =====================================================================
# KONFIGURASI
# =====================================================================

# Ecowitt API (Imported from set_variables)
ECO_BASE = "https://api.ecowitt.net/api/v3"

# Console Station
CONSOLE_ENDPOINT_ENABLED = os.environ.get("CONSOLE_ENDPOINT_ENABLED", "true").lower() in ("1", "true", "yes")

# Timeout settings
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "15"))
PARALLEL_TIMEOUT = int(os.environ.get("PARALLEL_TIMEOUT", "30"))

# Log konfigurasi
def _mask_secret(val: str) -> str:
    """Menyembunyikan sebagian secret untuk logging."""
    if not val:
        return None
    s = str(val)
    if len(s) <= 6:
        return '***'
    return f"{s[:3]}...{s[-3:]}"

if not WUNDERGROUND_URL:
    logging.warning('[Config] WUNDERGROUND_URL belum diset.')

if not all([ECO_APP_KEY, ECO_API_KEY, ECO_MAC]):
    logging.warning('[Config] Kredensial Ecowitt belum lengkap.')


# =====================================================================
# RETRY HELPER
# =====================================================================

def _requests_get_with_retry(url, params=None, timeout=REQUEST_TIMEOUT):
    """GET request dengan retry logic."""
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        reraise=True,
    )
    def _do_get(u, p, t):
        r = requests.get(u, params=p, timeout=t)
        r.raise_for_status()
        return r
    return _do_get(url, params, timeout)


# =====================================================================
# FETCH WUNDERGROUND (GET)
# =====================================================================

def fetch_wunderground() -> Optional[WeatherLogWunderground]:
    """
    Fetch data dari Weather Underground API (GET request).
    Menerapkan Quality Control sebelum menyimpan.
    """
    testing = False
    try:
        testing = bool(current_app.config.get('TESTING', False))
    except Exception:
        testing = False

    if not WUNDERGROUND_URL and not testing:
        logging.debug("[Wunderground] URL belum diset, skip.")
        return None

    try:
        if testing:
            resp = requests.get(WUNDERGROUND_URL, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        else:
            resp = _requests_get_with_retry(WUNDERGROUND_URL, timeout=REQUEST_TIMEOUT)

        # Defensive: Wunderground returns HTTP 204 No Content saat stasiun offline
        if resp.status_code == 204 or not resp.text.strip():
            logging.warning("[Wunderground] Response kosong (HTTP 204 / No Content). Stasiun cuaca mungkin offline.")
            return None

        data = resp.json()
    except RetryError as re:
        logging.error(f"[Wunderground] Gagal setelah retry: {re}")
        return None
    except Exception as e:
        logging.error(f"[Wunderground] Error fetch: {e}")
        return None
    
    if not data or "observations" not in data or not data["observations"]:
        logging.warning("[Wunderground] Response tidak valid atau kosong")
        return None
    
    obs = data["observations"][0]
    metric_si = obs.get("metric_si", {})
    
    # Parse request time
    request_time_str = obs.get("obsTimeUtc")
    try:
        if request_time_str:
            request_time_utc = datetime.fromisoformat(request_time_str.replace("Z", "+00:00"))
        else:
            raise ValueError("Request time tidak tersedia")
    except Exception:
        request_time_utc = datetime.now(timezone.utc)
        logging.warning("[Wunderground] Gagal parse waktu, menggunakan waktu server")

    # Prepare data untuk QC
    raw_data = {
        'solar_radiation': obs.get("solarRadiation"),
        'ultraviolet_radiation': obs.get("uv"),
        'humidity': obs.get("humidity"),
        'temperature': metric_si.get("temp"),
        'pressure': metric_si.get("pressure"),
        'wind_direction': obs.get("winddir"),
        'wind_speed': metric_si.get("windSpeed"),
        'wind_gust': metric_si.get("windGust"),
        'precipitation_rate': metric_si.get("precipRate"),
        'precipitation_total': metric_si.get("precipTotal"),
    }
    
    wl = WeatherLogWunderground(
        solar_radiation=safe_float(raw_data['solar_radiation'], None),
        ultraviolet_radiation=safe_float(raw_data['ultraviolet_radiation'], None),
        humidity=safe_float(raw_data['humidity'], None),
        temperature=safe_float(raw_data['temperature'], None),
        pressure=safe_float(raw_data['pressure'], None),
        wind_direction=safe_float(raw_data['wind_direction'], None),
        wind_speed=safe_float(raw_data['wind_speed'], None),
        wind_gust=safe_float(raw_data['wind_gust'], None),
        precipitation_rate=safe_float(raw_data['precipitation_rate'], None),
        precipitation_total=safe_float(raw_data['precipitation_total'], None),
        request_time=request_time_utc,
    )
    db.session.add(wl)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        logging.info(f"[Wunderground] Duplikat request_time={request_time_utc.isoformat()}, skip.")
        return None
    except Exception as e:
        db.session.rollback()
        logging.error(f"[Wunderground] Commit gagal: {e}")
        return None
    
    status = "[OK]"
    logging.info(f"[Wunderground] {status} Data disimpan (ID: {wl.id})")
    return wl


# =====================================================================
# FETCH ECOWITT (GET)
# =====================================================================

def fetch_ecowitt() -> Optional[WeatherLogEcowitt]:
    """
    Fetch data dari Ecowitt API (GET request).
    Menerapkan Quality Control sebelum menyimpan.
    """
    testing = False
    try:
        testing = bool(current_app.config.get('TESTING', False))
    except Exception:
        testing = False

    if not all([ECO_APP_KEY, ECO_API_KEY, ECO_MAC]) and not testing:
        logging.debug("[Ecowitt] Kredensial belum lengkap, skip.")
        return None

    params = {
        "application_key": ECO_APP_KEY,
        "api_key": ECO_API_KEY,
        "mac": ECO_MAC,
        "call_back": "all",
        "temp_unitid": 1,  # Celsius
        "pressure_unitid": 3,  # hPa
        "wind_speed_unitid": 6,  # m/s (API: 6=m/s, 7=km/h, 9=mph)
        "rainfall_unitid": 12,  # mm
        "solar_irradiance_unitid": 14,  # lux (API: 14=lux, 16=W/m²)
    }
    url = f"{ECO_BASE}/device/real_time"

    try:
        if testing:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        else:
            resp = _requests_get_with_retry(url, params=params, timeout=REQUEST_TIMEOUT)
        response_data = resp.json()
    except RetryError as re:
        logging.error(f"[Ecowitt] Gagal setelah retry: {re}")
        return None
    except Exception as e:
        logging.error(f"[Ecowitt] Error fetch: {e}")
        return None

    # Defensive: response bisa berupa list jika API error
    if not isinstance(response_data, dict):
        logging.warning(f"[Ecowitt] Response bukan dict (type: {type(response_data).__name__}). Stasiun mungkin offline.")
        return None

    if response_data.get("code") != 0 or "data" not in response_data:
        logging.warning(f"[Ecowitt] API error: {response_data.get('msg', 'Tidak ada pesan')}")
        return None

    data = response_data['data']

    # Defensive: data bisa berupa list kosong [] jika stasiun offline
    if not isinstance(data, dict):
        logging.warning(f"[Ecowitt] 'data' bukan dict (type: {type(data).__name__}, value: {data}). Stasiun cuaca mungkin offline atau tidak mengirim data.")
        return None

    # --- BEST PRACTICE: PARSING REQUEST TIME ---
    # 1. Inisialisasi default ke waktu server (UTC)
    # Ini menjamin variabel selalu valid, bahkan jika API tidak mengirim field 'time'.
    request_time_fix = datetime.now(timezone.utc)

    # 2. Ambil nilai timestamp epoch dari root response
    epoch_str = response_data.get('time')
    
    # 3. Coba override default dengan data dari API
    if epoch_str:
        try:
            # Konversi Epoch (integer detik) ke Datetime UTC
            # int(epoch_str) -> Mengubah "1765333867" menjadi integer
            # fromtimestamp -> Mengubah integer menjadi datetime object
            request_time_fix = datetime.fromtimestamp(int(epoch_str), tz=timezone.utc)
        except (ValueError, TypeError) as e:
            # Log error tapi jangan crash, biarkan menggunakan default (waktu server)
            logging.warning(f"Gagal parsing Epoch time Ecowitt '{epoch_str}': {e}. Menggunakan waktu server.")
    # -------------------------------------------

    def _get_value(source: Optional[Dict[str, Any]], key: str) -> Optional[float]:
        if source and key in source and isinstance(source[key], dict):
            val = source[key].get("value")
            try:
                return float(val) if val is not None and val != '' else None
            except (ValueError, TypeError):
                return None
        return None

    outdoor = data.get('outdoor')
    indoor = data.get('indoor')
    solar_uvi = data.get('solar_and_uvi')
    rainfall = data.get('rainfall')
    wind = data.get('wind')
    pressure = data.get('pressure')
    battery = data.get('battery', {}).get('sensor_array')

    # Prepare raw data untuk QC
    raw_data = {
        'vpd_outdoor': _get_value(outdoor, 'vpd'),
        'temperature_main_outdoor': _get_value(outdoor, 'temperature'),
        'temperature_feels_like_outdoor': _get_value(outdoor, 'feels_like'),
        'temperature_apparent_outdoor': _get_value(outdoor, 'app_temp'),
        'dew_point_outdoor': _get_value(outdoor, 'dew_point'),
        'humidity_outdoor': _get_value(outdoor, 'humidity'),
        'temperature_main_indoor': _get_value(indoor, 'temperature'),
        'temperature_feels_like_indoor': _get_value(indoor, 'feels_like'),
        'temperature_apparent_indoor': _get_value(indoor, 'app_tempin'),
        'dew_point_indoor': _get_value(indoor, 'dew_point'),
        'humidity_indoor': _get_value(indoor, 'humidity'),
        'solar_irradiance': _get_value(solar_uvi, 'solar'),
        'uvi': _get_value(solar_uvi, 'uvi'),
        'rain_rate': _get_value(rainfall, 'rain_rate'),
        'rain_daily': _get_value(rainfall, 'daily'),
        'rain_event': _get_value(rainfall, 'event'),
        'rain_hour': _get_value(rainfall, '1_hour'),
        'rain_weekly': _get_value(rainfall, 'weekly'),
        'rain_monthly': _get_value(rainfall, 'monthly'),
        'rain_yearly': _get_value(rainfall, 'yearly'),
        'wind_speed': _get_value(wind, 'wind_speed'),
        'wind_gust': _get_value(wind, 'wind_gust'),
        'wind_direction': _get_value(wind, 'wind_direction'),
        'pressure_relative': _get_value(pressure, 'relative'),
        'pressure_absolute': _get_value(pressure, 'absolute'),
        'battery_sensor_array': _get_value({'sensor_array': battery}, 'sensor_array'),
    }

    wl = WeatherLogEcowitt(
        vpd_outdoor=raw_data['vpd_outdoor'],
        temperature_main_outdoor=raw_data['temperature_main_outdoor'],
        temperature_feels_like_outdoor=raw_data['temperature_feels_like_outdoor'],
        temperature_apparent_outdoor=raw_data['temperature_apparent_outdoor'],
        dew_point_outdoor=raw_data['dew_point_outdoor'],
        humidity_outdoor=raw_data['humidity_outdoor'],
        temperature_main_indoor=raw_data['temperature_main_indoor'],
        temperature_feels_like_indoor=raw_data['temperature_feels_like_indoor'],
        temperature_apparent_indoor=raw_data['temperature_apparent_indoor'],
        dew_point_indoor=raw_data['dew_point_indoor'],
        humidity_indoor=raw_data['humidity_indoor'],
        solar_irradiance=raw_data['solar_irradiance'],
        uvi=raw_data['uvi'],
        rain_rate=raw_data['rain_rate'],
        rain_daily=raw_data['rain_daily'],
        rain_event=raw_data['rain_event'],
        rain_hour=raw_data['rain_hour'],
        rain_weekly=raw_data['rain_weekly'],
        rain_monthly=raw_data['rain_monthly'],
        rain_yearly=raw_data['rain_yearly'],
        wind_speed=raw_data['wind_speed'],
        wind_gust=raw_data['wind_gust'],
        wind_direction=raw_data['wind_direction'],
        pressure_relative=raw_data['pressure_relative'],
        pressure_absolute=raw_data['pressure_absolute'],
        battery_sensor_array=raw_data['battery_sensor_array'],
        request_time=request_time_fix,
    )
    db.session.add(wl)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        logging.info(f"[Ecowitt] Duplikat request_time={request_time_fix.isoformat()}, skip.")
        return None
    except Exception as e:
        db.session.rollback()
        logging.error(f"[Ecowitt] Commit gagal: {e}")
        return None
    
    status = "[OK]"
    logging.info(f"[Ecowitt] {status} Data disimpan (ID: {wl.id})")
    return wl


# =====================================================================
# PROCESS CONSOLE DATA (dari POST request)
# =====================================================================

def process_console_data(raw_data: Dict[str, Any]) -> Optional[WeatherLogConsole]:
    """
    Proses data dari Console Station yang dikirim via POST.
    Data disimpan langsung tanpa konversi unit (Imperial units).
    
    Args:
        raw_data: Dictionary dari form data console station
    
    Returns:
        WeatherLogConsole instance atau None jika gagal
    """
    if not raw_data:
        logging.warning("[Console] Data kosong")
        return None
    
    # Parse dateutc
    date_utc = None
    dateutc_str = raw_data.get('dateutc')
    if dateutc_str:
        try:
            date_utc = datetime.strptime(dateutc_str, "%Y-%m-%d %H:%M:%S")
            date_utc = date_utc.replace(tzinfo=timezone.utc)
        except Exception as e:
            logging.warning(f"[Console] Gagal parse dateutc '{dateutc_str}': {e}")
            date_utc = datetime.now(timezone.utc)
    else:
        date_utc = datetime.now(timezone.utc)
    
    # Simpan data langsung tanpa konversi (Imperial units)
    wl = WeatherLogConsole(
        runtime=safe_int(raw_data.get('runtime'), None),
        heap=safe_int(raw_data.get('heap'), None),
        temperature_indoor=safe_float(raw_data.get('tempinf'), None),  # °F
        humidity_indoor=safe_float(raw_data.get('humidityin'), None),
        pressure_relative=safe_float(raw_data.get('baromrelin'), None),  # inHg
        pressure_absolute=safe_float(raw_data.get('baromabsin'), None),  # inHg
        temperature=safe_float(raw_data.get('tempf'), None),  # °F
        humidity=safe_float(raw_data.get('humidity'), None),
        wind_direction=safe_float(raw_data.get('winddir'), None),
        wind_speed=safe_float(raw_data.get('windspeedmph'), None),  # mph
        wind_gust=safe_float(raw_data.get('windgustmph'), None),  # mph
        max_daily_gust=safe_float(raw_data.get('maxdailygust'), None),  # mph
        solar_radiation=safe_float(raw_data.get('solarradiation'), None),  # W/m²
        uvi=safe_float(raw_data.get('uv'), None),
        rain_rate=safe_float(raw_data.get('rainratein'), None),  # in/hr
        rain_event=safe_float(raw_data.get('eventrainin'), None),  # in
        rain_hourly=safe_float(raw_data.get('hourlyrainin'), None),  # in
        rain_daily=safe_float(raw_data.get('dailyrainin'), None),  # in
        rain_weekly=safe_float(raw_data.get('weeklyrainin'), None),  # in
        rain_monthly=safe_float(raw_data.get('monthlyrainin'), None),  # in
        rain_yearly=safe_float(raw_data.get('yearlyrainin'), None),  # in
        rain_total=safe_float(raw_data.get('totalrainin'), None),  # in
        vpd=safe_float(raw_data.get('vpd'), None),  # kPa
        date_utc=date_utc,
    )
    
    db.session.add(wl)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        logging.info(f"[Console] Duplikat date_utc={date_utc.isoformat() if date_utc else 'N/A'}, skip.")
        return None
    except Exception as e:
        db.session.rollback()
        logging.error(f"[Console] Commit gagal: {e}")
        return None
    
    status = "[OK]"
    logging.info(f"[Console] {status} Data disimpan (ID: {wl.id})")
    return wl



# =====================================================================
# PARALLEL FETCH HELPERS
# =====================================================================

def _fetch_with_context(fetch_func, app, source_name: str):
    """Helper untuk menjalankan fetch function dengan app context."""
    with app.app_context():
        try:
            result = fetch_func()
            return source_name, result, None
        except Exception as e:
            logging.error(f"[{source_name}] Error: {e}")
            db.session.rollback()
            return source_name, None, str(e)


def fetch_and_store_weather():
    """
    Job untuk mengambil data cuaca dari semua sumber secara PARALEL.
    Berjalan setiap 5 menit (pada menit :00, :05, :10, :15, dst).
    
    Sumber yang di-fetch:
    1. Ecowitt (GET) - API Cloud
    2. Wunderground (GET) - API Cloud
    
    Note: Console data diterima via POST endpoint terpisah, bukan dijadwalkan.
    
    Event-Driven Prediction:
    Jika fetch berjalan pada jam pas (menit < 5, toleransi delay retry),
    maka run_hourly_prediction() akan dipanggil SINKRON setelah fetch selesai.
    Ini menjamin urutan: Fetch → Data Tersimpan → Prediction.
    """
    # Dapatkan app instance untuk context
    if getattr(scheduler, 'app', None) is not None:
        app = scheduler.app
    else:
        app = current_app._get_current_object()
    
    now = datetime.now(timezone.utc)
    wib = now.astimezone(timezone(timedelta(hours=7)))
    
    logging.info(f"{'='*60}")
    logging.info(f"[FETCH] Memulai pengambilan data cuaca (PARALEL)")
    logging.info(f"[FETCH] Waktu: {wib.strftime('%Y-%m-%d %H:%M:%S')} WIB")
    logging.info(f"{'='*60}")
    
    results = {}
    
    # Parallel fetching menggunakan ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='weather_fetch') as executor:
        futures = {
            executor.submit(_fetch_with_context, fetch_ecowitt, app, 'Ecowitt'): 'Ecowitt',
            executor.submit(_fetch_with_context, fetch_wunderground, app, 'Wunderground'): 'Wunderground',
        }
        
        try:
            for future in as_completed(futures, timeout=PARALLEL_TIMEOUT):
                try:
                    source_name, result, error = future.result()
                    results[source_name] = result
                    if error:
                        logging.warning(f"[FETCH] {source_name}: {error}")
                except Exception as e:
                    source_name = futures[future]
                    logging.error(f"[FETCH] {source_name} exception: {e}")
                    results[source_name] = None
        except TimeoutError:
            # as_completed() timeout — beberapa fetch belum selesai (retry masih jalan)
            for future, source_name in futures.items():
                if source_name not in results:
                    logging.error(
                        f"[FETCH] {source_name} TIMEOUT setelah {PARALLEL_TIMEOUT}s "
                        f"(retry mungkin masih berjalan). Ditandai gagal."
                    )
                    results[source_name] = None
                    future.cancel()
    
    # Log hasil
    success_count = sum(1 for r in results.values() if r is not None)
    total_count = len(results)
    
    success_sources = [f"{k}(ID:{v.id})" for k, v in results.items() if v is not None]
    failed_sources = [k for k, v in results.items() if v is None]
    
    if success_sources:
        logging.info(f"[FETCH] [OK] Berhasil: {', '.join(success_sources)}")
    if failed_sources:
        logging.warning(f"[FETCH] [!] Gagal: {', '.join(failed_sources)}")
    
    logging.info(f"[FETCH] Selesai ({success_count}/{total_count} sumber)")
    logging.info(f"{'='*60}")
    
    # ─────────────────────────────────────────────────────────
    # EVENT-DRIVEN PREDICTION: Chain prediction setelah fetch
    # pada jam pas (toleransi menit < 5 untuk delay retry).
    # Ini adalah PRIMARY trigger. SAFETY trigger berjalan
    # di menit ke-8 jika primary gagal (lihat scheduler_init.py).
    # ─────────────────────────────────────────────────────────
    fetch_finish_wib = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=7)))
    if fetch_finish_wib.minute < 5:
        if success_count > 0:
            # Console TIDAK di-fetch di sini (via POST), jadi TIDAK di-skip
            skip_sources = [s.lower() for s in failed_sources]
            if skip_sources:
                logging.warning(f"[FETCH->PREDICT] Source GAGAL fetch: {skip_sources} -> prediksi di-SKIP untuk source ini")
            logging.info(
                f"[FETCH->PREDICT] Jam pas + {success_count}/{total_count} fetch OK. "
                f"Memicu prediksi..."
            )
            try:
                run_hourly_prediction(skip_sources=skip_sources)
                # Mark: prediksi sudah berjalan pada jam ini (untuk dedup guard)
                from .scheduler_init import _mark_prediction_done
                _mark_prediction_done()
                logging.info("[FETCH->PREDICT] Dedup guard updated — safety cron akan SKIP jam ini")
            except Exception as e:
                logging.error(f"[FETCH->PREDICT] Gagal memicu prediksi: {e}")
        else:
            logging.warning(
                "[FETCH->PREDICT] Jam pas tapi SEMUA fetch gagal. "
                "Prediksi DIBATALKAN."
            )
    
    return results


# =====================================================================
# HOURLY PREDICTION JOB
# =====================================================================

def run_hourly_prediction(skip_sources: list = None):
    """
    Job untuk menjalankan prediksi cuaca.
    Berjalan setiap JAM PAS (menit ke-00), tidak ada toleransi menit.
    
    Args:
        skip_sources: List source yang di-skip karena fetch gagal.
                      Contoh: ['wunderground'] jika Wunderground fetch gagal.
                      None = proses semua source (default, dipakai safety net).
    
    Urutan prediksi: Console -> Ecowitt -> Wunderground
    Hasil prediksi disimpan ke database (PredictionLog).
    """
    appctx = None
    if getattr(scheduler, 'app', None) is not None:
        appctx = scheduler.app.app_context()
    else:
        appctx = current_app.app_context()
    
    with appctx:
        now = datetime.now(timezone.utc)
        wib = now.astimezone(timezone(timedelta(hours=7)))
        
        logging.info(f"{'='*60}")
        logging.info(f"[PREDIKSI] Memulai job prediksi per jam")
        logging.info(f"[PREDIKSI] Waktu: {wib.strftime('%Y-%m-%d %H:%M:%S')} WIB")
        if skip_sources:
            logging.info(f"[PREDIKSI] Skip sources (fetch gagal): {skip_sources}")
        logging.info(f"{'='*60}")
        
        try:
            # Import prediction service
            from .services.prediction_service import run_prediction_pipeline, initialize_models
            
            # Pastikan model sudah diinisialisasi (seharusnya sudah dari startup)
            initialize_models()
            
            # Jalankan pipeline prediksi (dengan filter source jika ada yang gagal fetch)
            result = run_prediction_pipeline(skip_sources=skip_sources)
            
            if result:
                logging.info(f"[PREDIKSI] [OK] Berhasil. PredictionLog ID: {result.id}")
            else:
                logging.warning(f"[PREDIKSI] [!] Tidak menghasilkan data")
                
        except Exception as e:
            logging.error(f"[PREDIKSI] Error: {e}")
            db.session.rollback()
        
        logging.info(f"{'='*60}")


# =====================================================================
# SCHEDULER HELPER FUNCTIONS
# =====================================================================

def calculate_next_5min_time() -> datetime:
    """
    Hitung waktu berikutnya yang tepat pada menit kelipatan 5.
    Contoh: Jika sekarang 10:03:45, return 10:05:00
    """
    now = datetime.now(timezone.utc)
    minute = now.minute
    next_5min = ((minute // 5) + 1) * 5
    
    if next_5min >= 60:
        next_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        next_time = now.replace(minute=next_5min, second=0, microsecond=0)
    
    return next_time


def calculate_next_hour_time() -> datetime:
    """
    Hitung waktu jam berikutnya yang tepat (menit 00).
    Contoh: Jika sekarang 10:30:45, return 11:00:00
    """
    now = datetime.now(timezone.utc)
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return next_hour