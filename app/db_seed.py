from __future__ import annotations

import os
from typing import Optional
from sqlalchemy import create_engine, text, inspect


DEFAULT_MODEL_FILENAME = 'model_prediksi_hujan_darimana_XGBoost.joblib'


def _get_default_model_path() -> str:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return os.path.join(base, 'ml_models', DEFAULT_MODEL_FILENAME)


def seed_labels_and_models(database_url: Optional[str] = None, model_path: Optional[str] = None, logger=None) -> None:
    def _log(msg):
        if logger:
            try:
                logger.info(msg)
            except Exception:
                pass
        else:
            try:
                print(msg)
            except Exception:
                pass

    if not database_url:
        database_url = os.environ.get('DATABASE_URL', "postgresql://postgres@localhost:5432/tuws_pws")

    if not model_path:
        model_path = _get_default_model_path()

    engine = create_engine(database_url)
    insp = inspect(engine)

    with engine.begin() as conn:
        if insp.has_table('label'):
            try:
                cnt = conn.execute(text('SELECT COUNT(*) AS cnt FROM label')).scalar()
                _log(f"[db_seed] label count={cnt}")
                if cnt == 0:
                    # PERINGATAN: label harus sinkron dengan LABEL_MAP
                    # di app/services/prediction_service.py
                    label_map_local = [
                        'Cerah / Berawan',
                        'Berpotensi Hujan dari Arah Utara',
                        'Berpotensi Hujan dari Arah Timur Laut',
                        'Berpotensi Hujan dari Arah Timur',
                        'Berpotensi Hujan dari Arah Tenggara',
                        'Berpotensi Hujan dari Arah Selatan',
                        'Berpotensi Hujan dari Arah Barat Daya',
                        'Berpotensi Hujan dari Arah Barat',
                        'Berpotensi Hujan dari Arah Barat Laut',
                    ]
                    for name in label_map_local:
                        conn.execute(text('INSERT INTO label (name) VALUES (:name)'), {'name': name})
                    _log('[db_seed] Seeded table `label`.')
                else:
                    _log('[db_seed] label already seeded; skipping.')
            except Exception as e:
                _log(f'[db_seed] Failed to seed label: {e}')
        else:
            _log("[db_seed] Table 'label' does not exist; skipping label seed.")

        if insp.has_table('model'):
            try:
                cntm = conn.execute(text('SELECT COUNT(*) AS cnt FROM model')).scalar()
                _log(f"[db_seed] model count={cntm}")
                if cntm == 0:
                    # Seed default models: XGBoost dan LSTM
                    models_to_seed = [
                        {'name': 'default_xgboost', 'range': 60},
                        {'name': 'default_lstm', 'range': 1440},  # 1440 menit = 24 jam prediksi
                    ]
                    for m in models_to_seed:
                        conn.execute(
                            text('INSERT INTO model (name, range_prediction) VALUES (:name, :range)'),
                            m
                        )
                    _log(f'[db_seed] Seeded table `model` with {len(models_to_seed)} entries.')
                else:
                    # Cek apakah LSTM sudah ada (exact match, bukan LIKE)
                    lstm_exists = conn.execute(
                        text("SELECT COUNT(*) FROM model WHERE name = 'default_lstm'")
                    ).scalar()
                    if lstm_exists == 0:
                        conn.execute(
                            text('INSERT INTO model (name, range_prediction) VALUES (:name, :range)'),
                            {'name': 'default_lstm', 'range': 1440}
                        )
                        _log('[db_seed] Added missing LSTM model.')
                    else:
                        _log('[db_seed] model already seeded; skipping.')
            except Exception as e:
                _log(f'[db_seed] Failed to seed model: {e}')
        else:
            _log("[db_seed] Table 'model' does not exist; skipping model seed.")


if __name__ == '__main__':
    seed_labels_and_models()
