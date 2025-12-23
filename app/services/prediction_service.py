"""
Prediction Service dengan Layering Architecture
================================================
Service layer untuk menangani prediksi cuaca menggunakan:
- XGBoost untuk klasifikasi arah hujan
- LSTM untuk prediksi intensitas hujan 24 jam ke depan

Fitur:
- Singleton Model Loading: Model dimuat sekali saat aplikasi start
- Smart Interpolation: Resampling data hanya jika ada data bolong
- Sequential Pipeline: Proses Ecowitt -> Wunderground -> Save dalam satu transaksi
"""

import os
import math
import logging
import threading
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple, Any
from sqlalchemy import func

# Flask & DB Imports
from flask import current_app
from .. import db
from ..models import (
    WeatherLogEcowitt,
    WeatherLogWunderground,
    PredictionLog,
    Model as ModelMeta,
)

# =====================================================================
# KONFIGURASI PATH & KONSTANTA
# =====================================================================
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
XGBOOST_MODEL_PATH = os.path.join(BASE_DIR, 'ml_models', 'model_prediksi_hujan_darimana_XGBoost.joblib')
LSTM_MODEL_PATH = os.path.join(BASE_DIR, 'ml_models', 'model_lstm_regresi_telkom.keras')
SCALER_PATH = os.path.join(BASE_DIR, 'ml_models', 'scalerFIT_split.joblib')

# Konstanta Model
SEQUENCE_LENGTH = 144       # 144 data points = 12 jam (5 menit interval)
PREDICTION_STEPS = 24       # Output: 24 timestep ke depan (24 jam)
N_FEATURES = 9              # Jumlah fitur sesuai scaler
WM2_TO_LUX = 126.7          # Konversi estimasi radiasi matahari ke lux
RAIN_FEATURE_INDEX = 5      # Index kolom 'intensitas_hujan' pada scaler
DATA_INTERVAL_MINUTES = 5   # Interval waktu antar data point

# Mapping label XGBoost
LABEL_MAP = {
    0: 'Cerah / Berawan',
    1: 'Berpotensi Hujan dari Arah Utara',
    2: 'Berpotensi Hujan dari Arah Timur Laut',
    3: 'Berpotensi Hujan dari Arah Timur',
    4: 'Berpotensi Hujan dari Arah Tenggara',
    5: 'Berpotensi Hujan dari Arah Selatan',
    6: 'Berpotensi Hujan dari Arah Barat Daya',
    7: 'Berpotensi Hujan dari Arah Barat',
    8: 'Berpotensi Hujan dari Arah Barat Laut'
}

XGBOOST_REQUIRED_FEATURES = [
    'suhu', 'kelembaban', 'kecepatan_angin', 
    'arah_angin', 'tekanan_udara', 'intensitas_hujan'
]

LSTM_FEATURE_ORDER = [
    'suhu', 'kelembaban', 'kecepatan_angin', 'arah_angin', 
    'tekanan_udara', 'intensitas_hujan', 'intensitas_cahaya', 
    'hour_sin', 'hour_cos'
]

# =====================================================================
# SINGLETON MODEL LOADER
# =====================================================================

class ModelLoader:
    """
    Singleton Class Thread-Safe untuk mengelola Model ML dan Scaler.
    Memuat model hanya SATU KALI saat aplikasi start.
    """
    _instance = None
    _lock = threading.Lock()
    
    # Model instances
    xgboost_model = None
    lstm_model = None
    scaler = None
    
    # Status flags
    _initialized = False
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ModelLoader, cls).__new__(cls)
        return cls._instance
    
    def initialize(self):
        """Memuat semua model dan scaler ke memori. Dipanggil sekali saat app start."""
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            self._load_xgboost()
            self._load_scaler()
            self._load_lstm()
            self._initialized = True
            logging.info("ModelLoader: Semua model berhasil dimuat ke memori.")
    
    def _load_xgboost(self):
        """Load model XGBoost."""
        try:
            import joblib
            if os.path.exists(XGBOOST_MODEL_PATH):
                self.xgboost_model = joblib.load(XGBOOST_MODEL_PATH)
                logging.info(f"XGBoost model berhasil dimuat dari {XGBOOST_MODEL_PATH}")
            else:
                logging.warning(f"XGBoost model tidak ditemukan: {XGBOOST_MODEL_PATH}")
        except Exception as e:
            logging.error(f"Error loading XGBoost model: {e}")
    
    def _load_scaler(self):
        """Load scaler untuk LSTM."""
        try:
            import joblib
            if os.path.exists(SCALER_PATH):
                self.scaler = joblib.load(SCALER_PATH)
                logging.info(f"Scaler berhasil dimuat dari {SCALER_PATH}")
                # Validasi jumlah fitur
                if hasattr(self.scaler, 'n_features_in_') and self.scaler.n_features_in_ != N_FEATURES:
                    logging.warning(f"Scaler mismatch! Harapan {N_FEATURES}, didapat {self.scaler.n_features_in_}")
            else:
                logging.warning(f"Scaler tidak ditemukan: {SCALER_PATH}")
        except Exception as e:
            logging.error(f"Error loading scaler: {e}")
    
    def _load_lstm(self):
        """Load model LSTM."""
        try:
            import tensorflow as tf
            
            # Custom loss function untuk model Keras
            @tf.keras.utils.register_keras_serializable()
            def weighted_masked_regression_loss(y_true, y_pred):
                RAIN_EVENT_WEIGHT = 10.0
                NO_RAIN_WEIGHT = 1.0
                squared_error = tf.square(y_true - y_pred)
                is_raining_mask = tf.cast(tf.greater(y_true, 0), tf.float32)
                weight = (is_raining_mask * (RAIN_EVENT_WEIGHT - NO_RAIN_WEIGHT) + NO_RAIN_WEIGHT)
                weighted_square_error = squared_error * weight
                return tf.reduce_mean(weighted_square_error)
            
            if os.path.exists(LSTM_MODEL_PATH):
                self.lstm_model = tf.keras.models.load_model(
                    LSTM_MODEL_PATH,
                    custom_objects={'weighted_masked_regression_loss': weighted_masked_regression_loss},
                    compile=False
                )
                logging.info(f"LSTM model berhasil dimuat dari {LSTM_MODEL_PATH}")
            else:
                logging.warning(f"LSTM model tidak ditemukan: {LSTM_MODEL_PATH}")
        except ImportError:
            logging.warning("TensorFlow tidak terinstall, LSTM tidak akan tersedia.")
        except Exception as e:
            logging.error(f"Error loading LSTM model: {e}")
    
    def get_rain_inverse_params(self) -> Tuple[Optional[float], Optional[float]]:
        """Mengambil parameter untuk inverse scaling hasil prediksi hujan."""
        if self.scaler is None:
            return None, None
        try:
            scale = self.scaler.scale_[RAIN_FEATURE_INDEX]
            min_val = self.scaler.min_[RAIN_FEATURE_INDEX]
            return scale, min_val
        except Exception:
            return None, None


# Global singleton instance
_model_loader: Optional[ModelLoader] = None


def get_model_loader() -> ModelLoader:
    """Mendapatkan instance ModelLoader (singleton)."""
    global _model_loader
    if _model_loader is None:
        _model_loader = ModelLoader()
    return _model_loader


def initialize_models():
    """Inisialisasi semua model. Panggil saat aplikasi start."""
    loader = get_model_loader()
    loader.initialize()


# =====================================================================
# HELPER FUNCTIONS
# =====================================================================

def _calculate_hour_components(request_time: datetime) -> Tuple[float, float]:
    """Menghitung komponen cyclical waktu (Sin/Cos) untuk WIB."""
    if request_time is None:
        return 0.0, 0.0
    if request_time.tzinfo is None:
        request_time = request_time.replace(tzinfo=timezone.utc)
    
    # Konversi ke WIB (UTC+7)
    wib = request_time.astimezone(timezone(timedelta(hours=7)))
    hour_decimal = wib.hour + (wib.minute / 60.0)
    angle = 2.0 * math.pi * (hour_decimal / 24.0)
    return math.sin(angle), math.cos(angle)


def _check_data_needs_interpolation(timestamps: List[datetime]) -> bool:
    """
    Cek apakah data memerlukan interpolasi.
    Return True jika ada data bolong atau interval tidak pas 5 menit.
    """
    if len(timestamps) < 2:
        return False
    
    for i in range(1, len(timestamps)):
        diff = (timestamps[i] - timestamps[i-1]).total_seconds()
        expected = DATA_INTERVAL_MINUTES * 60  # 300 detik
        # Toleransi 30 detik
        if abs(diff - expected) > 30:
            return True
    return False


def _resample_and_interpolate(df: pd.DataFrame, timestamp_col: str = 'timestamp') -> pd.DataFrame:
    """
    Resample data ke interval 5 menit dan interpolasi nilai yang hilang.
    Menggunakan Pandas untuk interpolasi linear.
    """
    if df.empty:
        return df
    
    # Set timestamp sebagai index
    df = df.copy()
    df[timestamp_col] = pd.to_datetime(df[timestamp_col])
    df = df.set_index(timestamp_col)
    
    # Resample ke 5 menit dan interpolasi
    df_resampled = df.resample('5min').mean()
    
    # Interpolasi linear untuk mengisi NaN
    df_interpolated = df_resampled.interpolate(method='linear', limit_direction='both')
    
    # Forward fill dan backward fill untuk sisa NaN
    df_interpolated = df_interpolated.ffill().bfill()
    
    # Reset index
    df_interpolated = df_interpolated.reset_index()
    
    return df_interpolated


# =====================================================================
# DATA FETCHING FUNCTIONS
# =====================================================================

def _get_latest_weather_data(source: str) -> Optional[Any]:
    """Ambil 1 data cuaca terkini untuk XGBoost."""
    try:
        ModelClass = WeatherLogEcowitt if source == 'ecowitt' else WeatherLogWunderground
        latest = db.session.query(ModelClass).order_by(ModelClass.id.desc()).first()
        return latest
    except Exception as e:
        logging.error(f"Error fetching latest {source} data: {e}")
        return None


def _prepare_xgboost_features(weather_log, source: str) -> Optional[Dict[str, float]]:
    """Menyiapkan fitur untuk prediksi XGBoost."""
    if weather_log is None:
        return None
    
    try:
        if source == 'ecowitt':
            features = {
                'suhu': float(weather_log.temperature_main_outdoor) if weather_log.temperature_main_outdoor is not None else None,
                'kelembaban': float(weather_log.humidity_outdoor) if weather_log.humidity_outdoor is not None else None,
                'kecepatan_angin': float(weather_log.wind_speed) if weather_log.wind_speed is not None else None,
                'arah_angin': float(weather_log.wind_direction) if weather_log.wind_direction is not None else None,
                'tekanan_udara': float(weather_log.pressure_relative) if weather_log.pressure_relative is not None else None,
                'intensitas_hujan': float(weather_log.rain_rate) if weather_log.rain_rate is not None else 0.0,
            }
        else:  # wunderground
            features = {
                'suhu': float(weather_log.temperature) if weather_log.temperature is not None else None,
                'kelembaban': float(weather_log.humidity) if weather_log.humidity is not None else None,
                'kecepatan_angin': float(weather_log.wind_speed) if weather_log.wind_speed is not None else None,
                'arah_angin': float(weather_log.wind_direction) if weather_log.wind_direction is not None else None,
                'tekanan_udara': float(weather_log.pressure) if weather_log.pressure is not None else None,
                'intensitas_hujan': float(weather_log.precipitation_rate) if weather_log.precipitation_rate is not None else 0.0,
            }
        
        # Validasi semua fitur ada
        if any(v is None for k, v in features.items() if k != 'intensitas_hujan'):
            logging.warning(f"Missing features for {source}: {features}")
            return None
        
        return features
    except Exception as e:
        logging.error(f"Error preparing XGBoost features for {source}: {e}")
        return None


def _fetch_lstm_data(source: str) -> Optional[pd.DataFrame]:
    """
    Ambil 144 data point terakhir (12 jam) untuk LSTM.
    Cek interval waktu dan lakukan interpolasi jika diperlukan.
    """
    try:
        ModelClass = WeatherLogEcowitt if source == 'ecowitt' else WeatherLogWunderground
        
        # Ambil data lebih banyak untuk antisipasi gap
        buffer_size = SEQUENCE_LENGTH + 50  # Lebih banyak untuk handle gaps
        
        rows = db.session.query(ModelClass)\
            .order_by(ModelClass.request_time.desc())\
            .limit(buffer_size)\
            .all()
        
        if not rows or len(rows) < SEQUENCE_LENGTH:
            logging.warning(f"Tidak cukup data untuk LSTM {source}: {len(rows) if rows else 0}/{SEQUENCE_LENGTH}")
            return None
        
        # Reverse agar urut dari lama ke baru
        rows = list(reversed(rows))
        
        # Konversi ke DataFrame
        data_list = []
        timestamps = []
        
        for row in rows:
            ts = row.request_time
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            
            timestamps.append(ts)
            
            if source == 'wunderground':
                solar = (float(row.solar_radiation) * WM2_TO_LUX) if row.solar_radiation is not None else 0.0
                data_list.append({
                    'timestamp': ts,
                    'suhu': float(row.temperature) if row.temperature is not None else np.nan,
                    'kelembaban': float(row.humidity) if row.humidity is not None else np.nan,
                    'kecepatan_angin': float(row.wind_speed) if row.wind_speed is not None else 0.0,
                    'arah_angin': float(row.wind_direction) if row.wind_direction is not None else 0.0,
                    'tekanan_udara': float(row.pressure) if row.pressure is not None else np.nan,
                    'intensitas_hujan': float(row.precipitation_rate) if row.precipitation_rate is not None else 0.0,
                    'intensitas_cahaya': solar,
                })
            else:  # ecowitt
                data_list.append({
                    'timestamp': ts,
                    'suhu': float(row.temperature_main_outdoor) if row.temperature_main_outdoor is not None else np.nan,
                    'kelembaban': float(row.humidity_outdoor) if row.humidity_outdoor is not None else np.nan,
                    'kecepatan_angin': float(row.wind_speed) if row.wind_speed is not None else 0.0,
                    'arah_angin': float(row.wind_direction) if row.wind_direction is not None else 0.0,
                    'tekanan_udara': float(row.pressure_relative) if row.pressure_relative is not None else np.nan,
                    'intensitas_hujan': float(row.rain_rate) if row.rain_rate is not None else 0.0,
                    'intensitas_cahaya': float(row.solar_irradiance) if row.solar_irradiance is not None else 0.0,
                })
        
        if len(data_list) < SEQUENCE_LENGTH:
            logging.warning(f"Data tidak cukup setelah parsing untuk {source}")
            return None
        
        df = pd.DataFrame(data_list)
        
        # Cek apakah perlu interpolasi
        needs_interpolation = _check_data_needs_interpolation(timestamps)
        
        if needs_interpolation:
            logging.info(f"Data {source} memerlukan interpolasi karena ada gap")
            df = _resample_and_interpolate(df, 'timestamp')
        else:
            logging.info(f"Data {source} sudah rapi, skip interpolasi")
        
        # Ambil 144 data terakhir
        if len(df) > SEQUENCE_LENGTH:
            df = df.tail(SEQUENCE_LENGTH)
        
        if len(df) < SEQUENCE_LENGTH:
            logging.warning(f"Data kurang dari {SEQUENCE_LENGTH} setelah processing untuk {source}")
            return None
        
        # Imputation untuk NaN yang tersisa
        df = df.ffill().bfill()
        
        # Hitung time features (Sin/Cos)
        if 'timestamp' in df.columns:
            sin_cos = df['timestamp'].apply(lambda x: pd.Series(_calculate_hour_components(x)))
            df['hour_sin'] = sin_cos[0]
            df['hour_cos'] = sin_cos[1]
        else:
            df['hour_sin'] = 0.0
            df['hour_cos'] = 0.0
        
        # Urutkan kolom sesuai scaler
        feature_cols = [c for c in LSTM_FEATURE_ORDER if c in df.columns]
        
        if len(feature_cols) != N_FEATURES:
            logging.error(f"Feature mismatch untuk {source}: expected {N_FEATURES}, got {len(feature_cols)}")
            return None
        
        final_df = df[feature_cols]
        
        # Cek NaN
        if final_df.isnull().values.any():
            logging.warning(f"Data masih mengandung NaN setelah imputasi pada {source}")
            final_df = final_df.ffill().bfill().fillna(0)
        
        return final_df
        
    except Exception as e:
        logging.error(f"Error fetching LSTM data for {source}: {e}")
        return None


# =====================================================================
# PREDICTION FUNCTIONS
# =====================================================================

def predict_xgboost(features: Dict[str, float]) -> Optional[int]:
    """Jalankan prediksi XGBoost dan return class label (int)."""
    loader = get_model_loader()
    
    if loader.xgboost_model is None:
        logging.warning("XGBoost model tidak tersedia")
        return None
    
    try:
        # Validasi fitur
        if not all(f in features for f in XGBOOST_REQUIRED_FEATURES):
            missing = [f for f in XGBOOST_REQUIRED_FEATURES if f not in features]
            logging.error(f"Missing XGBoost features: {missing}")
            return None
        
        # Buat DataFrame
        input_df = pd.DataFrame([features], columns=XGBOOST_REQUIRED_FEATURES)
        input_df = input_df.astype(float)
        
        # Prediksi
        prediction_raw = loader.xgboost_model.predict(input_df)
        result = int(prediction_raw[0])
        
        logging.info(f"XGBoost prediction: {result} ({LABEL_MAP.get(result, 'Unknown')})")
        return result
        
    except Exception as e:
        logging.error(f"Error in XGBoost prediction: {e}")
        return None


def predict_lstm(data: pd.DataFrame) -> Optional[List[float]]:
    """Jalankan prediksi LSTM dan return array 24 nilai (intensitas hujan per jam)."""
    loader = get_model_loader()
    
    if loader.lstm_model is None or loader.scaler is None:
        logging.warning("LSTM model atau scaler tidak tersedia")
        return None
    
    try:
        # Konversi ke numpy array
        raw_data = data.values
        
        if raw_data.shape != (SEQUENCE_LENGTH, N_FEATURES):
            logging.error(f"Invalid data shape: {raw_data.shape}, expected ({SEQUENCE_LENGTH}, {N_FEATURES})")
            return None
        
        # Scaling
        scaled_data = loader.scaler.transform(raw_data)
        
        # Reshape untuk LSTM: (batch, steps, features) -> (1, 144, 9)
        input_tensor = scaled_data.reshape(1, SEQUENCE_LENGTH, N_FEATURES)
        
        # Prediksi
        pred_scaled = loader.lstm_model.predict(input_tensor, verbose=0)
        
        # Inverse scaling khusus untuk fitur hujan
        scale_val, min_val = loader.get_rain_inverse_params()
        if scale_val is None or min_val is None:
            logging.warning("Tidak bisa melakukan inverse scaling")
            return pred_scaled.flatten().tolist()
        
        # Rumus Inverse MinMaxScaler: (X_scaled - min_) / scale_
        pred_mm = (pred_scaled - min_val) / scale_val
        
        # Bersihkan nilai negatif dan bulatkan
        pred_final = np.maximum(pred_mm, 0.0).flatten().tolist()
        final_rounded = [round(x, 2) for x in pred_final]
        
        logging.info(f"LSTM prediction (24 hours): {final_rounded[:5]}... (showing first 5)")
        return final_rounded
        
    except Exception as e:
        logging.error(f"Error in LSTM prediction: {e}")
        return None


# =====================================================================
# MAIN PREDICTION PIPELINE
# =====================================================================

def run_prediction_pipeline() -> Optional[PredictionLog]:
    """
    Menjalankan pipeline prediksi lengkap:
    1. Step A (Ecowitt): XGBoost + LSTM
    2. Step B (Wunderground): XGBoost + LSTM
    3. Step C (Save): Simpan ke satu baris PredictionLog
    
    Returns PredictionLog yang tersimpan, atau None jika gagal.
    """
    logging.info("="*60)
    logging.info("Memulai Prediction Pipeline")
    logging.info("="*60)
    
    # Inisialisasi model jika belum
    initialize_models()
    
    # Container untuk hasil sementara
    results = {
        'ecowitt_xgboost': None,
        'ecowitt_lstm': None,
        'ecowitt_weather_id': None,
        'wunderground_xgboost': None,
        'wunderground_lstm': None,
        'wunderground_weather_id': None,
    }
    
    # -------------------------
    # Step A: Ecowitt
    # -------------------------
    logging.info("-" * 40)
    logging.info("Step A: Processing Ecowitt")
    logging.info("-" * 40)
    
    eco_weather = _get_latest_weather_data('ecowitt')
    if eco_weather:
        results['ecowitt_weather_id'] = eco_weather.id
        
        # XGBoost
        eco_features = _prepare_xgboost_features(eco_weather, 'ecowitt')
        if eco_features:
            results['ecowitt_xgboost'] = predict_xgboost(eco_features)
        
        # LSTM
        eco_lstm_data = _fetch_lstm_data('ecowitt')
        if eco_lstm_data is not None:
            results['ecowitt_lstm'] = predict_lstm(eco_lstm_data)
    else:
        logging.warning("Tidak ada data Ecowitt tersedia")
    
    # -------------------------
    # Step B: Wunderground
    # -------------------------
    logging.info("-" * 40)
    logging.info("Step B: Processing Wunderground")
    logging.info("-" * 40)
    
    wu_weather = _get_latest_weather_data('wunderground')
    if wu_weather:
        results['wunderground_weather_id'] = wu_weather.id
        
        # XGBoost
        wu_features = _prepare_xgboost_features(wu_weather, 'wunderground')
        if wu_features:
            results['wunderground_xgboost'] = predict_xgboost(wu_features)
        
        # LSTM
        wu_lstm_data = _fetch_lstm_data('wunderground')
        if wu_lstm_data is not None:
            results['wunderground_lstm'] = predict_lstm(wu_lstm_data)
    else:
        logging.warning("Tidak ada data Wunderground tersedia")
    
    # -------------------------
    # Step C: Save to Database
    # -------------------------
    logging.info("-" * 40)
    logging.info("Step C: Saving to Database")
    logging.info("-" * 40)
    
    # Cek apakah ada data untuk disimpan
    has_ecowitt = results['ecowitt_weather_id'] is not None
    has_wunderground = results['wunderground_weather_id'] is not None
    
    if not has_ecowitt and not has_wunderground:
        logging.warning("Tidak ada data dari kedua sumber. Pipeline dibatalkan.")
        return None
    
    # Ambil model metadata dari database
    xgboost_model = db.session.query(ModelMeta).filter(
        ModelMeta.name.ilike('%xgboost%')
    ).first()
    
    lstm_model = db.session.query(ModelMeta).filter(
        ModelMeta.name.ilike('%lstm%')
    ).first()
    
    # Jika tidak ada model spesifik, gunakan model pertama
    if not xgboost_model:
        xgboost_model = db.session.query(ModelMeta).first()
    if not lstm_model:
        lstm_model = db.session.query(ModelMeta).first()
    
    try:
        # Buat PredictionLog baru dengan 10 kolom
        prediction_log = PredictionLog(
            weather_log_ecowitt_id=results['ecowitt_weather_id'],
            weather_log_wunderground_id=results['wunderground_weather_id'],
            xgboost_model_id=xgboost_model.id if xgboost_model else None,
            lstm_model_id=lstm_model.id if lstm_model else None,
            ecowitt_predict_result=results['ecowitt_xgboost'],
            wunderground_predict_result=results['wunderground_xgboost'],
            ecowitt_predict_data=results['ecowitt_lstm'],
            wunderground_predict_data=results['wunderground_lstm'],
        )
        
        db.session.add(prediction_log)
        db.session.commit()
        
        logging.info(f"PredictionLog berhasil disimpan dengan ID: {prediction_log.id}")
        logging.info(f"  - Ecowitt XGBoost: {results['ecowitt_xgboost']}")
        logging.info(f"  - Ecowitt LSTM: {len(results['ecowitt_lstm']) if results['ecowitt_lstm'] else 0} values")
        logging.info(f"  - Wunderground XGBoost: {results['wunderground_xgboost']}")
        logging.info(f"  - Wunderground LSTM: {len(results['wunderground_lstm']) if results['wunderground_lstm'] else 0} values")
        logging.info("="*60)
        
        return prediction_log
        
    except Exception as e:
        logging.error(f"Error saving PredictionLog: {e}")
        db.session.rollback()
        return None


def get_label_name(class_id: int) -> str:
    """
    Mendapatkan nama label dari class ID XGBoost.
    Prioritas: Database -> Fallback ke LABEL_MAP hardcoded.
    
    Note: XGBoost mengembalikan class_id 0-8, tapi di database label.id dimulai dari 1.
    Karena XGBoost dilatih dengan class_id 0-8 (sesuai LABEL_MAP), kita gunakan class_id + 1
    untuk mengambil dari database (karena ID database dimulai dari 1).
    """
    from ..models import Label
    
    try:
        # XGBoost class_id 0 = label.id 1, class_id 1 = label.id 2, dst.
        # Kita query berdasarkan ID = class_id + 1
        label = Label.query.filter_by(id=class_id + 1).first()
        if label:
            return label.name
    except Exception:
        pass
    
    # Fallback ke hardcoded LABEL_MAP
    return LABEL_MAP.get(class_id, 'Unknown')


def get_label_from_db(class_id: int) -> dict:
    """
    Mendapatkan label lengkap dari database.
    Returns dict dengan id, name, dan class_id (original dari XGBoost).
    """
    from ..models import Label
    
    try:
        # class_id dari XGBoost (0-8), label.id di database (1-9)
        label = Label.query.filter_by(id=class_id + 1).first()
        if label:
            return {
                'label_id': label.id,
                'class_id': class_id,  # Original class dari XGBoost
                'name': label.name,
            }
    except Exception:
        pass
    
    # Fallback ke hardcoded
    return {
        'label_id': None,
        'class_id': class_id,
        'name': LABEL_MAP.get(class_id, 'Unknown'),
    }


def get_model_info(model_type: str) -> dict:
    """
    Mendapatkan informasi model dari database.
    model_type: 'xgboost' atau 'lstm'
    """
    from ..models import Model as ModelMeta
    
    try:
        model = ModelMeta.query.filter(
            ModelMeta.name.ilike(f'%{model_type}%')
        ).first()
        
        if model:
            return {
                'id': model.id,
                'name': model.name,
                'range_prediction': model.range_prediction,
            }
    except Exception:
        pass
    
    return {
        'id': None,
        'name': f'default_{model_type}',
        'range_prediction': None,
    }
