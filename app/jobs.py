import requests
import os
from datetime import datetime, timezone
from typing import Optional, Any, Dict
import logging
from . import scheduler, db
from .models import (
    WeatherLogWunderground,
    WeatherLogEcowitt,
    PredictionLog,
    Label,
    Model as ModelMeta,
)
from .secrets import get_secret
from concurrent.futures import ThreadPoolExecutor
import random
from flask import current_app
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError
from dotenv import load_dotenv
from .set_variables import *

def _mask_secret(val: str) -> str:
    if not val:
        return None
    s = str(val)
    if len(s) <= 6:
        return '***'
    return f"{s[:3]}...{s[-3:]}"

try:
    masked_app = _mask_secret(globals().get('ECO_APP_KEY'))
    masked_api = _mask_secret(globals().get('ECO_API_KEY'))
    masked_mac = _mask_secret(globals().get('ECO_MAC'))
    db_url = globals().get('DATABASE_URL')
    db_host = None
    if db_url and '@' in str(db_url):
        db_host = str(db_url).split('@', 1)[1]
    else:
        db_host = str(db_url) if db_url else None
    logging.info(f'[ECO] APP_KEY={masked_app} | API_KEY={masked_api} | ECO_MAC={masked_mac} | DATABASE={db_host}')
except Exception:
    logging.debug('ECO env vars present but masked for safety')

if not WUNDERGROUND_URL:
    logging.warning('WUNDERGROUND_URL belum diset melalui environment atau secrets. Pengambilan data Wunderground akan dilewati sampai variabel ini diset.')

ECO_APP_KEY =  os.environ.get("ECO_APP_KEY")
ECO_API_KEY =  os.environ.get("ECO_API_KEY")
ECO_MAC = os.environ.get("ECO_MAC")
if not any([ECO_APP_KEY, ECO_API_KEY, ECO_MAC]):
    logging.warning('Kredensial Ecowitt belum diset melalui environment atau secrets. fetch_ecowitt mungkin gagal atau mengembalikan None.')
ECO_BASE = "https://api.ecowitt.net/api/v3"

def _requests_get_with_retry(url, params=None, timeout=15):
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

def fetch_wunderground() -> Optional[WeatherLogWunderground]:
    testing = False
    try:
        from flask import current_app
        testing = bool(current_app.config.get('TESTING', False))
    except Exception:
        testing = False

    if not WUNDERGROUND_URL and not testing:
        logging.warning("fetch_wunderground dipanggil tetapi WUNDERGROUND_URL belum diset; melewati proses pengambilan data.")
        return None

    try:
        if testing:
            resp = requests.get(WUNDERGROUND_URL, timeout=15)
            resp.raise_for_status()
        else:
            resp = _requests_get_with_retry(WUNDERGROUND_URL, timeout=15)
        data = resp.json()
    except RetryError as re:
        logging.error(f"Gagal mengambil Wunderground setelah beberapa percobaan: {re}")
        return None
    except Exception as e:
        logging.error(f"Gagal mengambil Wunderground: {e}")
        return None
    
    if not data or "observations" not in data or not data["observations"]:
        logging.warning("Format respons Wunderground tidak valid atau tidak ada data observasi.")
        return None
    
    obs = data["observations"][0]
    metric_si = obs.get("metric_si", {})
    
    request_time_str = obs.get("obsTimeUtc")

    try:
        if request_time_str:
            request_time_utc = datetime.fromisoformat(request_time_str.replace("Z", "+00:00"))
        else:
            raise ValueError("Request time tidak tersedia.")
    except Exception:
        request_time_utc = datetime.now(timezone.utc)
        logging.warning("Gagal mengurai atau mendapatkan waktu permintaan dari Wunderground; menggunakan waktu saat ini (UTC) sebagai gantinya.")

    wl = WeatherLogWunderground(
        solar_radiation=obs.get("solarRadiation"),
        ultraviolet_radiation=obs.get("uv"),
        humidity=obs.get("humidity"),
        temperature=metric_si.get("temp"),
        pressure=metric_si.get("pressure"),
        wind_direction=obs.get("winddir"),
        wind_speed=metric_si.get("windSpeed"),
        wind_gust=metric_si.get("windGust"),
        precipitation_rate=metric_si.get("precipRate"),
        precipitation_total=metric_si.get("precipTotal"),
        request_time=request_time_utc,
    )
    db.session.add(wl)
    db.session.commit()
    logging.info(f"Berhasil mengambil dan menyimpan data Wunderground (ID: {wl.id}).")
    return wl


def fetch_ecowitt() -> Optional[WeatherLogEcowitt]:
    testing = False
    try:
        testing = bool(current_app.config.get('TESTING', False))
    except Exception:
        testing = False

    params = {
        "application_key": ECO_APP_KEY,
        "api_key": ECO_API_KEY,
        "mac": ECO_MAC,
        "call_back": "all",
        "temp_unitid": 1,
        "pressure_unitid": 3,
        "wind_speed_unitid": 6,
        "rainfall_unitid": 12,
        "solar_irradiance_unitid": 14,
    }
    url = f"{ECO_BASE}/device/real_time"

    try:
        if testing:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
        else:
            resp = _requests_get_with_retry(url, params=params, timeout=15)
        response_data = resp.json()
    except RetryError as re:
        logging.error(f"Gagal mengambil Ecowitt setelah beberapa percobaan: {re}")
        return None
    except Exception as e:
        logging.error(f"Gagal mengambil Ecowitt: {e}")
        return None

    if response_data.get("code") != 0 or "data" not in response_data:
        logging.warning(f"API Ecowitt mengembalikan error atau data tidak valid: {response_data.get('msg', 'Tidak ada pesan')}")
        return None

    data = response_data['data']

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

    wl = WeatherLogEcowitt(
        vpd_outdoor=_get_value(outdoor, 'vpd'),
        temperature_main_outdoor=_get_value(outdoor, 'temperature'),
        temperature_feels_like_outdoor=_get_value(outdoor, 'feels_like'),
        temperature_apparent_outdoor=_get_value(outdoor, 'app_temp'),
        dew_point_outdoor=_get_value(outdoor, 'dew_point'),
        humidity_outdoor=_get_value(outdoor, 'humidity'),
        temperature_main_indoor=_get_value(indoor, 'temperature'),
        temperature_feels_like_indoor=_get_value(indoor, 'feels_like'),
        temperature_apparent_indoor=_get_value(indoor, 'app_tempin'),
        dew_point_indoor=_get_value(indoor, 'dew_point'),
        humidity_indoor=_get_value(indoor, 'humidity'),
        solar_irradiance=_get_value(solar_uvi, 'solar'),
        uvi=_get_value(solar_uvi, 'uvi'),
        rain_rate=_get_value(rainfall, 'rain_rate'),
        rain_daily=_get_value(rainfall, 'daily'),
        rain_event=_get_value(rainfall, 'event'),
        rain_hour=_get_value(rainfall, '1_hour'),
        rain_weekly=_get_value(rainfall, 'weekly'),
        rain_monthly=_get_value(rainfall, 'monthly'),
        rain_yearly=_get_value(rainfall, 'yearly'),
        wind_speed=_get_value(wind, 'wind_speed'),
        wind_gust=_get_value(wind, 'wind_gust'),
        wind_direction=_get_value(wind, 'wind_direction'),
        pressure_relative=_get_value(pressure, 'relative'),
        pressure_absolute=_get_value(pressure, 'absolute'),
        battery_sensor_array=_get_value({'sensor_array': battery}, 'sensor_array'),
        request_time=request_time_fix,
    )
    db.session.add(wl)
    db.session.commit()
    logging.info(f"Berhasil mengambil dan menyimpan data Ecowitt (ID: {wl.id}).")
    return wl

def fetch_and_store_weather():
    """
    Job untuk mengambil dan menyimpan data cuaca dari Wunderground dan Ecowitt.
    Berjalan setiap 5 menit.
    TIDAK melakukan prediksi - prediksi dilakukan di job terpisah.
    """
    from flask import current_app
    appctx = None
    if getattr(scheduler, 'app', None) is not None:
        appctx = scheduler.app.app_context()
    else:
        appctx = current_app.app_context()
    with appctx:
        logging.info(f"[{datetime.now(timezone.utc)}] Memulai pengambilan data cuaca...")

        wu_log, eco_log = None, None
        try:
            wu_log = fetch_wunderground()
        except Exception as e:
            logging.error(f"Gagal mengambil data dari Wunderground: {e}")
            db.session.rollback()

        try:
            eco_log = fetch_ecowitt()
        except Exception as e:
            logging.error(f"Gagal mengambil data dari Ecowitt: {e}")
            db.session.rollback()

        if not wu_log and not eco_log:
            logging.info(f"[{datetime.now(timezone.utc)}] Tidak ada data yang diambil dari sumber manapun.")
            return

        logging.info(f"[{datetime.now(timezone.utc)}] Data cuaca berhasil diambil. WU ID: {wu_log.id if wu_log else None}, ECO ID: {eco_log.id if eco_log else None}")


def run_hourly_prediction():
    """
    Job untuk menjalankan prediksi cuaca.
    Berjalan setiap JAM (menit ke-00), terpisah dari job fetching data.
    Menggunakan prediction_service dengan layering architecture.
    """
    from flask import current_app
    appctx = None
    if getattr(scheduler, 'app', None) is not None:
        appctx = scheduler.app.app_context()
    else:
        appctx = current_app.app_context()
    
    with appctx:
        logging.info(f"[{datetime.now(timezone.utc)}] Memulai job prediksi per jam...")
        
        try:
            # Import prediction service
            from .services.prediction_service import run_prediction_pipeline, initialize_models
            
            # Pastikan model sudah diinisialisasi
            initialize_models()
            
            # Jalankan pipeline prediksi
            result = run_prediction_pipeline()
            
            if result:
                logging.info(f"[{datetime.now(timezone.utc)}] Prediksi berhasil. PredictionLog ID: {result.id}")
            else:
                logging.warning(f"[{datetime.now(timezone.utc)}] Prediksi tidak menghasilkan data.")
                
        except Exception as e:
            logging.error(f"Error saat menjalankan prediksi per jam: {e}")
            db.session.rollback()