# TUWS Weather API Backend — Manual Book

Backend API untuk sistem monitoring & prediksi cuaca **TUWS** (Telkom University Weather Station).  
Menggunakan **LSTM** untuk prediksi intensitas hujan 24 jam ke depan dan **XGBoost** untuk klasifikasi arah hujan.

---

## Daftar Isi

1. [Arsitektur Sistem](#-arsitektur-sistem)
2. [Quick Start](#-quick-start-pertama-kali)
3. [Konfigurasi Environment](#step-5-konfigurasi-environment-env)
4. [API Endpoints](#-api-v3-endpoints)
5. [Timezone & Waktu](#-timezone--waktu)
6. [Pipeline Prediksi ML](#-pipeline-prediksi-ml)
7. [Scheduler & Auto-Fetch](#-scheduler--auto-fetch)
8. [Caching](#-caching)
9. [Production Deployment](#-production-deployment-vps--cloud)
10. [Database & Migrasi](#-perintah-migrasi-database)
11. [Testing](#-menjalankan-tests)
12. [Struktur Proyek](#-project-structure)
13. [Environment Variables](#-environment-variables)

---

## 🏗 Arsitektur Sistem

```
┌─────────────────────────────────────────────────────────────────┐
│                        TUWS Backend                             │
│                                                                 │
│  ┌──────────┐   ┌────────────┐   ┌──────────────┐               │
│  │ Ecowitt  │   │Wunderground│   │ Console Stn  │ ← Data Source │
│  └────┬─────┘   └─────┬──────┘   └──────┬───────┘               │
│       │               │                 │                       │
│       ▼               ▼                 ▼                       │
│  ┌─────────────────────────────────────────┐                    │
│  │       APScheduler (setiap 5 menit)      │                    │
│  │       fetch_and_store_weather()         │                    │
│  └─────────────────┬───────────────────────┘                    │
│                    │                                            │
│       ┌────────────┼────────────┐                               │
│       ▼            ▼            ▼                               │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                            │
│  │ XGBoost │ │ XGBoost │ │ XGBoost │ ← Klasifikasi Arah         │
│  │   +     │ │   +     │ │   +     │    Hujan (9 kelas)         │
│  │  LSTM   │ │  LSTM   │ │  LSTM   │ ← Prediksi Intensitas      │
│  │ecowitt  │ │console  │ │wunder.  │    Hujan 24 jam            │
│  └────┬────┘ └────┬────┘ └────┬────┘                            │
│       │           │           │   ← 3 thread parallel           │
│       └───────────┼───────────┘                                 │
│                   ▼                                             │
│  ┌────────────────────────────────┐                             │
│  │       PostgreSQL Database      │                             │
│  │  weather_log_* + prediction_*  │                             │
│  └────────────────┬───────────────┘                             │
│                   │                                             │
│  ┌────────────────┼───────────────┐                             │
│  │          Redis Cache           │                             │
│  │  (fallback: in-memory dict)    │                             │
│  └────────────────┬───────────────┘                             │
│                   │                                             │
│                   ▼                                             │ 
│  ┌────────────────────────────────┐                             │
│  │      Flask REST API v3         │                             │ 
│  │    /api/v3/weather/*           │                             │
│  └────────────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

**Komponen Utama:**

| Komponen | Teknologi | Fungsi |
|----------|-----------|--------|
| Web Framework | Flask + Gunicorn | REST API |
| Database | PostgreSQL 15 | Penyimpanan data cuaca & prediksi |
| Cache | Redis (+ in-memory fallback) | Response caching |
| Scheduler | APScheduler | Auto-fetch data tiap 5 menit |
| ML Classification | XGBoost | Prediksi arah hujan (9 kelas) |
| ML Regression | LSTM (TensorFlow/Keras) | Prediksi intensitas hujan 24 jam |
| Scaler | MinMaxScaler (sklearn) | Normalisasi fitur LSTM |

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
APPKEY="your-api-key-here"

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
CONSOLE_IP_WHITELIST="192.168.4.1"
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
curl -H "X-APP-KEY: your-key" http://127.0.0.1:5000/api/v3/weather/current
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
**Authentication**: Header `X-APP-KEY` (kecuali `/health` dan `/console`)  
**Rate Limit**: 100 requests per 60 detik

| Method | Endpoint | Auth | Deskripsi |
|--------|----------|------|-----------|
| GET | `/api/v3/health` | Tidak | Health check sistem |
| GET | `/api/v3/weather/current` | Ya | Data cuaca terkini |
| GET | `/api/v3/weather/predict` | Ya | Prediksi ML (LSTM/XGBoost) |
| GET | `/api/v3/weather/details` | Ya | Detail cuaca (UVI, solar, tekanan) |
| GET | `/api/v3/weather/history` | Ya | Histori cuaca (pagination + filter) |
| GET | `/api/v3/weather/graph` | Ya | Data grafik (agregasi harian) |
| POST/GET | `/api/v3/console` | IP Whitelist | Terima data console station (port 5000) |

### Query Parameters

| Parameter | Endpoint | Values |
|-----------|----------|--------|
| `source` | current, predict, details, history, graph | `ecowitt` \| `wunderground` (default: `ecowitt`) |
| `model` | predict | `lstm` \| `xgboost` (default: `lstm`) |
| `limit` | predict | `1-24` (default: `12`, LSTM only. **Banned for XGBoost**) |
| `page` | history | `≥ 1` (default: `1`) |
| `per_page` | history | `1-10` (default: `5`) |
| `start_date` | history | Multi-format datetime — lihat [Format Tanggal](#format-tanggal-yang-didukung) |
| `end_date` | history | Multi-format datetime — lihat [Format Tanggal](#format-tanggal-yang-didukung) |
| `sort` | history | `newest` \| `oldest` (default: `newest`) |
| `range` | graph | `weekly` \| `monthly` (**wajib**) |
| `datatype` | graph | `temperature` \| `humidity` \| `rainfall` \| `wind_speed` \| `uvi` \| `solar_radiation` \| `relative_pressure` (**wajib**) |
| `month` | graph | `1-12` (wajib untuk `range=monthly`. **Banned untuk weekly**) |

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

### Format Tanggal yang Didukung

Parameter `start_date` dan `end_date` pada endpoint History menerima berbagai format:

| Format | Contoh | Timezone |
|--------|--------|----------|
| ISO 8601 + Z | `2026-02-01T00:00:00Z` | UTC eksplisit |
| ISO 8601 + offset | `2026-02-01T07:00:00+07:00` | WIB eksplisit |
| Date only (YYYY-MM-DD) | `2026-02-01` | **WIB diasumsikan** |
| Date slash (YYYY/MM/DD) | `2026/02/01` | **WIB diasumsikan** |
| DD-MM-YYYY | `01-02-2026` | **WIB diasumsikan** |
| DD/MM/YYYY | `01/02/2026` | **WIB diasumsikan** |
| Compact (YYYYMMDD) | `20260201` | **WIB diasumsikan** |
| Date + time | `2026-02-01 14:30:00` | **WIB diasumsikan** |
| Date + short time | `2026-02-01 14:30` | **WIB diasumsikan** |

> **Catatan:** Jika tanpa timezone info, server mengasumsikan input dalam **WIB (UTC+7)** karena konteks API ini untuk Indonesia.  
> Contoh: `2026-02-01` diparsing sebagai `2026-02-01 00:00:00 WIB` = `2026-01-31 17:00:00 UTC`.

📄 **Dokumentasi API lengkap**: lihat [`docs/API_V3_REFERENCE.md`](docs/API_V3_REFERENCE.md)

---

## ⏰ Timezone & Waktu

| Aspek | Format | Keterangan |
|-------|--------|------------|
| Database | **UTC** | Semua `created_at` dan `date_utc` disimpan UTC |
| Meta `timestamp` | **UTC** | `2026-03-02T03:10:00+00:00` |
| Data row `timestamp` | **UTC** | Endpoint history, current, details |
| Predict `time_target_predict` | **WIB** | `"11:00"` = jam 11 pagi WIB |
| Predict `date_target_predict` | **WIB** | `"02-03-26"` = 2 Maret 2026 WIB |
| Graph `date` per hari | **WIB** | Pengelompokan per hari kalender WIB |
| Graph `status` | **WIB** | `today` ditentukan dari jam WIB saat ini |
| History filter input | **WIB** (default) | Jika tidak ada offset, dianggap WIB |

### Mengapa Penting?

Data jam 01:00 WIB = 18:00 UTC **hari sebelumnya**. Jika dikategorikan berdasarkan UTC, data tersebut masuk ke hari yang salah. Oleh karena itu:

- **Graph API**: Pengelompokan harian menggunakan WIB  
  ```sql
  GROUP BY date(timezone('Asia/Jakarta', timezone('UTC', created_at)))
  ```
- **History filter**: Input tanpa timezone diasumsikan WIB  
  `2026-03-01` → `2026-03-01 00:00 WIB` → `2026-02-28 17:00 UTC`

### Contoh Filter History

| Tujuan | Request | Penjelasan |
|--------|---------|------------|
| Data 1 Maret WIB penuh | `start_date=2026-03-01&end_date=2026-03-01T23:59:59+07:00` | 00:00–23:59 WIB |
| Data 1 Maret UTC penuh | `start_date=2026-03-01T00:00:00Z&end_date=2026-03-01T23:59:59Z` | 00:00–23:59 UTC |
| Tanpa offset (WIB default) | `start_date=01-03-2026&end_date=31-03-2026` | DD-MM-YYYY, diasumsikan WIB |

---

## 🤖 Pipeline Prediksi ML

### Ringkasan Model

| Model | Tipe | Input | Output |
|-------|------|-------|--------|
| **XGBoost** | Klasifikasi | 6 fitur cuaca terkini (1 row) | 1 label arah hujan (kelas 0–8) |
| **LSTM** | Regresi | 9 fitur × 144 timestep (12 jam) | 24 nilai intensitas hujan (mm/h per jam) |

### Alur LSTM End-to-End

```
DB (154 rows terbaru)
  │
  ▼
Parse + Konversi Unit (Console: Imperial→Metric)
  │
  ▼
Normalisasi Timestamp (floor ke kelipatan 5 menit)
  │
  ├── Tidak ada gap → langsung ke tail(144)
  │
  ▼
Resample + Interpolasi Linear
  │  - Grid 5 menit tepat
  │  - Interpolasi maks 6 slot (30 menit gap)
  │  - Duplikat: di-merge rata-rata
  │
  ├── Rasio interpolasi ≥ 25% → ABORT (data terlalu banyak bolong)
  │
  ▼
tail(144) → 12 jam data terbaru
  │
  ▼
Imputasi NaN: ffill → bfill → default klimatologis Indonesia
  │  suhu=27°C, kelembaban=75%, tekanan=1010 hPa, dll.
  │
  ▼
Tambah fitur waktu: hour_sin, hour_cos (cyclical, WIB)
  │
  ▼
MinMaxScaler.transform() → (144, 9)
  │
  ▼
Reshape → (1, 144, 9) → LSTM.predict()
  │
  ▼
Output → (1, 24) scaled values
  │
  ▼
Inverse Scale (fitur hujan index=5)
  │
  ▼
Clamp ≥ 0 → Round 2dp → [24 × mm/h]
```

### XGBoost Labels

| Kelas | Label |
|-------|-------|
| 0 | Cerah / Berawan |
| 1 | Berpotensi Hujan dari Arah Utara |
| 2 | Berpotensi Hujan dari Arah Timur Laut |
| 3 | Berpotensi Hujan dari Arah Timur |
| 4 | Berpotensi Hujan dari Arah Tenggara |
| 5 | Berpotensi Hujan dari Arah Selatan |
| 6 | Berpotensi Hujan dari Arah Barat Daya |
| 7 | Berpotensi Hujan dari Arah Barat |
| 8 | Berpotensi Hujan dari Arah Barat Laut |

### Konstanta Model

| Konstanta | Nilai | Keterangan |
|-----------|-------|------------|
| `SEQUENCE_LENGTH` | 144 | 144 × 5 menit = 12 jam |
| `PREDICTION_STEPS` | 24 | Output 24 jam ke depan |
| `N_FEATURES` | 9 | 7 cuaca + hour_sin + hour_cos |
| `RAIN_FEATURE_INDEX` | 5 | Index kolom intensitas_hujan pada scaler |
| `MAX_INTERPOLATED_RATIO` | 0.25 | Maks 25% data boleh hasil interpolasi |
| `buffer_size` | 154 | 144 + 10 (buffer untuk gap ringan) |
| Interpolasi limit | 6 slot | Maks 30 menit gap yang diinterpolasi |

---

## ⏰ Scheduler & Auto-Fetch

### Job yang Terdaftar

| Job | Jadwal | Fungsi |
|-----|--------|--------|
| `fetch-weather` | Setiap 5 menit | Fetch data dari Ecowitt, Wunderground, Console |
| `hourly-prediction-safety` | Menit ke-8 setiap jam | Safety net prediksi jika trigger utama gagal |

### Alur Fetch → Predict

```
APScheduler (menit :00, :05, :10, ...)
  │
  ▼
fetch_and_store_weather()
  ├── Parallel: Ecowitt + Wunderground (timeout 30s, retry 3×)
  ├── Sequential: Console
  │
  ├── IF fetch selesai di menit < 5 WIB:
  │     └── run_prediction_pipeline()    ← PRIMARY trigger
  │
  └── Safety net di menit :08:
        └── IF belum prediksi jam ini:
              └── run_prediction_pipeline()  ← BACKUP trigger
```

### Dedup Guard

Variabel `_last_prediction_hour` mencegah prediksi ganda dalam 1 jam yang sama.

---

## 💾 Caching

Cache dual-layer: **Redis** (primary) + **in-memory dict** (fallback otomatis jika Redis mati).

| Endpoint | Cache Key Pattern | TTL |
|----------|-------------------|-----|
| `/weather/current` | `weather_current:{source}` | 60s |
| `/weather/predict` | `weather_predict:{source}:{limit}` | 300s |
| `/weather/details` | `weather_details:{source}` | 60s |
| `/weather/history` | `weather_history:{src}:{pg}:{pp}:{sd}:{ed}:{sort}` | 120s |
| `/weather/graph` | `weather_graph:{rng}:{src}:{dt}:{mo}` | 300s |
| `/health` | Tidak di-cache | — |
| `/console` | Tidak di-cache | — |

- Cache **HIT** → database TIDAK diquery
- Cache **MISS** → query DB → simpan ke cache
- Redis **mati** → otomatis fallback ke in-memory (tanpa error)

---

## 🚀 Production Deployment (VPS / Cloud)

Untuk melakukan deployment ke _production_ (seperti VPS Hostinger, AWS, DigitalOcean), sangat disarankan menggunakan **Docker**. Projek ini telah didesain dengan arsitektur _production grade_: **Gunicorn (WSGI) + PostgreSQL 15 + Redis**.

### 1. Persiapan Server
1. Pastikan VPS Anda ter-install `docker` dan `docker-compose`.
2. _Clone_ repositori ini ke VPS Anda.

### 2. Mulai Deployment
Di dalam direktori proyek pada VPS, jalankan:
```bash
# 1. Salin template khusus production
$ cp .env.production .env

# 2. Edit konfigurasi di file .env
$ nano .env
# PENTING JANGAN LUPA:
# - Ganti password DATABASE_URL dengan yang sangat kuat
# - Ganti SECRET_KEY dengan kombinasi 32 huruf+angka acak
# - Isi WUNDERGROUND_URL dan ECO_APP_KEY/ECO_API_KEY
# - Pastikan AUTO_MIGRATE=1 (untuk pembuatan tabel otomatis)

# 3. Jalankan Docker Compose
$ docker-compose up -d --build
```

**Docker otomatis menjalankan 3 _containers_:**
1. `db_postgres_tuws`: Database PostgreSQL 15.
2. `redis_tuws`: Redis Server (Caching & Rate Limiting).
3. `be_flask_tuws`: Aplikasi Backend TUWS_BE (Gunicorn WSGI).

> **💡 Tips Nginx / SSL:** Backend berjalan di port VPS internal `5000`. Jika menggunakan HTTPS, instal Nginx di VPS Anda, pasang sertifikat Let's Encrypt, dan buat _Reverse Proxy_ ke arah `http://127.0.0.1:5000`.

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
├── ml_models/                   # Trained ML models (.keras, .joblib)
├── migrations/                  # Database migrations
├── tests/                       # Test suites
├── docs/
│   ├── API_V3_REFERENCE.md      # Dokumentasi API lengkap
│   ├── DATA_REFERENCE.md        # Referensi data
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
| `APPKEY` | API key untuk header `X-APP-KEY` | *(tanpa auth jika kosong)* |
| `FLASK_HOST` | Host binding | `127.0.0.1` |
| `FLASK_PORT` | Port | `5000` |
| `FLASK_DEBUG` | Debug mode | `0` |
| `REDIS_URL` | Redis connection URL | Fallback in-memory |
| `CORS_ORIGINS` | CORS allowed origins | `*` |
| `RATE_LIMIT_REQUESTS` | Max requests per window | `100` |
| `RATE_LIMIT_WINDOW` | Window duration (detik) | `60` |
| `CONSOLE_ENDPOINT_ENABLED` | Aktifkan console endpoint | `true` |
| `CONSOLE_IP_WHITELIST` | IP whitelist (comma-separated) | *(wajib untuk console)* |
| `ECO_APP_KEY` | Ecowitt application key | *(opsional)* |
| `ECO_API_KEY` | Ecowitt API key | *(opsional)* |
| `ECO_MAC` | Ecowitt device MAC | *(opsional)* |
| `WUNDERGROUND_URL` | Wunderground API URL | *(opsional)* |

---

## 📊 Tabel Database Utama

| Tabel | Fungsi |
|-------|--------|
| `weather_log_ecowitt` | Data cuaca dari Ecowitt |
| `weather_log_wunderground` | Data cuaca dari Wunderground |
| `weather_log_console` | Data cuaca dari Console Station |
| `prediction_log` | Log prediksi (referensi ke model, data, result) |
| `data_xgboost` | Referensi 1 weather_log ID per source untuk XGBoost |
| `data_lstm` | Referensi 144 weather_log IDs per source untuk LSTM |
| `xgboost_prediction_result` | Hasil prediksi XGBoost (label_id per source) |
| `lstm_prediction_result` | Hasil prediksi LSTM (array 24 float per source) |
| `label` | Label arah hujan (9 kelas) |
| `model` | Metadata model ML |

---

## 📐 Konversi Unit

Konversi unit **hanya terjadi di pipeline prediksi internal**, bukan di response API.

| Konversi | Fungsi | Contoh |
|----------|--------|--------|
| °F → °C | `fahrenheit_to_celsius()` | 100°F → 37.78°C |
| inHg → hPa | `inch_hg_to_hpa()` | 29.92 → 1013.21 |
| mph → m/s | `mph_to_ms()` | 10 → 4.47 |
| in/hr → mm/hr | `inch_per_hour_to_mm_per_hour()` | 0.33 → 8.38 |
| W/m² → lux | `wm2_to_lux()` | 100 → 12670 |

### Satuan Data per Source di Database

| Parameter | Ecowitt | Wunderground | Console |
|-----------|---------|--------------|---------|
| Temperature | °C | °C | °F |
| Pressure | hPa | hPa | inHg |
| Wind Speed | m/s | m/s | mph |
| Rain | mm/hr | mm/hr | in/hr |
| Solar | lux | W/m² | W/m² |

> Response API mengembalikan data **apa adanya** dari database tanpa konversi. Hanya pipeline prediksi yang melakukan konversi internal.
