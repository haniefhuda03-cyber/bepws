"""
Prediction Service dengan Layering Architecture
================================================
Service layer untuk menangani prediksi cuaca menggunakan:
- XGBoost untuk klasifikasi arah hujan
- LSTM untuk prediksi intensitas hujan 24 jam ke depan

Fitur:
- Singleton Model Loading: Model dimuat sekali saat aplikasi start
- Smart Interpolation: Resampling data hanya jika ada data bolong
- Parallel Pipeline: 3 sumber diproses paralel, XGBoost->LSTM sekuensial per sumber
- Partial Save: Simpan hasil yang berhasil (XGBoost/LSTM/keduanya)
"""

import os
import math
import logging
import threading
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple, Any

# Flask & DB Imports
from flask import current_app
from .. import db
from sqlalchemy.orm import load_only
from ..models import (
    WeatherLogEcowitt,
    WeatherLogWunderground,
    WeatherLogConsole,
    PredictionLog,
    DataXGBoost,
    DataLSTM,
    XGBoostPredictionResult,
    LSTMPredictionResult,
    Model as ModelMeta,
    Label,
)
from ..common import helpers

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
RAIN_FEATURE_INDEX = 5      # Index kolom 'intensitas_hujan' pada scaler
DATA_INTERVAL_MINUTES = 5   # Interval waktu antar data point
MAX_INTERPOLATED_RATIO = 0.25  # Maks 25% data boleh hasil interpolasi
XGBOOST_FRESHNESS_SECONDS = 5 * 60  # dibawah 5 menit — data XGBoost harus segar

# Default values klimatologis Indonesia tropis untuk fallback fillna.
# Digunakan HANYA jika ffill+bfill gagal (seluruh kolom NaN).
# Nilai 0 pada suhu/tekanan akan menghasilkan outlier ekstrem pada scaler.
_SAFE_FILL_DEFAULTS = {
    'suhu': 27.0,              # ~rata-rata suhu Indonesia tropis (°C)
    'kelembaban': 75.0,        # ~rata-rata kelembaban relatif (%)
    'kecepatan_angin': 0.0,    # angin tenang, aman
    'arah_angin': 0.0,         # utara, acceptable default
    'tekanan_udara': 1010.0,   # ~rata-rata tekanan permukaan laut (hPa)
    'intensitas_hujan': 0.0,   # tidak hujan, aman
    'intensitas_cahaya': 0.0,  # gelap/malam, aman
}

# Thread safety: Lock untuk LSTM predict() — TF tidak menjamin thread-safety secara resmi
_lstm_predict_lock = threading.Lock()

# =====================================================================
# UNIT CONVERSION (Imperial -> Metric) untuk Console
# Hanya digunakan saat prediksi, TIDAK mengubah data di database
# =====================================================================

# ──────────────────────────────────────────────────────────
# Mapping label XGBoost — Single Source of Truth
# Jika label berubah, update juga di: app/db_seed.py (label_map_local)
# ──────────────────────────────────────────────────────────
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
# SOURCE RESULT CONTAINER
# =====================================================================

@dataclass
class SourceResult:
    """
    Container untuk hasil prediksi per sumber (thread-safe).
    
    Digunakan oleh _process_source() untuk menyimpan hasil XGBoost dan LSTM
    dari satu sumber data (console/ecowitt/wunderground).
    """
    source: str
    weather_id: Optional[int] = None
    xgboost: Optional[int] = None          # Class 0-8, None jika gagal
    lstm: Optional[List[float]] = None     # Array 24 float, None jika gagal
    lstm_ids: Optional[List[int]] = None   # 144 IDs yang digunakan LSTM
    xgboost_error: Optional[str] = None    # Error message jika XGBoost gagal
    lstm_error: Optional[str] = None       # Error message jika LSTM gagal

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
            import tensorflow as tf  # type: ignore[import-unresolved]
            
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
        """
        Mengambil parameter untuk inverse scaling hasil prediksi hujan.
        
        MinMaxScaler formula:
        - Scaling:   X_scaled = (X - data_min) / data_range = X * scale_ + min_
        - Inverse:   X = (X_scaled - min_) / scale_
        
        Untuk MinMaxScaler sklearn:
        - scale_ = 1 / (data_max - data_min)
        - min_ = -data_min / (data_max - data_min)
        
        Jadi inverse adalah: X = (X_scaled - min_) / scale_
        """
        if self.scaler is None:
            return None, None
        try:
            scale = self.scaler.scale_[RAIN_FEATURE_INDEX]
            min_val = self.scaler.min_[RAIN_FEATURE_INDEX]
            return scale, min_val
        except Exception:
            return None, None
    
    def get_rain_data_range(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Mengambil data_min dan data_max asli untuk inverse scaling.
        
        Dari MinMaxScaler:
        - data_min = -min_ / scale_
        - data_max = (1 - min_) / scale_
        """
        if self.scaler is None:
            return None, None
        try:
            scale = self.scaler.scale_[RAIN_FEATURE_INDEX]
            min_val = self.scaler.min_[RAIN_FEATURE_INDEX]
            
            data_min = -min_val / scale
            data_max = (1.0 - min_val) / scale
            
            return data_min, data_max
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


def _normalize_timestamp_to_5min(ts: datetime) -> datetime:
    """
    Normalisasi timestamp ke kelipatan 5 menit terdekat (floor).
    Mengabaikan detik - hanya melihat menit.
    
    Contoh:
    - 14:07:45 -> 14:05:00
    - 14:23:12 -> 14:20:00
    - 14:00:59 -> 14:00:00
    """
    if ts is None:
        return ts
    
    # Floor ke kelipatan 5 menit
    floored_minute = (ts.minute // 5) * 5
    
    # Buat timestamp baru dengan detik = 0
    return ts.replace(minute=floored_minute, second=0, microsecond=0)


def _check_data_needs_interpolation(timestamps: List[datetime]) -> bool:
    """
    Cek apakah data memerlukan interpolasi.
    Return True jika ada data bolong atau interval tidak pas 5 menit.
    
    Pengecekan dilakukan pada timestamp yang sudah dinormalisasi ke 5 menit.
    """
    if len(timestamps) < 2:
        return False
    
    # Normalisasi semua timestamp dulu
    normalized = [_normalize_timestamp_to_5min(ts) for ts in timestamps]
    
    for i in range(1, len(normalized)):
        diff = (normalized[i] - normalized[i-1]).total_seconds()
        expected = DATA_INTERVAL_MINUTES * 60  # 300 detik
        
        # Jika beda tidak tepat 5 menit (ada gap atau duplikat)
        if diff != expected:
            return True
    
    return False


# =====================================================================
# DATA FETCHING FUNCTIONS
# =====================================================================

def _get_latest_weather_data(source: str) -> Optional[Any]:
    """Ambil 1 data cuaca terkini untuk XGBoost - load only needed columns."""
    from .. import serializers
    try:
        if source == 'ecowitt':
            load_fields = [
                WeatherLogEcowitt.id,
                WeatherLogEcowitt.request_time,
                WeatherLogEcowitt.temperature_main_outdoor,
                WeatherLogEcowitt.humidity_outdoor,
                WeatherLogEcowitt.wind_speed,
                WeatherLogEcowitt.wind_direction,
                WeatherLogEcowitt.pressure_relative,
                WeatherLogEcowitt.rain_rate,
            ]
        elif source == 'console':
            load_fields = [
                WeatherLogConsole.id,
                WeatherLogConsole.date_utc,
                WeatherLogConsole.temperature,
                WeatherLogConsole.humidity,
                WeatherLogConsole.wind_speed,
                WeatherLogConsole.wind_direction,
                WeatherLogConsole.pressure_relative,
                WeatherLogConsole.rain_rate,
            ]
        else:
            load_fields = [
                WeatherLogWunderground.id,
                WeatherLogWunderground.request_time,
                WeatherLogWunderground.temperature,
                WeatherLogWunderground.humidity,
                WeatherLogWunderground.wind_speed,
                WeatherLogWunderground.wind_direction,
                WeatherLogWunderground.pressure,
                WeatherLogWunderground.precipitation_rate,
            ]
        
        return serializers.get_latest_weather_data(source, load_fields=load_fields)
    except Exception as e:
        logging.error(f"Error fetching latest {source} data: {e}")
        return None


def _prepare_xgboost_features(weather_log, source: str) -> Optional[Dict[str, float]]:
    """
    Menyiapkan fitur untuk prediksi XGBoost.
    
    Fitur yang diperlukan (6 fitur):
    1. suhu (°C)
    2. kelembaban (%)
    3. kecepatan_angin (m/s)
    4. arah_angin (derajat)
    5. tekanan_udara (hPa)
    6. intensitas_hujan (mm/h)
    
    Berlaku sama untuk console, ecowitt, dan wunderground.
    
    Mapping kolom database:
    - Console: temperature, humidity, wind_speed, wind_direction, pressure_relative, rain_rate
    - Ecowitt: temperature_main_outdoor, humidity_outdoor, wind_speed, wind_direction, pressure_relative, rain_rate
    - Wunderground: temperature, humidity, wind_speed, wind_direction, pressure, precipitation_rate
    """
    if weather_log is None:
        return None
    
    try:
        if source == 'console':
            # Console Station - data dalam Imperial, konversi ke Metric untuk model
            raw_temp = float(weather_log.temperature) if weather_log.temperature is not None else None
            raw_wind = float(weather_log.wind_speed) if weather_log.wind_speed is not None else None
            raw_pressure = float(weather_log.pressure_relative) if weather_log.pressure_relative is not None else None
            raw_rain = float(weather_log.rain_rate) if weather_log.rain_rate is not None else 0.0
            
            features = {
                'suhu': helpers.fahrenheit_to_celsius(raw_temp),  # °F -> °C
                'kelembaban': float(weather_log.humidity) if weather_log.humidity is not None else None,
                'kecepatan_angin': helpers.mph_to_ms(raw_wind),  # mph -> m/s
                'arah_angin': float(weather_log.wind_direction) if weather_log.wind_direction is not None else None,
                'tekanan_udara': helpers.inch_hg_to_hpa(raw_pressure),  # inHg -> hPa
                'intensitas_hujan': helpers.inch_per_hour_to_mm_per_hour(raw_rain) if raw_rain else 0.0,  # in/hr -> mm/hr
            }
        elif source == 'ecowitt':
            # Ecowitt - kolom: temperature_main_outdoor, humidity_outdoor
            features = {
                'suhu': float(weather_log.temperature_main_outdoor) if weather_log.temperature_main_outdoor is not None else None,
                'kelembaban': float(weather_log.humidity_outdoor) if weather_log.humidity_outdoor is not None else None,
                'kecepatan_angin': float(weather_log.wind_speed) if weather_log.wind_speed is not None else None,
                'arah_angin': float(weather_log.wind_direction) if weather_log.wind_direction is not None else None,
                'tekanan_udara': float(weather_log.pressure_relative) if weather_log.pressure_relative is not None else None,
                'intensitas_hujan': float(weather_log.rain_rate) if weather_log.rain_rate is not None else 0.0,
            }
        else:  # wunderground
            # Wunderground - kolom: temperature, humidity, pressure, precipitation_rate
            features = {
                'suhu': float(weather_log.temperature) if weather_log.temperature is not None else None,
                'kelembaban': float(weather_log.humidity) if weather_log.humidity is not None else None,
                'kecepatan_angin': float(weather_log.wind_speed) if weather_log.wind_speed is not None else None,
                'arah_angin': float(weather_log.wind_direction) if weather_log.wind_direction is not None else None,
                'tekanan_udara': float(weather_log.pressure) if weather_log.pressure is not None else None,
                'intensitas_hujan': float(weather_log.precipitation_rate) if weather_log.precipitation_rate is not None else 0.0,
            }
        
        # Validasi semua fitur ada (kecuali intensitas_hujan yang bisa 0)
        missing_features = [k for k, v in features.items() if v is None and k != 'intensitas_hujan']
        if missing_features:
            logging.warning(f"[{source}] Missing XGBoost features: {missing_features}")
            return None
        
        logging.debug(f"[{source}] XGBoost features: {features}")
        return features
        
    except Exception as e:
        logging.error(f"Error preparing XGBoost features for {source}: {e}")
        return None


def _fetch_lstm_data(source: str) -> Optional[Tuple[pd.DataFrame, List[int]]]:
    """
    Ambil 144 data terakhir dengan interval 5 menit untuk LSTM.
    
    Strategi: Data Asli ≥ 144 + Interpolasi Ringan
    ───────────────────────────────────────────────
    LSTM hanya jalan jika ada ≥ 144 data ASLI dari DB (setelah dedup).
    Interpolasi hanya merapikan gap kecil (misal loncat 10 menit)
    dalam 144 data tersebut — BUKAN mengisi kekosongan karena
    server mati. Ini menjamin kualitas data yang masuk ke model.
    
    Proses:
    1. Query data dari database (154 rows buffer)
    2. Normalisasi timestamp ke kelipatan 5 menit
    3. Deduplikasi (rata-rata untuk timestamp kembar)
    4. Cek: data unik ≥ 144? Jika tidak -> ABORT
    5. Ambil 144 data terbaru
    6. Jika interval sudah rapi (semua 5 menit) -> pakai langsung
    7. Jika ada gap (loncat 10, 15 menit dst):
       - Buat grid 5-menit dari min->max timestamp
       - Interpolasi ringan (maks 6 slot berturut-turut = 30 menit)
       - Ambil tail(144), cek rasio interpolasi ≤ 25%
    8. Hitung time features (hour_sin, hour_cos)
    9. Return (DataFrame 144×9, list DB IDs)
    
    Berlaku sama untuk console, ecowitt, dan wunderground.
    
    Returns:
        Tuple[DataFrame, List[int]]: (data untuk LSTM, list ID dari database)
    """
    try:
        if source == 'ecowitt':
            ModelClass = WeatherLogEcowitt
            order_column = ModelClass.request_time
        elif source == 'console':
            ModelClass = WeatherLogConsole
            order_column = ModelClass.date_utc  # Console pakai date_utc
        else:
            ModelClass = WeatherLogWunderground
            order_column = ModelClass.request_time
        
        # Ambil data sedikit lebih banyak (buffer) untuk mengantisipasi gap ringan
        # (Misal telat fetch 1-2 interval). +10 berarti buffer 50 menit
        buffer_size = SEQUENCE_LENGTH + 10
        
        # Load only columns needed for LSTM features
        if source == 'ecowitt':
            load_cols = load_only(
                ModelClass.id,
                ModelClass.request_time,
                ModelClass.temperature_main_outdoor,
                ModelClass.humidity_outdoor,
                ModelClass.wind_speed,
                ModelClass.wind_direction,
                ModelClass.pressure_relative,
                ModelClass.rain_rate,
                ModelClass.solar_irradiance,
            )
        elif source == 'console':
            load_cols = load_only(
                ModelClass.id,
                ModelClass.date_utc,
                ModelClass.temperature,
                ModelClass.humidity,
                ModelClass.wind_speed,
                ModelClass.wind_direction,
                ModelClass.pressure_relative,
                ModelClass.rain_rate,
                ModelClass.solar_radiation,
            )
        else:  # wunderground
            load_cols = load_only(
                ModelClass.id,
                ModelClass.request_time,
                ModelClass.temperature,
                ModelClass.humidity,
                ModelClass.wind_speed,
                ModelClass.wind_direction,
                ModelClass.pressure,
                ModelClass.precipitation_rate,
                ModelClass.solar_radiation,
            )
        
        rows = db.session.query(ModelClass).options(load_cols)\
            .order_by(order_column.desc())\
            .limit(buffer_size)\
            .all()
        
        if not rows or len(rows) < SEQUENCE_LENGTH:
            logging.warning(f"Tidak cukup data untuk LSTM {source}: {len(rows) if rows else 0}/{SEQUENCE_LENGTH}")
            return None
        
        # Reverse agar urut dari lama ke baru
        rows = list(reversed(rows))
        
        # Build mapping: normalized_timestamp -> DB ID.
        # Digunakan setelah grid mapping untuk tracking ID yang akurat.
        # Slot interpolasi tidak punya DB ID, hanya slot dengan data asli.
        row_ids = [row.id for row in rows]
        _ts_to_id: Dict[str, int] = {}  # isoformat string -> DB row ID
        for row in rows:
            _ts_raw = row.date_utc if source == 'console' else row.request_time
            if _ts_raw is not None:
                if _ts_raw.tzinfo is None:
                    _ts_raw = _ts_raw.replace(tzinfo=timezone.utc)
                _ts_norm = _normalize_timestamp_to_5min(_ts_raw)
                _ts_to_id[_ts_norm.isoformat()] = row.id  # last write wins
        
        # Konversi ke DataFrame
        data_list = []
        
        for row in rows:
            # Console menggunakan date_utc, lainnya menggunakan request_time
            if source == 'console':
                ts = row.date_utc
            else:
                ts = row.request_time
            
            if ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            
            # Normalisasi timestamp ke kelipatan 5 menit (abaikan detik)
            ts_normalized = _normalize_timestamp_to_5min(ts)
            
            if source == 'console':
                # Console Station - data dalam Imperial, konversi ke Metric untuk model
                raw_temp = float(row.temperature) if row.temperature is not None else np.nan
                raw_wind = float(row.wind_speed) if row.wind_speed is not None else 0.0
                raw_pressure = float(row.pressure_relative) if row.pressure_relative is not None else np.nan
                raw_rain = float(row.rain_rate) if row.rain_rate is not None else 0.0
                raw_solar = float(row.solar_radiation) if row.solar_radiation is not None else 0.0
                
                data_list.append({
                    'timestamp': ts_normalized,
                    'suhu': helpers.fahrenheit_to_celsius(raw_temp) if not np.isnan(raw_temp) else np.nan,  # °F -> °C
                    'kelembaban': float(row.humidity) if row.humidity is not None else np.nan,
                    'kecepatan_angin': helpers.mph_to_ms(raw_wind),  # mph -> m/s
                    'arah_angin': float(row.wind_direction) if row.wind_direction is not None else 0.0,
                    'tekanan_udara': helpers.inch_hg_to_hpa(raw_pressure) if not np.isnan(raw_pressure) else np.nan,  # inHg -> hPa
                    'intensitas_hujan': helpers.inch_per_hour_to_mm_per_hour(raw_rain) if raw_rain else 0.0,  # in/hr -> mm/hr
                    'intensitas_cahaya': helpers.wm2_to_lux(raw_solar),  # W/m² -> lux
                })
            elif source == 'wunderground':
                # Wunderground - kolom: temperature, humidity, pressure, precipitation_rate
                solar = helpers.wm2_to_lux(row.solar_radiation)
                data_list.append({
                    'timestamp': ts_normalized,
                    'suhu': float(row.temperature) if row.temperature is not None else np.nan,
                    'kelembaban': float(row.humidity) if row.humidity is not None else np.nan,
                    'kecepatan_angin': float(row.wind_speed) if row.wind_speed is not None else 0.0,
                    'arah_angin': float(row.wind_direction) if row.wind_direction is not None else 0.0,
                    'tekanan_udara': float(row.pressure) if row.pressure is not None else np.nan,
                    'intensitas_hujan': float(row.precipitation_rate) if row.precipitation_rate is not None else 0.0,
                    'intensitas_cahaya': solar,
                })
            else:  # ecowitt
                # Ecowitt - kolom: temperature_main_outdoor, humidity_outdoor
                # solar_irradiance sudah dalam lux (tidak perlu konversi)
                solar = float(row.solar_irradiance) if row.solar_irradiance is not None else 0.0
                data_list.append({
                    'timestamp': ts_normalized,
                    'suhu': float(row.temperature_main_outdoor) if row.temperature_main_outdoor is not None else np.nan,
                    'kelembaban': float(row.humidity_outdoor) if row.humidity_outdoor is not None else np.nan,
                    'kecepatan_angin': float(row.wind_speed) if row.wind_speed is not None else 0.0,
                    'arah_angin': float(row.wind_direction) if row.wind_direction is not None else 0.0,
                    'tekanan_udara': float(row.pressure_relative) if row.pressure_relative is not None else np.nan,
                    'intensitas_hujan': float(row.rain_rate) if row.rain_rate is not None else 0.0,
                    'intensitas_cahaya': solar,
                })
        
        if len(data_list) < SEQUENCE_LENGTH:
            logging.warning(f"Data tidak cukup setelah parsing untuk {source}: {len(data_list)}")
            return None
        
        df = pd.DataFrame(data_list)
        
        logging.info(f"[{source}] Data awal: {len(df)} rows, range: {df['timestamp'].min()} - {df['timestamp'].max()}")
        
        # ── STEP 1: Deduplikasi timestamp kembar (setelah floor 5 menit) ──
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        df_deduped = df.groupby('timestamp')[numeric_cols].mean().reset_index()
        df_deduped = df_deduped.sort_values('timestamp').reset_index(drop=True)
        
        dup_count = len(df) - len(df_deduped)
        if dup_count > 0:
            logging.info(
                f"[{source}] {dup_count} duplikat digabung -> "
                f"{len(df_deduped)} timestamp unik"
            )
        
        # ── STEP 2: Cek jumlah data asli ≥ 144 ──
        # LSTM hanya jalan jika ada cukup data ASLI dari DB.
        # Tidak ada "mengisi kekosongan" — data harus benar-benar ada.
        if len(df_deduped) < SEQUENCE_LENGTH:
            logging.warning(
                f"[{source}] Data asli tidak cukup untuk LSTM: "
                f"{len(df_deduped)}/{SEQUENCE_LENGTH} (butuh >={SEQUENCE_LENGTH} data unik). "
                f"Tunggu data terkumpul."
            )
            return None
        
        # ── STEP 3: Ambil 144 data terbaru ──
        df_144 = df_deduped.tail(SEQUENCE_LENGTH).reset_index(drop=True)
        
        logging.info(
            f"[{source}] {len(df_deduped)} data unik tersedia, "
            f"ambil {SEQUENCE_LENGTH} terbaru: "
            f"{df_144['timestamp'].min()} -> {df_144['timestamp'].max()}"
        )
        
        # ── STEP 4: Cek apakah interval sudah rapi (semua 5 menit) ──
        timestamps_144 = df_144['timestamp'].tolist()
        needs_resample = _check_data_needs_interpolation(timestamps_144)
        
        if needs_resample:
            # Ada gap (loncat 10, 15, ... menit) — perlu resample + interpolasi
            # Bangun grid 5-menit dari min->max, interpolasi gap ringan.
            logging.info(
                f"[{source}] Ada gap dalam {SEQUENCE_LENGTH} data "
                f"-> resample + interpolasi ringan"
            )
            
            # Simpan set timestamp asli untuk tracking rasio interpolasi
            original_ts_set = set(df_144['timestamp'].apply(lambda x: x.isoformat()))
            
            # Buat grid 5-menit dari min->max timestamp
            ts_min = df_144['timestamp'].min()
            ts_max = df_144['timestamp'].max()
            grid = pd.date_range(start=ts_min, end=ts_max, freq=f'{DATA_INTERVAL_MINUTES}min')
            
            # Map data ke grid
            df_grid = df_144.set_index('timestamp')
            df_grid = df_grid.reindex(grid)
            
            # Interpolasi linear (maks 6 slot berturut-turut = 30 menit gap)
            df_grid = df_grid.interpolate(method='linear', limit_direction='both', limit=6)
            df_grid = df_grid.ffill().bfill()
            
            # Cek sisa NaN (gap > 30 menit tidak bisa diinterpolasi)
            still_missing = int(df_grid.isna().any(axis=1).sum())
            if still_missing > 0:
                logging.warning(
                    f"[{source}] {still_missing} slot masih kosong setelah interpolasi "
                    f"(ada gap > 30 menit). LSTM dibatalkan."
                )
                return None
            
            # Reset index
            df_grid = df_grid.reset_index()
            df_grid = df_grid.rename(columns={'index': 'timestamp'})
            
            # Ambil tail(144) jika grid > 144 (grid bisa lebih besar karena gap)
            if len(df_grid) > SEQUENCE_LENGTH:
                df_grid = df_grid.tail(SEQUENCE_LENGTH).reset_index(drop=True)
            
            # Hitung rasio interpolasi pada window final
            final_ts_set = set(df_grid['timestamp'].apply(lambda x: x.isoformat()))
            interpolated_count = len(final_ts_set - original_ts_set)
            
            if interpolated_count > 0:
                ratio = interpolated_count / SEQUENCE_LENGTH
                if ratio >= MAX_INTERPOLATED_RATIO:
                    logging.warning(
                        f"[{source}] Rasio interpolasi terlalu tinggi: "
                        f"{interpolated_count}/{SEQUENCE_LENGTH} ({ratio:.0%}), "
                        f"maks {MAX_INTERPOLATED_RATIO:.0%}. LSTM dibatalkan."
                    )
                    return None
                logging.info(
                    f"[{source}] Interpolasi OK: "
                    f"{interpolated_count} slot terisi ({ratio:.0%})"
                )
            else:
                logging.info(f"[{source}] Resample selesai, tidak ada slot baru")
            
            df = df_grid
        else:
            # Data sudah rapi — interval 5 menit sempurna, pakai langsung
            df = df_144
            logging.info(
                f"[{source}] Data {SEQUENCE_LENGTH} point rapi "
                f"(interval 5 menit sempurna, tanpa interpolasi)"
            )
        
        logging.info(f"[{source}] Data final: {len(df)} rows")
        
        # Imputation untuk NaN yang tersisa
        # Gunakan default klimatologis Indonesia, bukan 0, untuk menghindari
        # outlier ekstrem pada scaler (misal suhu=0°C atau tekanan=0 hPa).
        numeric_cols = ['suhu', 'kelembaban', 'kecepatan_angin', 'arah_angin', 
                       'tekanan_udara', 'intensitas_hujan', 'intensitas_cahaya']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].ffill().bfill().fillna(_SAFE_FILL_DEFAULTS.get(col, 0))
        
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
            for col in final_df.columns:
                if final_df[col].isnull().any():
                    final_df[col] = final_df[col].ffill().bfill().fillna(_SAFE_FILL_DEFAULTS.get(col, 0))
        
        # ── Map timestamp final -> DB ID ──
        # Grid slot dengan data asli -> ID dari DB.
        # Grid slot interpolasi -> tidak ada DB ID (dilewati).
        final_ids = []
        for _ts in df['timestamp']:
            _key = _ts.isoformat() if hasattr(_ts, 'isoformat') else str(_ts)
            _db_id = _ts_to_id.get(_key)
            if _db_id is not None:
                final_ids.append(_db_id)
        
        if not final_ids:
            # Fallback jika mapping gagal (misal timezone mismatch)
            final_ids = row_ids[-SEQUENCE_LENGTH:] if len(row_ids) >= SEQUENCE_LENGTH else row_ids
            logging.warning(f"[{source}] Timestamp->ID mapping gagal, menggunakan fallback IDs")
        else:
            interp_rows = SEQUENCE_LENGTH - len(final_ids)
            if interp_rows > 0:
                logging.info(
                    f"[{source}] ID tracking: {len(final_ids)} DB rows + "
                    f"{interp_rows} interpolated rows = {SEQUENCE_LENGTH} total"
                )
        
        return (final_df, final_ids)
        
    except Exception as e:
        logging.error(f"Error fetching LSTM data for {source}: {e}")
        return None


# =====================================================================
# PREDICTION FUNCTIONS
# =====================================================================

def predict_xgboost(features: Dict[str, float], source: str) -> Optional[int]:
    """Jalankan prediksi XGBoost dan return class label (int)."""
    logging.info(f"Melakukan prediksi cuaca untuk {source} (XGBoost)...")
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
        
        # Buat DataFrame dengan feature names
        input_df = pd.DataFrame([features], columns=XGBOOST_REQUIRED_FEATURES)
        input_df = input_df.astype(float)
        
        # Prediksi — gunakan DMatrix untuk handling version-mismatch
        # Model diserialisasi via joblib oleh XGBoost versi lama. XGBoost 3.x
        # internal booster tidak menyimpan feature names, menyebabkan
        # validate_features gagal meskipun DataFrame benar. Solusi: buat
        # DMatrix secara eksplisit dengan feature_names.
        import xgboost as xgb
        dmatrix = xgb.DMatrix(input_df, feature_names=XGBOOST_REQUIRED_FEATURES)
        booster = loader.xgboost_model.get_booster()
        prediction_raw = booster.predict(dmatrix)
        
        # XGBClassifier multi-class: output berupa probabilitas per kelas
        # Ambil kelas dengan probabilitas tertinggi
        import numpy as np
        if prediction_raw.ndim == 2:
            result = int(np.argmax(prediction_raw[0]))
        else:
            result = int(prediction_raw[0])
        
        logging.info(f"XGBoost prediction for {source.capitalize()}: {result} ({LABEL_MAP.get(result, 'Unknown')})")
        return result
        
    except Exception as e:
        logging.error(f"Error in XGBoost prediction for {source}: {e}")
        return None


def predict_lstm(data: pd.DataFrame, source: str) -> Optional[List[float]]:
    """
    Jalankan prediksi LSTM dan return array 24 nilai (intensitas hujan per jam).
    
    Proses:
    1. Validasi shape data (144, 9)
    2. Scaling menggunakan MinMaxScaler yang sudah di-fit
    3. Reshape untuk input LSTM (1, 144, 9)
    4. Prediksi menghasilkan (1, 24) - scaled values
    5. Inverse scaling untuk mendapat nilai mm/h asli
    
    Formula MinMaxScaler:
    - Scaling:   X_scaled = X * scale_ + min_
    - Inverse:   X = (X_scaled - min_) / scale_
    """
    logging.info(f"Melakukan prediksi cuaca untuk {source} (LSTM)...")
    loader = get_model_loader()
    
    if loader.lstm_model is None or loader.scaler is None:
        logging.warning("LSTM model atau scaler tidak tersedia")
        return None
    
    try:
        # Konversi ke numpy array
        raw_data = data.values.astype(np.float64)
        
        if raw_data.shape != (SEQUENCE_LENGTH, N_FEATURES):
            logging.error(f"Invalid data shape: {raw_data.shape}, expected ({SEQUENCE_LENGTH}, {N_FEATURES})")
            return None
        
        # Log statistik input sebelum scaling
        logging.debug(f"Input stats before scaling - mean: {raw_data.mean(axis=0)}, std: {raw_data.std(axis=0)}")
        
        # Scaling menggunakan scaler yang sudah di-fit
        scaled_data = loader.scaler.transform(raw_data)
        
        # Log statistik setelah scaling
        logging.debug(f"Scaled stats - min: {scaled_data.min()}, max: {scaled_data.max()}")
        
        # Reshape untuk LSTM: (batch, steps, features) -> (1, 144, 9)
        input_tensor = scaled_data.reshape(1, SEQUENCE_LENGTH, N_FEATURES)
        
        # Prediksi - output adalah scaled values (thread-safe via Lock eksplisit)
        with _lstm_predict_lock:
            pred_scaled = loader.lstm_model.predict(input_tensor, verbose=0)
        
        logging.debug(f"Raw prediction (scaled): min={pred_scaled.min():.4f}, max={pred_scaled.max():.4f}")
        
        # Inverse scaling khusus untuk fitur hujan (index 5)
        scale_val, min_val = loader.get_rain_inverse_params()
        
        if scale_val is None or min_val is None:
            logging.warning("Tidak bisa melakukan inverse scaling - return raw prediction")
            return pred_scaled.flatten().tolist()
        
        logging.debug(f"Inverse params - scale: {scale_val}, min: {min_val}")
        
        # Rumus Inverse MinMaxScaler: X = (X_scaled - min_) / scale_
        pred_unscaled = (pred_scaled - min_val) / scale_val
        
        logging.debug(f"After inverse scaling: min={pred_unscaled.min():.4f}, max={pred_unscaled.max():.4f}")
        
        # Bersihkan nilai negatif (hujan tidak bisa negatif)
        pred_final = np.maximum(pred_unscaled, 0.0).flatten()
        
        # Bulatkan ke 2 desimal
        final_rounded = [round(float(x), 2) for x in pred_final]
        
        logging.info(f"LSTM prediction for {source.capitalize()} (24 hours): {final_rounded}")
        return final_rounded
        
    except Exception as e:
        logging.error(f"Error in LSTM prediction for {source}: {e}")
        import traceback
        logging.debug(traceback.format_exc())
        return None


# =====================================================================
# PARALLEL SOURCE PROCESSING
# =====================================================================

def _process_source(source: str, app) -> SourceResult:
    """
    Process single source: XGBoost -> LSTM (sequential within thread).
    Dijalankan dalam thread terpisah (parallel antar sumber).
    
    Args:
        source: 'console', 'ecowitt', atau 'wunderground'
        app: Flask app object untuk app_context
    
    Returns:
        SourceResult dengan hasil XGBoost dan LSTM (atau error messages)
    """
    result = SourceResult(source=source)
    
    try:
        with app.app_context():
            # 1. Get latest weather data (1 data untuk XGBoost)
            weather = _get_latest_weather_data(source)
            if not weather:
                result.xgboost_error = f"No data available for {source}"
                result.lstm_error = f"No data available for {source}"
                logging.warning(f"[{source}] No weather data available")
                return result
            
            result.weather_id = weather.id
            logging.info(f"[{source}] Processing weather_id={weather.id}")
            
            # 2. XGBoost freshness check — hindari prediksi dengan data basi
            _xgb_ts = weather.date_utc if source == 'console' else weather.request_time
            _data_is_fresh = False
            if _xgb_ts is not None:
                if _xgb_ts.tzinfo is None:
                    _xgb_ts = _xgb_ts.replace(tzinfo=timezone.utc)
                _age = (datetime.now(timezone.utc) - _xgb_ts).total_seconds()
                _data_is_fresh = _age < XGBOOST_FRESHNESS_SECONDS
                if not _data_is_fresh:
                    logging.warning(
                        f"[{source}] XGBoost DILEWATI: data sudah {_age/60:.1f} menit lalu "
                        f"(maks {XGBOOST_FRESHNESS_SECONDS//60} menit). "
                        f"Menghindari prediksi dengan data basi."
                    )
                    result.xgboost_error = (
                        f"Data basi ({_age/60:.0f} mnt, maks {XGBOOST_FRESHNESS_SECONDS//60} mnt)"
                    )
            else:
                logging.warning(f"[{source}] Timestamp tidak tersedia, XGBoost dilewati")
                result.xgboost_error = "Timestamp data tidak tersedia"
            
            # 3. XGBoost prediction (hanya jika data segar)
            if _data_is_fresh:
                try:
                    features = _prepare_xgboost_features(weather, source)
                    if features:
                        result.xgboost = predict_xgboost(features, source)
                        logging.info(f"[{source}] XGBoost: class {result.xgboost}")
                    else:
                        result.xgboost_error = "Failed to prepare XGBoost features"
                        logging.warning(f"[{source}] XGBoost: feature preparation failed")
                except Exception as e:
                    result.xgboost_error = str(e)
                    logging.error(f"[{source}] XGBoost failed: {e}")
            
            # 4. LSTM prediction (regardless of XGBoost result)
            try:
                lstm_data = _fetch_lstm_data(source)
                if lstm_data:
                    df, ids = lstm_data
                    result.lstm = predict_lstm(df, source)
                    result.lstm_ids = ids
                    logging.info(f"[{source}] LSTM: {len(result.lstm) if result.lstm else 0} values using {len(ids) if ids else 0} data points")
                else:
                    result.lstm_error = "Insufficient data for LSTM (need 144 points)"
                    logging.warning(f"[{source}] LSTM: insufficient data")
            except Exception as e:
                result.lstm_error = str(e)
                logging.error(f"[{source}] LSTM failed: {e}")
                
    except Exception as e:
        result.xgboost_error = str(e)
        result.lstm_error = str(e)
        logging.error(f"[{source}] Critical failure: {e}")
    
    return result


# =====================================================================
# MAIN PREDICTION PIPELINE
# =====================================================================

def run_prediction_pipeline(skip_sources: list = None) -> Optional[PredictionLog]:
    """
    Menjalankan pipeline prediksi dengan parallel processing per sumber.
    
    Args:
        skip_sources: List source yang di-skip karena fetch gagal.
                      Contoh: ['wunderground'] jika Wunderground fetch gagal.
                      None = proses semua source (default, dipakai safety net).
    
    Features:
    - Parallel: sumber diproses bersamaan
    - Sequential: XGBoost -> LSTM dalam tiap thread
    - Partial Save: Simpan XGBoost jika berhasil, simpan LSTM jika berhasil
    - Error Isolation: Error satu sumber tidak mempengaruhi lainnya
    - Timeout: 60 detik per sumber
    
    Returns:
        PredictionLog terakhir yang tersimpan, atau None jika gagal total.
    """
    logging.info("=" * 60)
    logging.info("[PREDIKSI] Memulai Parallel Prediction Pipeline")
    
    # Tentukan source yang akan diproses (filter yang gagal fetch)
    all_sources = ['console', 'ecowitt', 'wunderground']
    if skip_sources:
        sources = [s for s in all_sources if s not in skip_sources]
        skipped = [s for s in all_sources if s in skip_sources]
        if skipped:
            logging.warning(f"[PREDIKSI] Source di-SKIP (fetch gagal): {skipped}")
    else:
        sources = all_sources
    
    if not sources:
        logging.warning("[PREDIKSI] Semua source di-skip. Pipeline DIBATALKAN.")
        return None
    
    logging.info(f"[PREDIKSI] Mode: {len(sources)} threads parallel, XGBoost->LSTM sequential per thread")
    logging.info(f"[PREDIKSI] Sources: {sources}")
    logging.info("=" * 60)
    
    # Inisialisasi model jika belum
    initialize_models()
    
    # Get Flask app untuk app_context di thread
    app = current_app._get_current_object()
    source_results: Dict[str, SourceResult] = {}
    
    # =========================================================================
    # STEP 1: PARALLEL PROCESSING (3 threads)
    # =========================================================================
    TIMEOUT_SECONDS = 60
    
    logging.info("-" * 40)
    logging.info("Step 1: Parallel processing (3 sources)")
    logging.info("-" * 40)
    
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix='predict') as executor:
        # Submit semua task
        future_to_source = {
            executor.submit(_process_source, src, app): src
            for src in sources
        }
        
        # Collect results
        for future in as_completed(future_to_source, timeout=TIMEOUT_SECONDS + 10):
            source = future_to_source[future]
            try:
                result = future.result(timeout=TIMEOUT_SECONDS)
                source_results[source] = result
                
                xgb_status = f"class {result.xgboost}" if result.xgboost is not None else "FAILED"
                lstm_status = f"{len(result.lstm)} vals" if result.lstm else "FAILED"
                logging.info(f"[{source}] Completed - XGBoost: {xgb_status}, LSTM: {lstm_status}")
                
            except FuturesTimeoutError:
                source_results[source] = SourceResult(
                    source=source, 
                    xgboost_error="Timeout", 
                    lstm_error="Timeout"
                )
                logging.error(f"[{source}] Timeout after {TIMEOUT_SECONDS}s")
            except Exception as e:
                source_results[source] = SourceResult(
                    source=source, 
                    xgboost_error=str(e), 
                    lstm_error=str(e)
                )
                logging.error(f"[{source}] Exception: {e}")
    
    # =========================================================================
    # STEP 2: AGGREGATE RESULTS
    # =========================================================================
    logging.info("-" * 40)
    logging.info("Step 2: Aggregating results")
    logging.info("-" * 40)
    
    # Helper untuk mendapatkan SourceResult dengan default
    def get_result(src: str) -> SourceResult:
        return source_results.get(src, SourceResult(source=src))
    
    results = {
        'console_weather_id': get_result('console').weather_id,
        'console_xgboost': get_result('console').xgboost,
        'console_lstm': get_result('console').lstm,
        'console_lstm_ids': get_result('console').lstm_ids,
        'ecowitt_weather_id': get_result('ecowitt').weather_id,
        'ecowitt_xgboost': get_result('ecowitt').xgboost,
        'ecowitt_lstm': get_result('ecowitt').lstm,
        'ecowitt_lstm_ids': get_result('ecowitt').lstm_ids,
        'wunderground_weather_id': get_result('wunderground').weather_id,
        'wunderground_xgboost': get_result('wunderground').xgboost,
        'wunderground_lstm': get_result('wunderground').lstm,
        'wunderground_lstm_ids': get_result('wunderground').lstm_ids,
    }
    
    # =========================================================================
    # STEP 3: PARTIAL SAVE LOGIC
    # =========================================================================
    logging.info("-" * 40)
    logging.info("Step 3: Saving to database (partial save)")
    logging.info("-" * 40)
    
    # Cek hasil XGBoost (minimal 1 sumber berhasil)
    has_xgboost_results = any([
        results['console_xgboost'] is not None,
        results['ecowitt_xgboost'] is not None,
        results['wunderground_xgboost'] is not None,
    ])
    
    # Cek hasil LSTM (minimal 1 sumber berhasil)
    has_lstm_results = any([
        results['console_lstm'] is not None,
        results['ecowitt_lstm'] is not None,
        results['wunderground_lstm'] is not None,
    ])
    
    if not has_xgboost_results and not has_lstm_results:
        logging.warning("[PREDIKSI] Tidak ada hasil dari kedua model. Pipeline dibatalkan.")
        return None
    
    logging.info(f"[PREDIKSI] Has XGBoost results: {has_xgboost_results}")
    logging.info(f"[PREDIKSI] Has LSTM results: {has_lstm_results}")
    
    # Ambil model metadata - gunakan exact match untuk efisiensi (avoid ILIKE)
    xgboost_model_meta = db.session.query(ModelMeta).options(
        load_only(ModelMeta.id, ModelMeta.name)
    ).filter(
        ModelMeta.name == 'default_xgboost'
    ).first()
    lstm_model_meta = db.session.query(ModelMeta).options(
        load_only(ModelMeta.id, ModelMeta.name)
    ).filter(
        ModelMeta.name == 'default_lstm'
    ).first()
    
    try:
        prediction_logs = []
        
        # Gunakan satu timestamp yang sama untuk semua log dalam batch ini
        # Ini PENTING agar serializers.py bisa mem-pairing XGBoost dan LSTM berdasarkan created_at
        prediction_timestamp = datetime.now(timezone.utc)
        
        # ---------------------------------------------------------------------
        # SAVE XGBOOST (jika ada hasil)
        # ---------------------------------------------------------------------
        if has_xgboost_results:
            # DataXGBoost: referensi 1 ID per sumber yang berhasil
            data_xgboost = DataXGBoost(
                weather_log_console_id=results['console_weather_id'] if results['console_xgboost'] is not None else None,
                weather_log_ecowitt_id=results['ecowitt_weather_id'] if results['ecowitt_xgboost'] is not None else None,
                weather_log_wunderground_id=results['wunderground_weather_id'] if results['wunderground_xgboost'] is not None else None,
            )
            db.session.add(data_xgboost)
            db.session.flush()
            
            # XGBoostPredictionResult: konversi class_id ke label_id
            def _class_to_label_id(class_id: int) -> int:
                if class_id is None:
                    return None
                return class_id + 1  # label.id dimulai dari 1
            
            xgboost_result = XGBoostPredictionResult(
                console_result_id=_class_to_label_id(results['console_xgboost']),
                ecowitt_result_id=_class_to_label_id(results['ecowitt_xgboost']),
                wunderground_result_id=_class_to_label_id(results['wunderground_xgboost']),
            )
            db.session.add(xgboost_result)
            db.session.flush()
            
            # PredictionLog untuk XGBoost
            pl_xgboost = PredictionLog(
                model_id=xgboost_model_meta.id if xgboost_model_meta else None,
                data_xgboost_id=data_xgboost.id,
                data_lstm_id=None,  # NULL karena ini XGBoost
                xgboost_result_id=xgboost_result.id,
                lstm_result_id=None,  # NULL karena ini XGBoost
                created_at=prediction_timestamp,  # Explicit sync
            )
            db.session.add(pl_xgboost)
            prediction_logs.append(('XGBoost', pl_xgboost, data_xgboost, xgboost_result))
            
            logging.info(f"[PREDIKSI] XGBoost data prepared (DataXGBoost ID: {data_xgboost.id})")
        
        # ---------------------------------------------------------------------
        # SAVE LSTM (jika ada hasil)
        # ---------------------------------------------------------------------
        if has_lstm_results:
            # DataLSTM: referensi 144 IDs per sumber yang berhasil (sebagai array)
            data_lstm = DataLSTM(
                weather_log_console_ids=results['console_lstm_ids'] if results['console_lstm'] is not None else None,
                weather_log_ecowitt_ids=results['ecowitt_lstm_ids'] if results['ecowitt_lstm'] is not None else None,
                weather_log_wunderground_ids=results['wunderground_lstm_ids'] if results['wunderground_lstm'] is not None else None,
            )
            db.session.add(data_lstm)
            db.session.flush()
            
            # LSTMPredictionResult: array 24 float per sumber
            lstm_result = LSTMPredictionResult(
                console_result=results['console_lstm'],
                ecowitt_result=results['ecowitt_lstm'],
                wunderground_result=results['wunderground_lstm'],
            )
            db.session.add(lstm_result)
            db.session.flush()
            
            # PredictionLog untuk LSTM
            pl_lstm = PredictionLog(
                model_id=lstm_model_meta.id if lstm_model_meta else None,
                data_xgboost_id=None,  # NULL karena ini LSTM
                data_lstm_id=data_lstm.id,
                xgboost_result_id=None,  # NULL karena ini LSTM
                lstm_result_id=lstm_result.id,
                created_at=prediction_timestamp,  # Explicit sync
            )
            db.session.add(pl_lstm)
            prediction_logs.append(('LSTM', pl_lstm, data_lstm, lstm_result))
            
            logging.info(f"[PREDIKSI] LSTM data prepared (DataLSTM ID: {data_lstm.id})")
        
        # ---------------------------------------------------------------------
        # COMMIT ATOMIC
        # ---------------------------------------------------------------------
        db.session.commit()
        
        # Log hasil
        logging.info("=" * 60)
        logging.info("[PREDIKSI] Pipeline completed successfully!")
        for model_type, pl, data_obj, result_obj in prediction_logs:
            logging.info(f"  - PredictionLog {model_type}: ID={pl.id}")
        logging.info("=" * 60)
        
        # Return PredictionLog terakhir (LSTM jika ada, XGBoost jika tidak)
        if prediction_logs:
            return prediction_logs[-1][1]
        return None
        
    except Exception as e:
        logging.error(f"[PREDIKSI] Error saving prediction results: {e}")
        db.session.rollback()
        import traceback
        logging.debug(traceback.format_exc())
        return None


def get_label_name(class_id: int) -> str:
    """
    Mendapatkan nama label dari class ID XGBoost.
    Prioritas: Database -> Fallback ke LABEL_MAP hardcoded.
    
    Note: XGBoost mengembalikan class_id 0-8, tapi di database label.id dimulai dari 1.
    Karena XGBoost dilatih dengan class_id 0-8 (sesuai LABEL_MAP), kita gunakan class_id + 1
    untuk mengambil dari database (karena ID database dimulai dari 1).
    """
    try:
        # Gunakan Session.get() untuk PK lookup — memanfaatkan identity map cache
        # sehingga tidak mengirim query SQL jika objek sudah ada di session
        label = db.session.get(Label, class_id + 1)
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
    try:
        # Gunakan Session.get() untuk PK lookup — memanfaatkan identity map cache
        label = db.session.get(Label, class_id + 1)
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
    try:
        model = db.session.query(ModelMeta).options(
            load_only(ModelMeta.id, ModelMeta.name, ModelMeta.range_prediction)
        ).filter(
            ModelMeta.name == f'default_{model_type}'
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
