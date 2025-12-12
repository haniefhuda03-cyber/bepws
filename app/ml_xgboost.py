import joblib
import os
import pandas as pd
import logging
from flask import current_app

MODEL_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'ml_models', 'model_prediksi_hujan_darimana_XGBoost.joblib'))

REQUIRED_FEATURES = [
    'suhu',
    'kelembaban',
    'kecepatan_angin',
    'arah_angin',
    'tekanan_udara',
    'intensitas_hujan'
]

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

_model = None

class DeterministicMockModel:
    def __init__(self, label_map_keys):
        self._n = len(label_map_keys)

    def predict(self, df):
        vals = []
        for col in df.columns:
            v = df[col].iloc[0]
            try:
                vals.append(float(v) if v is not None else 0.0)
            except Exception:
                vals.append(0.0)
        
        s = int(sum(vals) * 100)
        idx = s % self._n
        return [idx]

def _load_model_once():
    global _model
    if _model is not None:
        return _model

    try:
        if os.path.exists(MODEL_PATH):
            _model = joblib.load(MODEL_PATH)
            logging.getLogger(__name__).info(f"Model ML berhasil dimuat dari {MODEL_PATH}")
        else:
            _model = None 
            logging.getLogger(__name__).warning(f"File model tidak ditemukan di {MODEL_PATH}.")
    except Exception as e:
        _model = None
        logging.getLogger(__name__).warning(f"Gagal memuat model ML: {e}")
    
    return _model


def is_model_available() -> bool:
    if _model is not None:
        if not isinstance(_model, DeterministicMockModel):
            return True
    return os.path.exists(MODEL_PATH)


def run_prediction(api_data: dict) -> int | None:
    global _model
    
    model = _load_model_once()

    if model is None:
        use_fallback = False
        try:
            cfg_demo = bool(current_app.config.get('DEMO_MODE', False))
            cfg_testing = bool(current_app.config.get('TESTING', False))
            use_fallback = cfg_demo or (not cfg_testing) 
        except Exception:
            use_fallback = True

        if use_fallback:
            logging.getLogger(__name__).warning('Menggunakan ML fallback (Mock) karena model asli tidak tersedia.')
            model = DeterministicMockModel(list(LABEL_MAP.keys()))
            _model = model 
        else:
            logging.getLogger(__name__).error('Prediksi dibatalkan: Model asli tidak ada dan Fallback tidak diizinkan.')
            return None

    try:
        if not all(feature in api_data for feature in REQUIRED_FEATURES):
            missing = [f for f in REQUIRED_FEATURES if f not in api_data]
            logging.getLogger(__name__).error(f"Data input tidak lengkap. Hilang: {missing}")
            return None

        input_df = pd.DataFrame([api_data], columns=REQUIRED_FEATURES)
        
        input_df = input_df.astype(float)

        prediction_raw = model.predict(input_df)
        
        prediction_number = int(prediction_raw[0])
        
        logging.getLogger(__name__).info(f"Prediksi Sukses. Input: {api_data} -> Hasil Class: {prediction_number}")
        return prediction_number

    except ValueError as ve:
        logging.getLogger(__name__).error(f"Kesalahan Tipe Data: Pastikan semua input berupa angka. Detail: {ve}")
        return None
    except Exception as e:
        logging.getLogger(__name__).error(f"Kesalahan Sistem saat prediksi: {e}")
        return None