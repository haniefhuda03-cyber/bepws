# 📖 TUWS Weather API - Manual Book

**Panduan Lengkap Penggunaan Aplikasi dari Awal hingga Akhir**

**Version:** 3.0  
**Last Updated:** December 23, 2025

---

## 📋 Daftar Isi

1. [Pendahuluan](#1-pendahuluan)
2. [Prasyarat Sistem](#2-prasyarat-sistem)
3. [Instalasi & Setup](#3-instalasi--setup)
4. [Konfigurasi](#4-konfigurasi)
5. [Menjalankan Aplikasi](#5-menjalankan-aplikasi)
6. [Testing & Validasi](#6-testing--validasi)
7. [Penggunaan API](#7-penggunaan-api)
8. [Deployment Produksi](#8-deployment-produksi)
9. [Troubleshooting](#9-troubleshooting)
10. [Maintenance](#10-maintenance)

---

## 1. Pendahuluan

### 1.1 Tentang TUWS Weather API

TUWS (Telkom University Weather Station) adalah backend API untuk sistem prediksi cuaca yang menggunakan:

- **LSTM (Long Short-Term Memory):** Prediksi intensitas hujan 24 jam ke depan
- **XGBoost:** Klasifikasi arah potensi hujan (9 kategori)

### 1.2 Fitur Utama

| Fitur | Deskripsi |
|-------|-----------|
| 🌤️ **Real-time Weather** | Data cuaca terkini dari Ecowitt & Wunderground |
| 🔮 **Predictions** | Prediksi hujan LSTM (24 jam) & XGBoost (klasifikasi) |
| 📊 **Historical Data** | Riwayat cuaca dengan filtering & pagination |
| 📈 **Graph Data** | Data untuk visualisasi chart |
| 🔐 **Security** | X-API-KEY authentication + Rate limiting |
| 🌐 **CORS** | Cross-Origin Resource Sharing untuk frontend |

### 1.3 Arsitektur Sistem

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│                  (React/Vue/Angular/etc)                     │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP/HTTPS
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     TUWS Backend API                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ API Biasa   │  │  API v3     │  │  Background Jobs    │  │
│  │   /api/*    │  │ /api/v3/*   │  │  (APScheduler)      │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│           │               │                   │              │
│           └───────────────┴───────────────────┘              │
│                           │                                  │
│  ┌────────────────────────▼─────────────────────────────┐   │
│  │              Service Layer                            │   │
│  │  ┌─────────────────┐  ┌─────────────────────────┐    │   │
│  │  │ prediction_     │  │  serializers.py         │    │   │
│  │  │ service.py      │  │  (Data transformation)  │    │   │
│  │  └─────────────────┘  └─────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                  │
│  ┌────────────────────────▼─────────────────────────────┐   │
│  │              ML Models                                │   │
│  │  ┌─────────────────┐  ┌─────────────────────────┐    │   │
│  │  │  LSTM (Keras)   │  │  XGBoost (Scikit)       │    │   │
│  │  │  24h Rainfall   │  │  Rain Direction         │    │   │
│  │  └─────────────────┘  └─────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                       MySQL Database                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   label     │  │   model     │  │  prediction_log     │  │
│  │  (9 rows)   │  │  (2 rows)   │  │  (weather + pred)   │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────────────────┐  ┌─────────────────────────┐   │
│  │  weather_log_ecowitt    │  │ weather_log_wunderground│   │
│  └─────────────────────────┘  └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Prasyarat Sistem

### 2.1 Software Requirements

| Software | Minimum Version | Recommended |
|----------|-----------------|-------------|
| Python | 3.10 | 3.11+ |
| MySQL | 5.7 | 8.0+ |
| pip | 21.0 | Latest |
| Git | 2.30 | Latest |

### 2.2 Hardware Requirements

| Resource | Development | Production |
|----------|-------------|------------|
| RAM | 4 GB | 8+ GB |
| CPU | 2 cores | 4+ cores |
| Storage | 5 GB | 20+ GB |

### 2.3 Verifikasi Instalasi

```bash
# Cek Python
python --version
# Output: Python 3.11.x

# Cek pip
pip --version
# Output: pip 23.x.x

# Cek MySQL
mysql --version
# Output: mysql Ver 8.0.x

# Cek Git
git --version
# Output: git version 2.x.x
```

---

## 3. Instalasi & Setup

### 3.1 Clone Repository

```bash
# Clone dari repository
git clone <repository-url> tuwsbe
cd tuwsbe
```

### 3.2 Setup Virtual Environment

**Windows:**
```powershell
# Buat virtual environment
python -m venv .venv

# Aktivasi
.venv\Scripts\activate

# Verifikasi (prompt harus berubah)
# (.venv) C:\path\to\tuwsbe>
```

**Linux/Mac:**
```bash
# Buat virtual environment
python3 -m venv .venv

# Aktivasi
source .venv/bin/activate

# Verifikasi
# (.venv) user@host:~/tuwsbe$
```

### 3.3 Install Dependencies

```bash
# Upgrade pip terlebih dahulu
pip install --upgrade pip

# Install semua dependencies
pip install -r requirements.txt
```

**Output yang diharapkan:**
```
Successfully installed Flask-2.x.x SQLAlchemy-2.x.x tensorflow-2.x.x ...
```

### 3.4 Setup Database MySQL

**Login ke MySQL:**
```bash
mysql -u root -p
```

**Buat Database:**
```sql
-- Buat database
CREATE DATABASE tuws_pws CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- (Opsional) Buat user khusus untuk keamanan
CREATE USER 'tuws_user'@'localhost' IDENTIFIED BY 'secure_password_here';
GRANT ALL PRIVILEGES ON tuws_pws.* TO 'tuws_user'@'localhost';
FLUSH PRIVILEGES;

-- Verifikasi
SHOW DATABASES;

EXIT;
```

### 3.5 Konfigurasi Environment

**Buat file `.env`:**
```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

**Edit file `.env`:**
```dotenv
# ============================================
# DATABASE CONFIGURATION
# ============================================
# Format: mysql+pymysql://user:password@host:port/database
DATABASE_URL="mysql+pymysql://root@localhost:3306/tuws_pws"
# Atau dengan password:
# DATABASE_URL="mysql+pymysql://root:password@localhost:3306/tuws_pws"
# Atau dengan user khusus:
# DATABASE_URL="mysql+pymysql://tuws_user:secure_password@localhost:3306/tuws_pws"

# ============================================
# FLASK CONFIGURATION
# ============================================
FLASK_APP=run.py
FLASK_ENV=development
FLASK_DEBUG=1
FLASK_HOST=127.0.0.1
FLASK_PORT=5000

# ============================================
# SECURITY
# ============================================
# Secret key untuk session (akan di-generate otomatis jika kosong)
SECRET_KEY=""

# API Key untuk akses endpoint (header: X-API-KEY)
API_READ_KEY="tuws2526"

# ============================================
# EXTERNAL WEATHER API (Opsional)
# ============================================
# Wunderground
WUNDERGROUND_URL=""
WUNDERGROUND_API_KEY=""
WUNDERGROUND_STATION_ID=""

# Ecowitt
ECO_APP_KEY=""
ECO_API_KEY=""
ECO_MAC=""

# ============================================
# ADVANCED SETTINGS
# ============================================
# Auto migrate saat startup
AUTO_MIGRATE=false

# Load .env file
LOAD_DOTENV=true

# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO

# Rate limiting
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# Disable scheduler untuk testing
DISABLE_SCHEDULER_FOR_TESTS=false
```

### 3.6 Jalankan Migrasi Database

```bash
# Jika folder migrations belum ada
flask db init

# Generate file migrasi dari models
flask db migrate -m "Initial migration"

# Terapkan migrasi ke database
flask db upgrade
```

**Output yang diharapkan:**
```
INFO  [alembic.runtime.migration] Context impl MySQLImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> xxxx, Initial migration
[db_seed] Seeded table `label`.
[db_seed] Seeded table `model` with 2 entries.
```

### 3.7 Verifikasi Database

```bash
mysql -u root -p tuws_pws
```

```sql
-- Cek tabel
SHOW TABLES;
-- Output: label, model, prediction_log, weather_log_ecowitt, weather_log_wunderground

-- Cek data label
SELECT * FROM label;
-- Output: 9 rows (Cerah/Berawan, Utara, Timur Laut, dst)

-- Cek data model
SELECT * FROM model;
-- Output: 2 rows (default_xgboost, default_lstm)

EXIT;
```

---

## 4. Konfigurasi

### 4.1 Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABASE_URL` | Database connection string | ✅ | SQLite (dev) |
| `API_READ_KEY` | API key untuk autentikasi | ❌ | (no auth) |
| `SECRET_KEY` | Flask secret key | ❌ | auto-generated |
| `FLASK_ENV` | development/production | ❌ | production |
| `LOG_LEVEL` | DEBUG/INFO/WARNING/ERROR | ❌ | INFO |
| `RATE_LIMIT_REQUESTS` | Max requests per window | ❌ | 100 |
| `RATE_LIMIT_WINDOW` | Window dalam detik | ❌ | 60 |

### 4.2 ML Models

Model machine learning harus ada di folder `ml_models/`:

```
ml_models/
├── model_lstm_regresi_telkom.keras       # LSTM model (wajib)
├── model_prediksi_hujan_darimana_XGBoost.joblib  # XGBoost model (wajib)
└── scalerFIT_split.joblib                # Scaler untuk LSTM (wajib)
```

**Catatan:** Jika model tidak tersedia, sistem akan menggunakan Mock Model untuk development.

---

## 5. Menjalankan Aplikasi

### 5.1 Development Mode

```bash
# Pastikan virtual environment aktif
# (.venv) C:\path\to\tuwsbe>

# Jalankan aplikasi
python run.py
```

**Output yang diharapkan:**
```
INFO - SECRET_KEY tidak ditemukan di env; dibuat/diambil di instance/secret_key
INFO - Cache: menggunakan simple (in-memory) cache.
INFO - Scheduler initialized but not started. Start it from run.py.
INFO - Registered API blueprints: /api (legacy), /api/v3
INFO - Model ML berhasil diinisialisasi saat startup.
INFO - Job 'fetch-weather' didaftarkan (interval 5 menit).
INFO - Job 'hourly-prediction' didaftarkan (cron setiap jam).
 * Serving Flask app 'run.py'
 * Debug mode: on
 * Running on http://127.0.0.1:5000
Press CTRL+C to quit
```

### 5.2 Akses API

Buka browser atau gunakan curl:

```bash
# Health check (tanpa auth)
curl http://localhost:5000/api/health

# Health check API v3
curl http://localhost:5000/api/v3/health
```

**Response:**
```json
{
  "ok": true,
  "details": {
    "db": "ok",
    "scheduler": "running"
  }
}
```

---

## 6. Testing & Validasi

### 6.1 Quick Test dengan cURL

```bash
# 1. Health Check
curl http://localhost:5000/api/health

# 2. Data dengan API Key
curl -H "X-API-KEY: tuws2526" http://localhost:5000/api/data?type=general

# 3. History
curl -H "X-API-KEY: tuws2526" "http://localhost:5000/api/history?page=1&per_page=5"

# 4. API v3 Current Weather
curl -H "X-API-KEY: tuws2526" http://localhost:5000/api/v3/weather/current

# 5. Labels dari database
curl -H "X-API-KEY: tuws2526" http://localhost:5000/api/v3/labels

# 6. Models dari database
curl -H "X-API-KEY: tuws2526" http://localhost:5000/api/v3/models
```

### 6.2 Automated Tests

```bash
# Test API v3
python -m tests.test_api_v3

# Test prediction flow
python -m tests.test_prediction_flow

# Semua tests dengan pytest
pytest tests/ -v
```

### 6.3 Testing dengan Postman

1. **Import Collection:**
   - File > Import
   - Pilih `postman/TUWS_API_Collection.postman_collection.json`

2. **Import Environment:**
   - File > Import
   - Pilih `postman/TUWS_Local.postman_environment.json`

3. **Set Environment:**
   - Pilih "TUWS Local Development" di dropdown
   - Edit variable `api_key` jika perlu

4. **Run Tests:**
   - Buka folder yang diinginkan
   - Klik request dan Send

---

## 7. Penggunaan API

### 7.1 Autentikasi

Semua endpoint (kecuali `/health`) memerlukan header:

```
X-API-KEY: your-api-key
```

**Contoh cURL:**
```bash
curl -H "X-API-KEY: tuws2526" http://localhost:5000/api/data?type=general
```

**Contoh JavaScript (Fetch):**
```javascript
const response = await fetch('http://localhost:5000/api/v3/weather/current', {
  headers: {
    'X-API-KEY': 'tuws2526'
  }
});
const data = await response.json();
```

### 7.2 Endpoint Utama

| Endpoint | Deskripsi |
|----------|-----------|
| `GET /api/health` | Status sistem |
| `GET /api/data?type=general` | Data cuaca terkini |
| `GET /api/data?type=hourly&model=lstm` | Prediksi LSTM 24 jam |
| `GET /api/data?type=hourly&model=xgboost` | Klasifikasi XGBoost |
| `GET /api/history` | Riwayat data |
| `GET /api/graph?range=weekly&datatype=temperature` | Data grafik |

### 7.3 API v3 (Recommended)

| Endpoint | Deskripsi |
|----------|-----------|
| `GET /api/v3/health` | Status sistem |
| `GET /api/v3/weather/current` | Data cuaca terkini |
| `GET /api/v3/weather/hourly` | Prediksi per jam |
| `GET /api/v3/weather/history` | Riwayat dengan pagination |
| `GET /api/v3/weather/graph` | Data grafik |
| `GET /api/v3/labels` | Daftar label prediksi |
| `GET /api/v3/models` | Daftar model ML |

**Lihat dokumentasi lengkap di:** `docs/COMPLETE_API_DOCUMENTATION.md`

---

## 8. Deployment Produksi

### 8.1 Checklist Sebelum Deploy

- [ ] Set `FLASK_ENV=production`
- [ ] Set `FLASK_DEBUG=0`
- [ ] Generate `SECRET_KEY` yang kuat
- [ ] Set `API_READ_KEY` yang aman
- [ ] Konfigurasi database produksi
- [ ] Backup ML models
- [ ] Tes semua endpoint

### 8.2 Docker Deployment

**Build Image:**
```bash
docker build -t tuws-backend .
```

**Run Container:**
```bash
docker run -d \
  --name tuws-api \
  -p 5000:5000 \
  --env-file .env.production \
  tuws-backend
```

**Docker Compose:**
```bash
docker-compose up -d
```

### 8.3 Production Settings

```dotenv
# .env.production
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY="super-secure-random-key-here-64-chars-min"
API_READ_KEY="production-api-key-here"
DATABASE_URL="mysql+pymysql://user:password@db-host:3306/tuws_prod"
LOG_LEVEL=WARNING
RATE_LIMIT_REQUESTS=1000
RATE_LIMIT_WINDOW=60
```

### 8.4 Gunicorn (Recommended for Production)

```bash
pip install gunicorn

gunicorn -w 4 -b 0.0.0.0:5000 "run:app"
```

---

## 9. Troubleshooting

### 9.1 Database Connection Error

**Error:**
```
sqlalchemy.exc.OperationalError: (pymysql.err.OperationalError) (2003, "Can't connect to MySQL server")
```

**Solusi:**
1. Pastikan MySQL berjalan: `sudo systemctl status mysql`
2. Cek DATABASE_URL di .env
3. Verifikasi user/password MySQL

### 9.2 Model ML Tidak Ditemukan

**Error:**
```
WARNING - File model tidak ditemukan di ml_models/...
```

**Solusi:**
1. Pastikan file model ada di folder `ml_models/`
2. Untuk development, sistem akan otomatis menggunakan Mock Model

### 9.3 Migration Error

**Error:**
```
alembic.util.exc.CommandError: Can't locate revision identified by 'xxx'
```

**Solusi:**
```bash
# Reset migrations
rm -rf migrations/
flask db init
flask db migrate -m "Fresh start"
flask db upgrade
```

### 9.4 Rate Limit Exceeded

**Error:**
```json
{"ok": false, "error": {"code": "RATE_LIMIT_EXCEEDED"}}
```

**Solusi:**
- Tunggu sesuai `Retry-After` header
- Atau tingkatkan `RATE_LIMIT_REQUESTS` di .env

### 9.5 Import Error TensorFlow

**Error:**
```
ImportError: DLL load failed while importing _pywrap_tensorflow
```

**Solusi (Windows):**
1. Install Visual C++ Redistributable
2. Atau install TensorFlow CPU: `pip install tensorflow-cpu`

---

## 10. Maintenance

### 10.1 Backup Database

```bash
# Backup
mysqldump -u root -p tuws_pws > backup_$(date +%Y%m%d).sql

# Restore
mysql -u root -p tuws_pws < backup_20241223.sql
```

### 10.2 Log Monitoring

```bash
# Lihat log
tail -f logs/app.log

# Rotate logs manual
mv logs/app.log logs/app.log.$(date +%Y%m%d)
```

### 10.3 Update Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Upgrade semua packages
pip install --upgrade -r requirements.txt

# Check outdated
pip list --outdated
```

### 10.4 Database Cleanup (Opsional)

```sql
-- Hapus data lama (lebih dari 30 hari)
DELETE FROM prediction_log 
WHERE created_at < DATE_SUB(NOW(), INTERVAL 30 DAY);

-- Optimize tables
OPTIMIZE TABLE prediction_log;
OPTIMIZE TABLE weather_log_ecowitt;
OPTIMIZE TABLE weather_log_wunderground;
```

---

## 📞 Support

Jika mengalami masalah:

1. Cek dokumentasi di folder `docs/`
2. Lihat log di `logs/app.log`
3. Jalankan tests untuk identifikasi masalah
4. Hubungi tim development

---

**© 2025 TUWS Development Team**
