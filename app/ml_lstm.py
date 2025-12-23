import os
import math
import logging
import threading
import numpy as np
import pandas as pd  # Disarankan menggunakan Pandas untuk imputation
from datetime import timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, List
from sqlalchemy import func

# Flask & DB Imports
from flask import current_app
from . import db
from .models import WeatherLogEcowitt, WeatherLogWunderground

# ML Imports (Safe Import)
try:
    import joblib
    import tensorflow as tf
except ImportError:
    joblib = None
    tf = None

# --- KONFIGURASI PATH ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODEL_PATH = os.path.join(BASE_DIR, 'ml_models', 'model_lstm_regresi_telkom.keras')
SCALER_PATH = os.path.join(BASE_DIR, 'ml_models', 'scalerFIT_split.joblib')

# --- KONSTANTA MODEL ---
SEQUENCE_LENGTH = 144       # Input: 144 timestep ke belakang
PREDICTION_STEPS = 24       # Output: 24 timestep ke depan
N_FEATURES = 9              # Jumlah fitur sesuai scaler
WM2_TO_LUX = 126.7          # Konversi estimasi radiasi matahari ke lux
RAIN_FEATURE_INDEX = 5      # Index kolom 'intensitas_hujan' pada scaler (urutan ke-6)

# --- CUSTOM LOSS FUNCTION ---
# Wajib ada agar model Keras bisa di-load dengan benar
@tf.keras.utils.register_keras_serializable()
def weighted_masked_regression_loss(y_true, y_pred):
    if tf is None: return 0.0
    RAIN_EVENT_WEIGHT = 10.0
    NO_RAIN_WEIGHT = 1.0
    squared_error = tf.square(y_true - y_pred)
    is_raining_mask = tf.cast(tf.greater(y_true, 0), tf.float32)
    weight = (is_raining_mask * (RAIN_EVENT_WEIGHT - NO_RAIN_WEIGHT) + NO_RAIN_WEIGHT)
    weighted_square_error = squared_error * weight
    return tf.reduce_mean(weighted_square_error)

class WeatherPredictor:
    """
    Singleton Class Thread-Safe untuk mengelola Model ML dan Scaler.
    Memuat model dan scaler hanya sekali untuk efisiensi memori.
    """
    _instance = None
    _lock = threading.Lock() # Lock untuk mencegah race condition saat init
    model = None
    scaler = None
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(WeatherPredictor, cls).__new__(cls)
                cls._instance._load_resources()
        return cls._instance

    def _load_resources(self):
        """Memuat model dan scaler ke memori."""
        if not tf or not joblib:
            logging.error("Library TensorFlow atau Joblib tidak terinstall atau hilang.")
            return

        # 1. Load Scaler
        try:
            if os.path.exists(SCALER_PATH):
                self.scaler = joblib.load(SCALER_PATH)
                logging.info(f"Scaler berhasil dimuat dari {SCALER_PATH}")
                try:
                    logging.info(f"Scaler params: n_features_in_={getattr(self.scaler, 'n_features_in_', None)}, scale_[5]={getattr(self.scaler, 'scale_', None)[RAIN_FEATURE_INDEX] if hasattr(self.scaler, 'scale_') else None}, min_[5]={getattr(self.scaler, 'min_', None)[RAIN_FEATURE_INDEX] if hasattr(self.scaler, 'min_') else None}")
                except Exception:
                    pass
                # Validasi jumlah fitur scaler
                if self.scaler.n_features_in_ != N_FEATURES:
                    logging.error(f"Scaler mismatch! Harapan {N_FEATURES}, didapat {self.scaler.n_features_in_}")
            else:
                logging.critical(f"Scaler not found: {SCALER_PATH}. Predictions will not be accurate!")
        except Exception as e:
            logging.error(f"Error loading scaler: {e}")

        # 2. Load Model
        try:
            if os.path.exists(MODEL_PATH):
                self.model = tf.keras.models.load_model(
                    MODEL_PATH, 
                    custom_objects={'weighted_masked_regression_loss': weighted_masked_regression_loss},
                    compile=False # False agar lebih cepat jika tidak akan dilatih ulang
                )
                logging.info(f"Model LSTM berhasil dimuat dari {MODEL_PATH}")
                try:
                    logging.info(f"Model summary (short): {self.model.__class__.__name__} - outputs: {getattr(self.model, 'output_shape', None)}")
                except Exception:
                    pass
            else:
                logging.critical(f"Model not found: {MODEL_PATH}")
        except Exception as e:
            logging.error(f"Error loading model: {e}")

    def get_rain_inverse_params(self):
        """Mengambil parameter scale_ dan min_ khusus untuk fitur hujan (index 5) serta mengembalikan nilai asli hujan."""
        if self.scaler is None: return None, None
        # MinMaxScaler formula: X_std = (X - X.min(axis=0)) / (X.max(axis=0) - X.min(axis=0))
        # Sklearn menyimpan: scale_ = 1 / (max - min), min_ = -min * scale_
        # Formula Inverse: X = (X_scaled - min_) / scale_
        scale = self.scaler.scale_[RAIN_FEATURE_INDEX]
        min_val = self.scaler.min_[RAIN_FEATURE_INDEX]
        return scale, min_val

# --- HELPER FUNCTIONS ---

def _calculate_hour_components(request_time):
    """Menghitung komponen cyclical waktu (Sin/Cos)."""
    if request_time is None: return 0.0, 0.0
    if request_time.tzinfo is None:
        request_time = request_time.replace(tzinfo=timezone.utc)
    
    # Konversi ke WIB (UTC+7)
    wib = request_time.astimezone(timezone(timedelta(hours=7)))
    hour_decimal = wib.hour + (wib.minute / 60.0)
    # hour_decimal = wib.hour + (wib.minute / 60.0) + (wib.second / 3600.0)
    angle = 2.0 * math.pi * (hour_decimal / 24.0)
    return math.sin(angle), math.cos(angle)

def _fetch_cleaned_dataframe(source: str, app) -> Optional[pd.DataFrame]:
    """Mengambil data dan membersihkannya (Handling Missing Values)."""
    with app.app_context():
        try:
            ModelClass = WeatherLogEcowitt if source == 'ecowitt' else WeatherLogWunderground
            # Kita akan mencari timestamp maksimum, lalu membangun rentang waktu
            # yang diharapkan (SEQUENCE_LENGTH titik dengan selisih tepat 5 menit).
            max_ts = db.session.query(func.max(ModelClass.request_time)).scalar()
            if not max_ts:
                logging.info(f"Tidak ada data request_time untuk sumber {source}.")
                return None

            # Normalize latest timestamp: drop seconds/microseconds and floor to 5-minute
            try:
                latest = max_ts
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=timezone.utc)
            except Exception:
                latest = max_ts

            # Floor minutes to nearest 5-minute
            minute = (latest.minute // 5) * 5
            latest_aligned = latest.replace(minute=minute, second=0, microsecond=0)

            # Compute start time (oldest required)
            span_minutes = 5 * (SEQUENCE_LENGTH - 1)
            start_time = latest_aligned - timedelta(minutes=span_minutes)

            # Fetch all rows between start_time - 5min buffer and latest_aligned (inclusive)
            buffer_start = start_time - timedelta(minutes=5)
            rows = db.session.query(ModelClass)
            rows = rows.filter(ModelClass.request_time >= buffer_start)
            rows = rows.filter(ModelClass.request_time <= latest_aligned + timedelta(minutes=1))
            rows = rows.order_by(ModelClass.request_time.asc()).all()

            if not rows or len(rows) < SEQUENCE_LENGTH:
                logging.info(f"Tidak cukup baris dalam rentang waktu untuk LSTM pada sumber {source}: dibutuhkan minimal {SEQUENCE_LENGTH}, ditemukan {len(rows) if rows else 0}")
                return None

            # Build mapping from rounded timestamp (floor to 5-min, seconds=0) -> latest row for that minute
            mapping = {}
            for r in rows:
                rt = r.request_time
                if rt is None:
                    continue
                if rt.tzinfo is None:
                    rt = rt.replace(tzinfo=timezone.utc)
                # floor to 5-minute and remove seconds
                m = (rt.minute // 5) * 5
                key = rt.replace(minute=m, second=0, microsecond=0)
                # keep the last observed row for that key (since rows ordered asc, later ones will overwrite)
                mapping[key] = r

            # Build expected timestamps (old -> new)
            expected = [start_time + timedelta(minutes=5 * i) for i in range(SEQUENCE_LENGTH)]

            data = []
            missing = []
            for ts in expected:
                # ensure tzinfo same as keys
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                row = mapping.get(ts)
                if not row:
                    missing.append(ts)
                else:
                    if source == 'wunderground':
                        solar = (float(row.solar_radiation) * WM2_TO_LUX) if row.solar_radiation is not None else 0.0
                        item = {
                            'suhu': float(row.temperature) if row.temperature is not None else np.nan,
                            'kelembaban': float(row.humidity) if row.humidity is not None else np.nan,
                            'kecepatan_angin': float(row.wind_speed) if row.wind_speed is not None else 0.0,
                            'arah_angin': float(row.wind_direction) if row.wind_direction is not None else 0.0,
                            'tekanan_udara': float(row.pressure) if row.pressure is not None else np.nan,
                            'intensitas_hujan': float(row.precipitation_rate) if row.precipitation_rate is not None else 0.0,
                            'intensitas_cahaya': solar,
                            'req_time': ts
                        }
                    else:
                        item = {
                            'suhu': float(row.temperature_main_outdoor) if row.temperature_main_outdoor is not None else np.nan,
                            'kelembaban': float(row.humidity_outdoor) if row.humidity_outdoor is not None else np.nan,
                            'kecepatan_angin': float(row.wind_speed) if row.wind_speed is not None else 0.0,
                            'arah_angin': float(row.wind_direction) if row.wind_direction is not None else 0.0,
                            'tekanan_udara': float(row.pressure_relative) if row.pressure_relative is not None else np.nan,
                            'intensitas_hujan': float(row.rain_rate) if row.rain_rate is not None else 0.0,
                            'intensitas_cahaya': float(row.solar_irradiance) if row.solar_irradiance is not None else 0.0,
                            'req_time': ts
                        }
                    data.append(item)

            if missing:
                logging.info(f"Tidak cukup data berjarak 5 menit untuk LSTM pada sumber {source}: missing timestamps count={len(missing)}. contoh: {missing[:3]}")
                return None

            df = pd.DataFrame(data)

            # 1. IMPUTATION: Isi NaN dengan nilai sebelumnya (Forward Fill)
            # Pressure 0.0 atau NaN akan merusak scaler, jadi kita ffill
            df = df.ffill().bfill()

            # 2. Hitung Time Features (Sin/Cos)
            sin_cos = df['req_time'].apply(lambda x: pd.Series(_calculate_hour_components(x)))
            df['hour_sin'] = sin_cos[0]
            df['hour_cos'] = sin_cos[1]

            # 3. Urutkan Kolom Sesuai Scaler (SANGAT PENTING)
            # Urutan dari scalerFIT_split.joblib 
            feature_order = [
                'suhu', 'kelembaban', 'kecepatan_angin', 'arah_angin', 
                'tekanan_udara', 'intensitas_hujan', 'intensitas_cahaya', 
                'hour_sin', 'hour_cos'
            ]
            
            # Ambil hanya 144 baris terakhir
            final_df = df[feature_order].tail(SEQUENCE_LENGTH)

            logging.debug(f"Prepared dataframe for {source}: shape={final_df.shape}, columns={list(final_df.columns)}")
            
            if final_df.isnull().values.any():
                logging.warning(f"Data masih mengandung NaN setelah imputasi pada {source}")
                return None

            return final_df.values # Return numpy array

        except Exception as e:
            logging.error(f"DB Error {source}: {e}")
            return None

def _predict_task(source: str, app) -> Optional[List[float]]:
    """Fungsi worker thread untuk melakukan prediksi."""
    logging.info(f"Memulai LSTM prediction worker untuk sumber: {source}")
    predictor = WeatherPredictor()
    
    if not predictor.model or not predictor.scaler:
        logging.warning(f"Model atau scaler LSTM tidak tersedia; melewatkan prediksi untuk {source}.")
        return None

    # 1. Fetch & Clean Data
    raw_data = _fetch_cleaned_dataframe(source, app) # Shape (144, 9)
    if raw_data is None: return None

    try:
        logging.debug(f"Raw data shape for {source}: {raw_data.shape}")
        # 2. Scaling
        scaled_data = predictor.scaler.transform(raw_data)
        logging.debug(f"Scaled data sample (first row) for {source}: {scaled_data[0][:6].tolist()}")
        
        # 3. Reshape untuk LSTM (Batch, Steps, Features) -> (1, 144, 9)
        input_tensor = scaled_data.reshape(1, SEQUENCE_LENGTH, N_FEATURES)

        # 4. Prediksi
        # Output shape model adalah (1, 24) 
        pred_scaled = predictor.model.predict(input_tensor, verbose=0)
        logging.debug(f"Raw model output (scaled) for {source}: {pred_scaled.flatten().tolist()}")

        # 5. Inverse Scaling (Khusus Hujan)
        scale_val, min_val = predictor.get_rain_inverse_params()
        logging.info(f"Scaler inverse params for rain: scale={scale_val}, min={min_val}")
        
        # Rumus Inverse Sklearn MinMaxScaler: (X_scaled - min_) / scale_
        pred_mm = (pred_scaled - min_val) / scale_val
        
        # Bersihkan nilai (tidak boleh negatif) dan bulatkan
        pred_final = np.maximum(pred_mm, 0.0).flatten().tolist()
        final_rounded = [round(x, 2) for x in pred_final]
        logging.info(f"LSTM prediction result for {source}: {final_rounded}")
        return final_rounded

    except Exception as e:
        logging.error(f"Prediction logic error {source}: {e}")
        return None

def run_parallel_lstm_predictions() -> Dict[str, Optional[List[float]]]:
    results = {'ecowitt': None, 'wunderground': None}
    try:
        app_obj = current_app._get_current_object()
    except:
        return results

    WeatherPredictor() # Init singleton di main thread

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_predict_task, src, app_obj): src 
            for src in ['ecowitt', 'wunderground']
        }
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    
    return results


def run_lstm_for_source(source: str, app) -> Optional[List[float]]:
    """Public helper to run LSTM prediction for a single source under given Flask app.
    Returns prediction list or None.
    """
    try:
        return _predict_task(source, app)
    except Exception as e:
        logging.error(f"run_lstm_for_source error for {source}: {e}")
        return None