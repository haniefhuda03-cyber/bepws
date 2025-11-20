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
from .ml_model import run_prediction, LABEL_MAP
from .secrets import get_secret
from concurrent.futures import ThreadPoolExecutor
import random
from flask import current_app
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError


from dotenv import load_dotenv
from .set_variables import *


logging.error(f'[ECO] ====== APP_KEY: {ECO_APP_KEY} | API_KEY: {ECO_API_KEY} | ECO_MAC: {ECO_MAC} | DATABASE_URL: {DATABASE_URL}')

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
    metric = obs.get("metric", {})

    wind_speed_kmh = metric.get("windSpeed")
    wind_gust_kmh = metric.get("windGust")

    wl = WeatherLogWunderground(
        solar_radiation=obs.get("solarRadiation"),
        ultraviolet_radiation=obs.get("uv"),
        humidity=obs.get("humidity"),
        temperature=metric.get("temp"),
        pressure=metric.get("pressure"),
        wind_direction=obs.get("winddir"),
        wind_speed=wind_speed_kmh,
        wind_gust=wind_gust_kmh,
        precipitation_rate=metric.get("precipRate"),
        precipitation_total=metric.get("precipTotal"),
        request_time=datetime.now(timezone.utc),
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
        "solar_irradiance_unitid": 16,
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
        request_time=datetime.now(timezone.utc),
    )
    db.session.add(wl)
    db.session.commit()
    logging.info(f"Berhasil mengambil dan menyimpan data Ecowitt (ID: {wl.id}).")
    return wl


def fetch_and_store_weather():
    from flask import current_app
    appctx = None
    if getattr(scheduler, 'app', None) is not None:
        appctx = scheduler.app.app_context()
    else:
        appctx = current_app.app_context()
    with appctx:
        logging.info(f"[{datetime.now(timezone.utc)}] Memulai pipeline ambil/simpan/prediksi...")

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
            logging.info(f"[{datetime.now(timezone.utc)}] Tidak ada data yang diambil dari sumber manapun. Pipeline selesai.")
            return

        model_meta = db.session.query(ModelMeta).first()
        if not model_meta:
            logging.warning("Tidak ada entri Model di database. Prediksi akan dilewati.")
            return

        pl = PredictionLog(
            weather_log_wunderground_id=wu_log.id if wu_log else None,
            weather_log_ecowitt_id=eco_log.id if eco_log else None,
            model_id=model_meta.id,
        )
        db.session.add(pl)
        db.session.commit()

        prediction_tasks = {}
        if wu_log:
            wu_wind_speed_ms = (float(wu_log.wind_speed) / 3.6) if wu_log.wind_speed is not None else None
            features_wu = {
                'suhu': float(wu_log.temperature) if wu_log.temperature is not None else None,
                'kelembaban': float(wu_log.humidity) if wu_log.humidity is not None else None,
                'kecepatan_angin': wu_wind_speed_ms,
                'arah_angin': float(wu_log.wind_direction) if wu_log.wind_direction is not None else None,
                'tekanan_udara': float(wu_log.pressure) if wu_log.pressure is not None else None,
                'intensitas_hujan': float(wu_log.precipitation_rate) if wu_log.precipitation_rate is not None else 0.0,
            }
            prediction_tasks['wunderground'] = features_wu

        if eco_log:
            features_eco = {
                'suhu': float(eco_log.temperature_main_outdoor) if eco_log.temperature_main_outdoor is not None else None,
                'kelembaban': float(eco_log.humidity_outdoor) if eco_log.humidity_outdoor is not None else None,
                'kecepatan_angin': float(eco_log.wind_speed) if eco_log.wind_speed is not None else None,
                'arah_angin': float(eco_log.wind_direction) if eco_log.wind_direction is not None else None,
                'tekanan_udara': float(eco_log.pressure_relative) if eco_log.pressure_relative is not None else None,
                'intensitas_hujan': float(eco_log.rain_rate) if eco_log.rain_rate is not None else 0.0,
            }
            prediction_tasks['ecowitt'] = features_eco

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_source = {executor.submit(run_prediction, features): source for source, features in prediction_tasks.items()}

            for future in future_to_source:
                source = future_to_source[future]
                try:
                    label_value = future.result(timeout=30)
                    logging.info(f"Prediksi untuk {source} menghasilkan label: {label_value}")

                    if label_value is not None:
                        label_text = LABEL_MAP.get(label_value, 'Label tidak diketahui')
                        label = db.session.query(Label).filter_by(name=label_text).first()

                        if not label:
                            label = Label(name=label_text)
                            db.session.add(label)
                            db.session.commit()

                        if source == 'wunderground':
                            pl.wunderground_prediction_result = label.id
                        elif source == 'ecowitt':
                            pl.ecowitt_prediction_result = label.id

                except Exception as e:
                    logging.error(f"Prediksi gagal untuk {source}: {e}")
        db.session.commit()
        logging.info(f"[{datetime.now(timezone.utc)}] PredictionLog diperbarui dengan hasil (ID: {pl.id}). Pipeline selesai.")