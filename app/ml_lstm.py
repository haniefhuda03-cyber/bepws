import os
import math
import logging
import threading
import numpy as np
import pandas as pd  # Disarankan menggunakan Pandas untuk imputation
from datetime import timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, List

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
            
            # Ambil sedikit lebih banyak dari 144 untuk buffer imputasi
            rows = db.session.query(ModelClass)\
                .order_by(ModelClass.created_at.desc())\
                .limit(SEQUENCE_LENGTH + 20)\
                .all()
            
            if len(rows) < SEQUENCE_LENGTH:
                return None
            
            rows.reverse() # Urutkan kronologis (Lama -> Baru)

            # Konversi ke List of Dicts agar mudah jadi DataFrame
            data = []
            for r in rows:
                if source == 'wunderground':
                    solar = (float(r.solar_radiation) * WM2_TO_LUX) if r.solar_radiation is not None else 0.0
                    item = {
                        'suhu': float(r.temperature) if r.temperature is not None else np.nan,
                        'kelembaban': float(r.humidity) if r.humidity is not None else np.nan,
                        'kecepatan_angin': float(r.wind_speed) if r.wind_speed is not None else 0.0,
                        'arah_angin': float(r.wind_direction) if r.wind_direction is not None else 0.0,
                        'tekanan_udara': float(r.pressure) if r.pressure is not None else np.nan,
                        'intensitas_hujan': float(r.precipitation_rate) if r.precipitation_rate is not None else 0.0,
                        'intensitas_cahaya': solar,
                        'req_time': r.request_time
                    }
                else: # ecowitt
                    item = {
                        'suhu': float(r.temperature_main_outdoor) if r.temperature_main_outdoor is not None else np.nan,
                        'kelembaban': float(r.humidity_outdoor) if r.humidity_outdoor is not None else np.nan,
                        'kecepatan_angin': float(r.wind_speed) if r.wind_speed is not None else 0.0,
                        'arah_angin': float(r.wind_direction) if r.wind_direction is not None else 0.0,
                        'tekanan_udara': float(r.pressure_relative) if r.pressure_relative is not None else np.nan,
                        'intensitas_hujan': float(r.rain_rate) if r.rain_rate is not None else 0.0,
                        'intensitas_cahaya': float(r.solar_irradiance) if r.solar_irradiance is not None else 0.0,
                        'req_time': r.request_time
                    }
                data.append(item)

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
            
            if final_df.isnull().values.any():
                logging.warning(f"Data masih mengandung NaN setelah imputasi pada {source}")
                return None

            return final_df.values # Return numpy array

        except Exception as e:
            logging.error(f"DB Error {source}: {e}")
            return None

def _predict_task(source: str, app) -> Optional[List[float]]:
    """Fungsi worker thread untuk melakukan prediksi."""
    predictor = WeatherPredictor()
    
    if not predictor.model or not predictor.scaler: return None

    # 1. Fetch & Clean Data
    raw_data = _fetch_cleaned_dataframe(source, app) # Shape (144, 9)
    if raw_data is None: return None

    try:
        # 2. Scaling
        scaled_data = predictor.scaler.transform(raw_data)
        
        # 3. Reshape untuk LSTM (Batch, Steps, Features) -> (1, 144, 9)
        input_tensor = scaled_data.reshape(1, SEQUENCE_LENGTH, N_FEATURES)

        # 4. Prediksi
        # Output shape model adalah (1, 24) 
        pred_scaled = predictor.model.predict(input_tensor, verbose=0)

        # 5. Inverse Scaling (Khusus Hujan)
        scale_val, min_val = predictor.get_rain_inverse_params()
        
        # Rumus Inverse Sklearn MinMaxScaler: (X_scaled - min_) / scale_
        pred_mm = (pred_scaled - min_val) / scale_val
        
        # Bersihkan nilai (tidak boleh negatif) dan bulatkan
        pred_final = np.maximum(pred_mm, 0.0).flatten().tolist()
        return [round(x, 2) for x in pred_final]

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