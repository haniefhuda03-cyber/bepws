import os
import math
import logging
import numpy as np
from datetime import timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, List, Any

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
SEQUENCE_LENGTH = 144       # 12 jam data (interval 5 menit)
N_FEATURES = 9              # Jumlah fitur sesuai scaler
WM2_TO_LUX = 126.7          # Konversi estimasi Radiasi
RAIN_FEATURE_INDEX = 5      # Index kolom 'intensitas_hujan' pada scaler (urutan ke-6)


# --- CUSTOM LOSS FUNCTION ---
# Wajib ada agar model Keras bisa di-load dengan benar
def weighted_masked_regression_loss(y_true, y_pred):
    if tf is None:
        return 0
    RAIN_EVENT_WEIGHT = 10.0
    NO_RAIN_WEIGHT = 1.0
    squared_error = tf.square(y_true - y_pred)
    is_raining_mask = tf.cast(tf.greater(y_true, 0), tf.float32)
    weight = (is_raining_mask * (RAIN_EVENT_WEIGHT - NO_RAIN_WEIGHT) + NO_RAIN_WEIGHT)
    weighted_square_error = squared_error * weight
    return tf.reduce_mean(weighted_square_error)


class WeatherPredictor:
    """
    Singleton class untuk mengelola Model ML dan Scaler.
    Memuat model hanya sekali untuk efisiensi memori.
    """
    _instance = None
    model = None
    scaler = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WeatherPredictor, cls).__new__(cls)
            cls._instance._load_resources()
        return cls._instance

    def _load_resources(self):
        """Memuat scaler dan model ke memori."""
        if not tf or not joblib:
            logging.error("Library TensorFlow atau Joblib tidak terinstall.")
            return

        # 1. Load Scaler
        try:
            if os.path.exists(SCALER_PATH):
                self.scaler = joblib.load(SCALER_PATH)
                logging.info(f"Scaler berhasil dimuat dari {SCALER_PATH}")
            else:
                logging.critical(f"Scaler tidak ditemukan di {SCALER_PATH}. Prediksi tidak akan akurat!")
        except Exception as e:
            logging.error(f"Gagal memuat scaler: {e}")

        # 2. Load Model
        try:
            if os.path.exists(MODEL_PATH):
                self.model = tf.keras.models.load_model(
                    MODEL_PATH, 
                    custom_objects={'weighted_masked_regression_loss': weighted_masked_regression_loss},
                    compile=False
                )
                logging.info(f"Model LSTM berhasil dimuat dari {MODEL_PATH}")
            else:
                logging.critical(f"Model tidak ditemukan di {MODEL_PATH}")
        except Exception as e:
            logging.error(f"Gagal memuat model: {e}")

    def get_scaler_params_for_rain(self):
        """Mengambil parameter scale_ dan min_ khusus untuk fitur hujan (index 5)"""
        if self.scaler is None: 
            return None, None
        
        # MinMaxScaler formula: X_std = (X - X.min(axis=0)) / (X.max(axis=0) - X.min(axis=0))
        # Sklearn menyimpan: scale_ = 1 / (max - min), min_ = -min * scale_
        # Inverse: X = (X_scaled - min_) / scale_
        return self.scaler.scale_[RAIN_FEATURE_INDEX], self.scaler.min_[RAIN_FEATURE_INDEX]


# --- HELPER FUNCTIONS ---

def _calculate_hour_components(request_time):
    """Menghitung komponen cyclical waktu (Sin/Cos)."""
    if request_time is None:
        return 0.0, 0.0
    
    if request_time.tzinfo is None:
        request_time = request_time.replace(tzinfo=timezone.utc)
    
    # Convert ke WIB (UTC+7)
    wib = request_time.astimezone(timezone(timedelta(hours=7)))
    
    hour_decimal = wib.hour + (wib.minute / 60.0) + (wib.second / 3600.0)
    angle = 2.0 * math.pi * (hour_decimal / 24.0)
    return math.sin(angle), math.cos(angle)


def _row_to_features(row, source_type: str) -> Optional[List[float]]:
    """
    Ekstraksi fitur raw dari row database.
    Urutan HARUS: [suhu, hum, wind_spd, wind_dir, press, rain, solar, h_sin, h_cos]
    """
    try:
        # Helper untuk handle nilai None (Default ke 0.0)
        def val(v): return float(v) if v is not None else 0.0

        # Tentukan mapping atribut berdasarkan tipe source
        if source_type == 'wunderground':
            temp = val(row.temperature)
            hum = val(row.humidity)
            ws = val(row.wind_speed)
            wd = val(row.wind_direction)
            press = val(row.pressure)
            rain = val(row.precipitation_rate)
            # Wunderground (W/m2) convert ke Lux
            solar = val(row.solar_radiation) * WM2_TO_LUX 
            req_time = row.request_time
        else: # ecowitt
            temp = val(row.temperature_main_outdoor)
            hum = val(row.humidity_outdoor)
            ws = val(row.wind_speed)
            wd = val(row.wind_direction)
            press = val(row.pressure_relative)
            rain = val(row.rain_rate)
            # Ecowitt sudah dalam Lux
            solar = val(row.solar_irradiance)
            req_time = row.request_time

        h_sin, h_cos = _calculate_hour_components(req_time)

        return [temp, hum, ws, wd, press, rain, solar, h_sin, h_cos]
    except Exception as e:
        logging.warning(f"Error parsing row features: {e}")
        return None


def _fetch_data_sequence(source: str, app) -> Optional[np.ndarray]:
    """Mengambil 144 data terakhir dari DB."""
    with app.app_context():
        try:
            ModelClass = WeatherLogEcowitt if source == 'ecowitt' else WeatherLogWunderground
            
            # Ambil n terakhir descending (terbaru diatas), lalu reverse biar kronologis
            rows = db.session.query(ModelClass)\
                .order_by(ModelClass.created_at.desc())\
                .limit(SEQUENCE_LENGTH)\
                .all()
            
            if len(rows) < SEQUENCE_LENGTH:
                logging.warning(f"[{source}] Data kurang (Hanya {len(rows)}/{SEQUENCE_LENGTH}).")
                return None
            
            # Ubah ke urutan kronologis (lama -> baru) untuk LSTM
            rows.reverse() 

            data_list = []
            for r in rows:
                feats = _row_to_features(r, source)
                if feats is None: return None
                data_list.append(feats)
            
            return np.array(data_list) # Shape (144, 9)
        except Exception as e:
            logging.error(f"Database error fetching {source}: {e}")
            return None


def _predict_task(source: str, app) -> Optional[List[float]]:
    """Fungsi worker thread untuk melakukan prediksi."""
    predictor = WeatherPredictor()
    
    if predictor.model is None or predictor.scaler is None:
        logging.error("Model/Scaler belum siap. Prediksi dibatalkan.")
        return None

    # 1. Fetch Data
    raw_data = _fetch_data_sequence(source, app)
    if raw_data is None:
        return None

    # 2. Preprocessing (Scaling)
    try:
        # Gunakan scaler yang SUDAH DILATIH. Jangan fit ulang!
        scaled_data = predictor.scaler.transform(raw_data)
        # Reshape ke (1, 144, 9) untuk input model LSTM
        input_tensor = scaled_data.reshape(1, SEQUENCE_LENGTH, N_FEATURES)
    except Exception as e:
        logging.error(f"Scaling error pada {source}: {e}")
        return None

    # 3. Inference
    try:
        # Prediksi (Output shape: 1, 24)
        prediction_scaled = predictor.model.predict(input_tensor, verbose=0)
        
        # 4. Inverse Scaling (PENTING!)
        # Kita perlu mengembalikan nilai prediksi hujan ke skala asli (mm/jam).
        # Ambil parameter scaling khusus untuk kolom hujan
        scale_val, min_val = predictor.get_scaler_params_for_rain()
        
        # Rumus Inverse: X_asli = (X_scaled - min_) / scale_
        prediction_raw = (prediction_scaled - min_val) / scale_val
        
        # Pastikan tidak ada nilai negatif (Hujan tidak mungkin negatif)
        prediction_final = np.maximum(prediction_raw, 0.0).flatten().tolist()
        
        # Rounding agar rapi (2 desimal)
        result_rounded = [round(val, 2) for val in prediction_final]
        
        logging.info(f"[{source}] Sukses memprediksi 24 titik data hujan.")
        return result_rounded

    except Exception as e:
        logging.error(f"Inference error pada {source}: {e}")
        return None


# --- PUBLIC FUNCTION ---

def run_parallel_lstm_predictions() -> Dict[str, Optional[List[float]]]:
    """Entry point utama untuk dijalankan oleh scheduler."""
    results = {'ecowitt': None, 'wunderground': None}
    
    # Dapatkan objek app asli untuk dipassing ke thread (karena db.session butuh app context)
    try:
        app_obj = current_app._get_current_object()
    except RuntimeError:
        logging.error("Fungsi ini harus dijalankan dalam Flask Application Context")
        return results

    # Inisialisasi model di main thread dulu agar thread-safe saat load pertama
    WeatherPredictor() 

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_predict_task, src, app_obj): src 
            for src in ['ecowitt', 'wunderground']
        }
        
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                results[src] = fut.result()
            except Exception as e:
                logging.error(f"Unhandled thread error {src}: {e}")
    
    return results