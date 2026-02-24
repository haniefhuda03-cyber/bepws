# TUWS Weather API Backend

Backend API untuk sistem prediksi cuaca menggunakan LSTM dan XGBoost.

---

## 🚀 Quick Start (Pertama Kali)

### Prasyarat
- Python 3.10+ 
- PostgreSQL Server (running)
- Git
- Redis *(opsional — jika tidak ada, cache fallback ke in-memory)*

---

## 📋 Langkah Setup Lengkap

### Step 1: Clone & Masuk Direktori
```bash
cd tuwsbe-fix
```

### Step 2: Buat Virtual Environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux/Mac
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Buat Database PostgreSQL
```sql
-- Login ke PostgreSQL
psql -U postgres

-- Buat database
CREATE DATABASE tuws_pws;

-- (Opsional) Buat user khusus
CREATE USER tuws_user WITH PASSWORD 'password123';
GRANT ALL PRIVILEGES ON DATABASE tuws_pws TO tuws_user;

\q
```

### Step 5: Konfigurasi Environment (.env)

File `.env` di-load **otomatis** saat aplikasi startup. Tidak perlu set environment variable apapun untuk loading-nya.

Isi file `.env`:
```dotenv
# ============================================================
# DATABASE
# ============================================================
DATABASE_URL="postgresql://postgres@localhost:5432/tuws_pws"
# atau dengan password:
# DATABASE_URL="postgresql://postgres:password@localhost:5432/tuws_pws"

# ============================================================
# FLASK
# ============================================================
FLASK_APP=run.py
FLASK_ENV=development
FLASK_DEBUG=1
FLASK_HOST=127.0.0.1
FLASK_PORT=5000

# ============================================================
# KEAMANAN
# ============================================================
# Secret Key (generate random, untuk session & CSRF)
SECRET_KEY="your-random-secret-key-here"

# API Key untuk akses endpoint v3 (header X-APP-KEY)
API_READ_KEY="tuws2526"

# ============================================================
# WEATHER API KEYS
# ============================================================
WUNDERGROUND_URL="https://api.weather.com/..."
ECO_APP_KEY="your-ecowitt-app-key"
ECO_API_KEY="your-ecowitt-api-key"
ECO_MAC="your-device-mac"

# ============================================================
# CACHE (Redis — opsional)
# ============================================================
# Jika tidak di-set, otomatis fallback ke in-memory cache
REDIS_URL="redis://localhost:6379/0"
# REDIS_URL="redis://:password@hostname:6379/0"  # dengan auth

# ============================================================
# CORS
# ============================================================
# Comma-separated origins (default: * jika tidak di-set)
CORS_ORIGINS="*"

# ============================================================
# RATE LIMITING
# ============================================================
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# ============================================================
# CONSOLE STATION (opsional)
# ============================================================
CONSOLE_ENDPOINT_ENABLED=true
CONSOLE_KEY="your-console-secret-key"
CONSOLE_IP_WHITELIST="192.168.1.100,10.0.0.50"
```

### Step 6: Jalankan Migrasi Database
```bash
# Inisialisasi migrasi (jika folder migrations belum ada)
flask db init

# Generate migrasi dari models
flask db migrate -m "Initial migration"

# Terapkan migrasi ke database
flask db upgrade
```

### Step 7: Seed Data Awal (Label & Model)
```bash
# Jalankan seeding via Python
python -c "from app.db_seed import seed_labels_and_models; seed_labels_and_models()"
```

Atau otomatis saat aplikasi pertama kali jalan.

### Step 8: Jalankan Aplikasi
```bash
python run.py
```

Output yang diharapkan:
```
INFO - SECRET_KEY diambil dari environment.
INFO - Cache: menggunakan simple (in-memory) cache.
INFO - [Scheduler] Job 'fetch-weather' registered. Next: 10:20:00 WIB
INFO - [Scheduler] Job 'hourly-prediction-safety' registered
INFO - CORS enabled for API v3 (origins: *)
INFO - Registered API blueprint: /api/v3
INFO - Swagger UI available at: /api/docs
 * Running on http://127.0.0.1:5000
```

### Step 9: Test API
```bash
# Health check (tanpa auth)
curl http://127.0.0.1:5000/api/v3/health

# Cuaca terkini (dengan API key)
curl -H "X-APP-KEY: tuws2526" http://127.0.0.1:5000/api/v3/weather/current
```

---

## 📖 Swagger UI (Dokumentasi Interaktif)

Buka di browser:
```
http://127.0.0.1:5000/api/docs
```

Fitur:
- Lihat semua endpoint dan parameter
- Coba request langsung dari browser
- Download OpenAPI specification: `GET /api/v3/openapi.yaml`

---

## 📡 API v3 Endpoints

**Base URL**: `/api/v3`  
**Authentication**: Header `X-APP-KEY` (kecuali `/health` dan `/weather/console`)  
**Rate Limit**: 100 requests per 60 detik

| Method | Endpoint | Auth | Deskripsi |
|--------|----------|------|-----------|
| GET | `/api/v3/health` | Tidak | Health check sistem |
| GET | `/api/v3/weather/current` | Ya | Data cuaca terkini |
| GET | `/api/v3/weather/predict` | Ya | Prediksi ML (LSTM/XGBoost) |
| GET | `/api/v3/weather/details` | Ya | Detail cuaca (UVI, solar, tekanan) |
| GET | `/api/v3/weather/history` | Ya | Histori cuaca (pagination + filter) |
| GET | `/api/v3/weather/graph` | Ya | Data grafik (agregasi harian) |
| POST/GET | `/api/v3/weather/console` | Console Key | Terima data console station |

### Query Parameters

| Parameter | Endpoint | Values |
|-----------|----------|--------|
| `source` | current, predict, details, history, graph | `ecowitt` \| `wunderground` (default: `ecowitt`) |
| `model` | predict | `lstm` \| `xgboost` (default: `lstm`) |
| `limit` | predict | `1-24` (default: `12`, LSTM only) |
| `page` | history | `≥ 1` (default: `1`) |
| `per_page` | history | `1-10` (default: `5`) |
| `start_date` | history | ISO 8601 datetime |
| `end_date` | history | ISO 8601 datetime |
| `sort` | history | `newest` \| `oldest` (default: `newest`) |
| `range` | graph | `weekly` \| `monthly` (**wajib**) |
| `datatype` | graph | `temperature` \| `humidity` \| `rainfall` \| `wind_speed` \| `uvi` \| `solar_radiation` \| `relative_pressure` (**wajib**) |
| `month` | graph | `1-12` (wajib untuk `range=monthly`) |
| `year` | graph | `YYYY` (default: tahun ini) |

### Response Format
```json
{
  "meta": {
    "status": "success",
    "code": 200,
    "timestamp": "2026-02-24T03:10:00+00:00",
    "source": "ecowitt"
  },
  "data": { ... }
}
```

### Error Response
```json
{
  "meta": {
    "status": "error",
    "code": 400,
    "timestamp": "..."
  },
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "Human readable message"
  }
}
```

📄 **Dokumentasi lengkap**: lihat [`docs/API_V3_REFERENCE.md`](docs/API_V3_REFERENCE.md)

---

## ⏰ Timezone & Waktu

| Aspek | Format |
|-------|--------|
| Database | UTC |
| API response `timestamp` | UTC ISO 8601 (`+00:00`) |
| Predict `time_target_predict` | **WIB** (UTC+7) |
| Graph grouping | Per hari **WIB** |
| History filter (`start_date`/`end_date`) | Menghormati offset yang dikirim client. Tanpa offset = dianggap UTC |

**Contoh filter history berdasarkan WIB:**
```http
GET /api/v3/weather/history?start_date=2026-02-01T00:00:00+07:00&end_date=2026-02-01T23:59:59+07:00
```

---

## 🔄 Perintah Migrasi Database

```bash
flask db current           # Status migrasi saat ini
flask db migrate -m "msg"  # Generate migrasi baru
flask db upgrade           # Terapkan ke database
flask db downgrade         # Rollback migrasi terakhir
flask db history           # History migrasi
```

---

## 🧪 Menjalankan Tests

```bash
# Semua tests dengan pytest
pytest tests/ -v

# Test audit fixes saja
pytest tests/test_audit_fixes_local.py -v

# Test spesifik
pytest tests/test_audit_fixes_local.py::TestApiEndpoints -v
```

---

## 📁 Project Structure

```
tuwsbe-fix/
├── app/
│   ├── __init__.py              # Flask app factory + Swagger UI
│   ├── api_v3.py                # API v3 (RESTful) endpoints
│   ├── models.py                # SQLAlchemy models
│   ├── serializers.py           # Data serialization & DB queries
│   ├── jobs.py                  # Scheduler jobs (fetch, predict)
│   ├── cache.py                 # Redis + in-memory fallback cache
│   ├── common/
│   │   └── helpers.py           # Konversi unit, timezone, utilities
│   └── services/
│       └── prediction_service.py  # ML prediction pipeline
├── ml_models/                   # Trained ML models (.pkl, .h5)
├── migrations/                  # Database migrations
├── tests/                       # Test suites
├── docs/
│   ├── API_V3_REFERENCE.md      # Dokumentasi API lengkap
│   └── openapi.yaml             # OpenAPI 3.0.3 specification
├── run.py                       # Entry point
├── requirements.txt
└── .env                         # Environment variables
```

---

## 🔧 Environment Variables

| Variable | Deskripsi | Default |
|----------|-----------|---------|
| `DATABASE_URL` | PostgreSQL connection string | *(wajib)* |
| `SECRET_KEY` | Flask secret key | Auto-generate ke `instance/` |
| `API_READ_KEY` | API key untuk header `X-APP-KEY` | *(tanpa auth jika kosong)* |
| `FLASK_HOST` | Host binding | `127.0.0.1` |
| `FLASK_PORT` | Port | `5000` |
| `FLASK_DEBUG` | Debug mode | `0` |
| `REDIS_URL` | Redis connection URL | Fallback in-memory |
| `CORS_ORIGINS` | CORS allowed origins | `*` |
| `RATE_LIMIT_REQUESTS` | Max requests per window | `100` |
| `RATE_LIMIT_WINDOW` | Window duration (detik) | `60` |
| `CONSOLE_ENDPOINT_ENABLED` | Aktifkan console endpoint | `true` |
| `CONSOLE_KEY` | Secret key untuk console auth | *(wajib untuk console)* |
| `CONSOLE_IP_WHITELIST` | IP whitelist (comma-separated) | *(opsional)* |
| `ECO_APP_KEY` | Ecowitt application key | *(opsional)* |
| `ECO_API_KEY` | Ecowitt API key | *(opsional)* |
| `ECO_MAC` | Ecowitt device MAC | *(opsional)* |
| `WUNDERGROUND_URL` | Wunderground API URL | *(opsional)* |
