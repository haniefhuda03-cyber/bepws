import os
import time
import math
import logging
from datetime import timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List

import numpy as np
import pandas as pd

from . import db
from .models import WeatherLogEcowitt, WeatherLogWunderground
from flask import current_app

try:
    import joblib
except Exception:
    joblib = None

try:
    from sklearn.preprocessing import MinMaxScaler
except Exception:
    MinMaxScaler = None

try:
    import tensorflow as tf
except Exception:
    tf = None

# --- Konfigurasi path model & scaler ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODEL_PATH = os.path.join(BASE_DIR, 'ml_models', 'model_lstm_regresi_telkom.keras')
SCALER_PATH = os.path.join(BASE_DIR, 'ml_models', 'scalerFIT_split.joblib')

# caching model dan scaler
_cached_model = None
_model_loaded_at = 0.0
_model_reload_interval = 300.0  # 5 menit
_cached_scaler = None

# constants untuk fitur
SEQUENCE_LENGTH = 144
N_FEATURES = 9

# conversion factor W/m2 -> lux (perkiraan). Digunakan hanya untuk Wunderground sesuai instruksi.
# Faktor ini adalah nilai perkiraan; nilai sebenarnya bergantung spektrum cahaya.
WM2_TO_LUX = 126.7

# --- Loss custom (harus persis seperti yang diberikan) ---
RAIN_EVENT_WEIGHT = 10.0
NO_RAIN_WEIGHT = 1.0

def weighted_masked_regression_loss(y_true, y_pred):
    squared_error = tf.square(y_true - y_pred)
    is_raining_mask = tf.cast(tf.greater(y_true, 0), tf.float32)
    weight = (is_raining_mask * (RAIN_EVENT_WEIGHT - NO_RAIN_WEIGHT) + NO_RAIN_WEIGHT)
    weighted_square_error = squared_error * weight
    return tf.reduce_mean(weighted_square_error)


def _load_scaler() -> Optional[Any]:
    global _cached_scaler
    if _cached_scaler is not None:
        return _cached_scaler
    if joblib is None:
        logging.warning('joblib tidak tersedia; scaler tidak dimuat')
        return None
    try:
        if os.path.exists(SCALER_PATH):
            _cached_scaler = joblib.load(SCALER_PATH)
            logging.info(f'Scaler dimuat dari {SCALER_PATH}')
            # pastikan scaler adalah MinMaxScaler jika memungkinkan
            if MinMaxScaler is not None:
                try:
                    if not isinstance(_cached_scaler, MinMaxScaler):
                        logging.warning('Scaler ter-load bukan MinMaxScaler. Akan menggunakan MinMaxScaler saat preprocessing sebagai fallback.')
                except Exception:
                    logging.debug('Tidak bisa memeriksa instance scaler dengan MinMaxScaler')
        else:
            logging.warning(f'Scaler tidak ditemukan di {SCALER_PATH}')
            _cached_scaler = None
    except Exception as e:
        logging.error(f'Gagal memuat scaler: {e}')
        _cached_scaler = None
    return _cached_scaler


def _load_model_if_needed() -> Optional[Any]:
    """Muat model jika belum ada atau sudah lebih lama dari interval reload.
    Mengembalikan objek model TensorFlow atau None jika gagal.
    """
    global _cached_model, _model_loaded_at
    now = time.time()
    if _cached_model is not None and (now - _model_loaded_at) < _model_reload_interval:
        return _cached_model

    if tf is None:
        logging.error('TensorFlow tidak tersedia, model LSTM tidak dapat dimuat')
        return None

    try:
        if os.path.exists(MODEL_PATH):
            model = tf.keras.models.load_model(MODEL_PATH, custom_objects={'weighted_masked_regression_loss': weighted_masked_regression_loss})
            _cached_model = model
            _model_loaded_at = now
            logging.info(f'Model LSTM dimuat dari {MODEL_PATH} pada {time.ctime(now)}')
            return _cached_model
        else:
            logging.error(f'File model tidak ditemukan di {MODEL_PATH}')
            return None
    except Exception as e:
        logging.error(f'Gagal memuat model LSTM: {e}')
        return None


def _row_to_features_wunderground(row) -> Optional[List[float]]:
    """Konversi satu baris WeatherLogWunderground menjadi vektor fitur 9 elemen.
    Perhatikan: konversi W/m2 -> lux hanya untuk sumber Wunderground (kolom solar_radiation).
    """
    try:
        suhu = float(row.temperature) if row.temperature is not None else None
        kelembaban = float(row.humidity) if row.humidity is not None else None
        kecepatan_angin = float(row.wind_speed) if row.wind_speed is not None else None
        arah_angin = float(row.wind_direction) if row.wind_direction is not None else None
        tekanan = float(row.pressure) if row.pressure is not None else None
        intensitas_hujan = float(row.precipitation_rate) if row.precipitation_rate is not None else 0.0
        # solar_radiation pada Wunderground diasumsikan W/m2 -> konversi ke lux
        solar_wm2 = float(row.solar_radiation) if row.solar_radiation is not None else 0.0
        intensitas_cahaya = solar_wm2 * WM2_TO_LUX

        # hour sin/cos dari request_time (convert ke WIB)
        rt = row.request_time
        if rt is None:
            return None
        if rt.tzinfo is None:
            rt = rt.replace(tzinfo=timezone.utc)
        wib = rt.astimezone(timezone(timedelta(hours=7)))
        hour_decimal = wib.hour + wib.minute / 60.0 + wib.second / 3600.0
        angle = 2.0 * math.pi * (hour_decimal / 24.0)
        hour_sin = math.sin(angle)
        hour_cos = math.cos(angle)

        return [suhu, kelembaban, kecepatan_angin, arah_angin, tekanan, intensitas_hujan, intensitas_cahaya, hour_sin, hour_cos]
    except Exception:
        return None


def _row_to_features_ecowitt(row) -> Optional[List[float]]:
    """Konversi satu baris WeatherLogEcowitt menjadi vektor fitur 9 elemen.
    Catatan: instruksi menyebutkan Ecowitt sudah dalam Lux untuk solar_irradiance.
    Untuk tekanan gunakan pressure_relative; untuk intensitas_hujan gunakan rain_rate.
    """
    try:
        suhu = float(row.temperature_main_outdoor) if row.temperature_main_outdoor is not None else None
        kelembaban = float(row.humidity_outdoor) if row.humidity_outdoor is not None else None
        kecepatan_angin = float(row.wind_speed) if row.wind_speed is not None else None
        arah_angin = float(row.wind_direction) if row.wind_direction is not None else None
        tekanan = float(row.pressure_relative) if row.pressure_relative is not None else None
        intensitas_hujan = float(row.rain_rate) if row.rain_rate is not None else 0.0
        intensitas_cahaya = float(row.solar_irradiance) if row.solar_irradiance is not None else 0.0

        rt = row.request_time
        if rt is None:
            return None
        if rt.tzinfo is None:
            rt = rt.replace(tzinfo=timezone.utc)
        wib = rt.astimezone(timezone(timedelta(hours=7)))
        hour_decimal = wib.hour + wib.minute / 60.0 + wib.second / 3600.0
        angle = 2.0 * math.pi * (hour_decimal / 24.0)
        hour_sin = math.sin(angle)
        hour_cos = math.cos(angle)

        return [suhu, kelembaban, kecepatan_angin, arah_angin, tekanan, intensitas_hujan, intensitas_cahaya, hour_sin, hour_cos]
    except Exception:
        return None


def _fetch_last_n_rows(model_name: str, n: int = SEQUENCE_LENGTH, app=None) -> Optional[List[Any]]:
    """Ambil n record terakhir (ordered by created_at desc) dari DB untuk source yang diberikan.
    model_name: 'ecowitt' atau 'wunderground'
    Mengembalikan list objek SQLAlchemy (dengan urutan kronologis ASC).
    Jika dipanggil dari thread worker, terima parameter `app` dan gunakan `app.app_context()`.
    """
    try:
        # Ensure we have an application context when querying from threads
        if app is None:
            try:
                app = current_app._get_current_object()
            except Exception:
                logging.error(f'No application context available for fetching {model_name} rows from DB.')
                return None

        with app.app_context():
            if model_name == 'ecowitt':
                q = db.session.query(WeatherLogEcowitt).order_by(WeatherLogEcowitt.created_at.desc()).limit(n).all()
            else:
                q = db.session.query(WeatherLogWunderground).order_by(WeatherLogWunderground.created_at.desc()).limit(n).all()
            if not q or len(q) < n:
                return None
            # q is DESC, reverse to get ASC chronologis
            q.reverse()
            return q
    except Exception as e:
        logging.error(f'Gagal mengambil data {model_name} dari DB: {e}')
        return None


def _prepare_sequence_from_rows(rows: List[Any], source: str) -> Optional[np.ndarray]:
    """Bangun array shape (144, 9) dari rows menurut source.
    Lakukan scaling menggunakan scaler yang dimuat.
    """
    features = []
    if source == 'ecowitt':
        for r in rows:
            fv = _row_to_features_ecowitt(r)
            if fv is None:
                return None
            features.append(fv)
    else:
        for r in rows:
            fv = _row_to_features_wunderground(r)
            if fv is None:
                return None
            features.append(fv)

    arr = np.array(features, dtype=float)  # shape (144,9)
    if arr.shape != (SEQUENCE_LENGTH, N_FEATURES):
        return None

    scaler = _load_scaler()
    # Jika scaler yang dimuat adalah MinMaxScaler, gunakan langsung.
    if scaler is not None:
        try:
            from sklearn.preprocessing import MinMaxScaler as _MMS
            if _MMS is not None and isinstance(scaler, _MMS):
                arr_scaled = scaler.transform(arr)
            else:
                # joblib scaler ada tapi bukan MinMaxScaler -> gunakan MinMaxScaler yang difit pada sequence saat ini
                logging.warning(f'Scaler ter-load bukan MinMaxScaler; melakukan fit MinMaxScaler pada sequence saat ini untuk {source}.')
                if _MMS is not None:
                    local_scaler = _MMS()
                    local_scaler.fit(arr)
                    arr_scaled = local_scaler.transform(arr)
                else:
                    logging.error('sklearn tidak tersedia untuk membuat MinMaxScaler; melewati scaling')
                    arr_scaled = arr
        except Exception as e:
            logging.error(f'Gagal men-scale data untuk {source}: {e}')
            arr_scaled = arr
    else:
        # tidak ada scaler di disk: buat MinMaxScaler lokal dan fit pada sequence saat ini
        try:
            from sklearn.preprocessing import MinMaxScaler as _MMS
            if _MMS is not None:
                local_scaler = _MMS()
                local_scaler.fit(arr)
                arr_scaled = local_scaler.transform(arr)
            else:
                logging.error('sklearn tidak tersedia untuk membuat MinMaxScaler; melewati scaling')
                arr_scaled = arr
        except Exception as e:
            logging.error(f'Gagal membuat/fit MinMaxScaler lokal: {e}')
            arr_scaled = arr

    # final shape expected (1, 144, 9)
    return arr_scaled.reshape((1, SEQUENCE_LENGTH, N_FEATURES))


def _predict_for_source(source: str, app=None) -> Optional[List[float]]:
    """Ambil data dari DB, prepare input dan jalankan prediksi model.
    Mengembalikan list 24 float atau None jika gagal.
    """
    try:
        rows = _fetch_last_n_rows(source, SEQUENCE_LENGTH, app=app)
        if rows is None:
            logging.warning(f'Jumlah data untuk {source} kurang dari {SEQUENCE_LENGTH}; prediksi dibatalkan untuk source ini.')
            return None

        x = _prepare_sequence_from_rows(rows, source)
        if x is None:
            logging.warning(f'Gagal menyiapkan sequence input untuk {source}')
            return None

        model = _load_model_if_needed()
        if model is None:
            logging.error('Model LSTM tidak tersedia; prediksi dibatalkan')
            return None

        # run predict
        pred = model.predict(x)
        # expect shape (1,24)
        arr = np.array(pred).reshape(-1).tolist()
        logging.info(f"[{source}] Prediksi 24 data ke depan: {arr}")
        return arr
    except Exception as e:
        logging.error(f'Error prediksi untuk {source}: {e}')
        return None


def run_parallel_lstm_predictions() -> Dict[str, Optional[List[float]]]:
    """Fungsi publik yang menjalankan pengambilan data dan prediksi untuk kedua sumber
    secara paralel dan mengembalikan dictionary hasil.
    """
    results: Dict[str, Optional[List[float]]] = {'ecowitt': None, 'wunderground': None}

    sources = ['ecowitt', 'wunderground']

    # Capture the current Flask app (if any) so worker threads can push app context
    app_obj = None
    try:
        app_obj = current_app._get_current_object()
    except Exception:
        app_obj = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(_predict_for_source, src, app_obj): src for src in sources}
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                res = fut.result()
                results[src] = res
            except Exception as e:
                logging.error(f'Prediksi paralel gagal untuk {src}: {e}')
                results[src] = None

    return results


if __name__ == '__main__':
    # simple smoke test when run directly (non-production)
    logging.basicConfig(level=logging.INFO)
    logging.info('Menjalankan prediksi LSTM paralel (smoke-test)')
    out = run_parallel_lstm_predictions()
    logging.info(f'Hasil: {out}')
