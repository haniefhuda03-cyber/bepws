"""Update prediction_log table to 10 columns with new structure

Revision ID: update_prediction_log_10cols
Revises: 40f14e08573e
Create Date: 2024-12-22

Perubahan:
- Hapus kolom model_id, ecowitt_prediction_result (FK ke label), wunderground_prediction_result (FK ke label)
- Tambah kolom xgboost_model_id (FK ke model)
- Tambah kolom lstm_model_id (FK ke model)  
- Tambah kolom ecowitt_predict_result (INT, hasil klasifikasi)
- Tambah kolom wunderground_predict_result (INT, hasil klasifikasi)
- Tambah kolom ecowitt_predict_data (JSON, output LSTM)
- Tambah kolom wunderground_predict_data (JSON, output LSTM)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'update_prediction_log_10cols'
down_revision = '40f14e08573e'
branch_labels = None
depends_on = None


def upgrade():
    # =====================================================
    # Step 1: Tambah kolom baru
    # =====================================================
    
    # Kolom untuk model IDs (terpisah untuk XGBoost dan LSTM)
    op.add_column('prediction_log', sa.Column('xgboost_model_id', sa.Integer(), nullable=True))
    op.add_column('prediction_log', sa.Column('lstm_model_id', sa.Integer(), nullable=True))
    
    # Kolom untuk hasil XGBoost (INT, bukan FK ke label)
    op.add_column('prediction_log', sa.Column('ecowitt_predict_result', sa.Integer(), nullable=True))
    op.add_column('prediction_log', sa.Column('wunderground_predict_result', sa.Integer(), nullable=True))
    
    # Kolom untuk hasil LSTM (JSON array 24 angka)
    op.add_column('prediction_log', sa.Column('ecowitt_predict_data', sa.JSON(), nullable=True))
    op.add_column('prediction_log', sa.Column('wunderground_predict_data', sa.JSON(), nullable=True))
    
    # =====================================================
    # Step 2: Migrasi data dari kolom lama ke baru
    # =====================================================
    
    # Copy model_id ke kedua kolom baru (xgboost_model_id dan lstm_model_id)
    op.execute("""
        UPDATE prediction_log 
        SET xgboost_model_id = model_id,
            lstm_model_id = model_id
        WHERE model_id IS NOT NULL
    """)
    
    # Copy prediction results (konversi dari FK label.id ke integer class)
    # Kita perlu join ke tabel label untuk mendapatkan class ID
    # Karena label.name berisi text seperti "Cerah / Berawan", kita perlu mapping
    # Untuk migrasi sederhana, kita set NULL dulu (data baru akan diisi oleh prediction service)
    
    # =====================================================
    # Step 3: Buat foreign key constraints baru
    # =====================================================
    
    op.create_foreign_key(
        'fk_prediction_log_xgboost_model',
        'prediction_log', 'model',
        ['xgboost_model_id'], ['id']
    )
    
    op.create_foreign_key(
        'fk_prediction_log_lstm_model',
        'prediction_log', 'model',
        ['lstm_model_id'], ['id']
    )
    
    # =====================================================
    # Step 4: Hapus kolom lama dan constraints
    # =====================================================
    
    # Hapus foreign key constraints lama
    try:
        op.drop_constraint('prediction_log_ibfk_3', 'prediction_log', type_='foreignkey')
    except Exception:
        pass  # Constraint mungkin tidak ada
    
    try:
        op.drop_constraint('prediction_log_ibfk_4', 'prediction_log', type_='foreignkey')
    except Exception:
        pass
    
    try:
        op.drop_constraint('prediction_log_ibfk_5', 'prediction_log', type_='foreignkey')
    except Exception:
        pass
    
    # Hapus kolom lama
    try:
        op.drop_column('prediction_log', 'model_id')
    except Exception:
        pass
    
    try:
        op.drop_column('prediction_log', 'ecowitt_prediction_result')
    except Exception:
        pass
    
    try:
        op.drop_column('prediction_log', 'wunderground_prediction_result')
    except Exception:
        pass


def downgrade():
    # =====================================================
    # Rollback ke struktur lama
    # =====================================================
    
    # Tambah kembali kolom lama
    op.add_column('prediction_log', sa.Column('model_id', sa.Integer(), nullable=True))
    op.add_column('prediction_log', sa.Column('ecowitt_prediction_result', sa.Integer(), nullable=True))
    op.add_column('prediction_log', sa.Column('wunderground_prediction_result', sa.Integer(), nullable=True))
    
    # Copy data kembali
    op.execute("""
        UPDATE prediction_log 
        SET model_id = xgboost_model_id
        WHERE xgboost_model_id IS NOT NULL
    """)
    
    # Buat foreign key lama
    op.create_foreign_key(
        'prediction_log_ibfk_3',
        'prediction_log', 'model',
        ['model_id'], ['id']
    )
    
    op.create_foreign_key(
        'prediction_log_ibfk_4',
        'prediction_log', 'label',
        ['ecowitt_prediction_result'], ['id']
    )
    
    op.create_foreign_key(
        'prediction_log_ibfk_5',
        'prediction_log', 'label',
        ['wunderground_prediction_result'], ['id']
    )
    
    # Hapus foreign key baru
    try:
        op.drop_constraint('fk_prediction_log_xgboost_model', 'prediction_log', type_='foreignkey')
    except Exception:
        pass
    
    try:
        op.drop_constraint('fk_prediction_log_lstm_model', 'prediction_log', type_='foreignkey')
    except Exception:
        pass
    
    # Hapus kolom baru
    op.drop_column('prediction_log', 'xgboost_model_id')
    op.drop_column('prediction_log', 'lstm_model_id')
    op.drop_column('prediction_log', 'ecowitt_predict_result')
    op.drop_column('prediction_log', 'wunderground_predict_result')
    op.drop_column('prediction_log', 'ecowitt_predict_data')
    op.drop_column('prediction_log', 'wunderground_predict_data')
