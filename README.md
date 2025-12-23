# TUWS Weather API Backend

Backend API untuk sistem prediksi cuaca menggunakan LSTM dan XGBoost.

---

## 🚀 Quick Start (Pertama Kali)

### Prasyarat
- Python 3.10+ 
- MySQL Server (running)
- Git

---

## 📋 Langkah Setup Lengkap

### Step 1: Clone & Masuk Direktori
```bash
cd tuwsbe
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

### Step 4: Buat Database MySQL
```sql
-- Login ke MySQL
mysql -u root -p

-- Buat database
CREATE DATABASE tuws_pws CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- (Opsional) Buat user khusus
CREATE USER 'tuws_user'@'localhost' IDENTIFIED BY 'password123';
GRANT ALL PRIVILEGES ON tuws_pws.* TO 'tuws_user'@'localhost';
FLUSH PRIVILEGES;

EXIT;
```

### Step 5: Konfigurasi Environment (.env)
```bash
# Copy contoh atau edit langsung .env
```

Isi file `.env`:
```dotenv
# Database (sesuaikan dengan MySQL Anda)
DATABASE_URL="mysql+pymysql://root@localhost:3306/tuws_pws"
# atau dengan password:
# DATABASE_URL="mysql+pymysql://root:password@localhost:3306/tuws_pws"

# Flask
FLASK_APP=run.py
FLASK_ENV=development
FLASK_DEBUG=1
FLASK_HOST=127.0.0.1
FLASK_PORT=5000

# Secret Key (generate random)
SECRET_KEY="your-random-secret-key-here"

# API Key untuk akses endpoint
API_READ_KEY="tuws2526"

# Weather API Keys (opsional, untuk fetch data real)
WUNDERGROUND_URL="https://api.weather.com/..."
ECO_APP_KEY="your-ecowitt-app-key"
ECO_API_KEY="your-ecowitt-api-key"
ECO_MAC="your-device-mac"
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
INFO - SECRET_KEY tidak ditemukan di env; dibuat/diambil di instance/secret_key
INFO - Cache: menggunakan simple (in-memory) cache.
INFO - Scheduler initialized but not started.
INFO - Registered API blueprints: /api (legacy), /api/v3
INFO - Model ML berhasil diinisialisasi saat startup.
INFO - Job 'fetch-weather' didaftarkan (interval 5 menit).
INFO - Job 'hourly-prediction' didaftarkan (cron setiap jam).
 * Running on http://127.0.0.1:5000
```

### Step 9: Test API
```bash
# Health check (tanpa auth)
curl http://localhost:5000/api/health

# Dengan API key
curl -H "X-API-KEY: tuws2526" http://localhost:5000/api/data?type=general
```

---

## 🔄 Perintah Migrasi Database

```bash
# Melihat status migrasi
flask db current

# Membuat migrasi baru setelah mengubah models.py
flask db migrate -m "Deskripsi perubahan"

# Menerapkan migrasi ke database
flask db upgrade

# Rollback migrasi terakhir
flask db downgrade

# Melihat history migrasi
flask db history
```

---

## 🧪 Menjalankan Tests

```bash
# Test API v3
python -m tests.test_api_v3

# Test prediction flow
python -m tests.test_prediction_flow

# Semua tests dengan pytest
pytest tests/ -v
```

---

## 🐳 Docker (Opsional)

```bash
# Build image
docker build -t tuws-backend .

# Run container
docker run -p 5000:5000 --env-file .env tuws-backend

# Atau dengan docker-compose
docker-compose up -d
```

## 📡 API Endpoints

### Tersedia Dua Versi API:

| Versi | Base URL | Fitur |
|-------|----------|-------|
| **API Biasa (Legacy)** | `/api/*` | X-API-KEY authentication |
| **API v3 (RESTful)** | `/api/v3/*` | X-API-KEY + CORS + Rate Limiting |

---

## 🔐 Authentication

Semua endpoint (kecuali `/health`) memerlukan header `X-API-KEY`:

```
X-API-KEY: your-api-key
```

### Development Mode
Jika environment variable `API_KEY` tidak di-set, API akan berjalan tanpa authentication (untuk development).

---

## 📋 API Biasa (Legacy) - `/api/*`

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| GET | `/api/health` | Health check |
| GET | `/api/data?type=general` | Data cuaca terkini |
| GET | `/api/data?type=hourly&model=lstm` | Prediksi per jam (LSTM) |
| GET | `/api/data?type=hourly&model=xgboost` | Prediksi klasifikasi (XGBoost) |
| GET | `/api/data?type=detail` | Detail cuaca lengkap |
| GET | `/api/history` | Riwayat data |
| GET | `/api/graph` | Data untuk grafik |

### Query Parameters:
- `source`: `ecowitt` atau `wunderground` (default: `ecowitt`)
- `model`: `lstm` atau `xgboost` (untuk type=hourly)
- `limit`: Jumlah data yang ditampilkan
- `page`: Nomor halaman (untuk history)

---

## 🆕 API v3 (RESTful) - `/api/v3/*`

### Fitur Tambahan:
- ✅ **CORS** - Cross-Origin Resource Sharing enabled
- ✅ **Rate Limiting** - 100 requests per 60 detik
- ✅ **X-API-KEY** - Header authentication

### Rate Limit Headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 99
X-RateLimit-Reset: 1703318400
```

### Endpoints:

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| GET | `/api/v3/health` | Health check (no auth) |
| GET | `/api/v3/weather/current` | Data cuaca & prediksi terkini |
| GET | `/api/v3/weather/hourly` | Prediksi per jam |
| GET | `/api/v3/weather/details` | Detail cuaca lengkap |
| GET | `/api/v3/weather/history` | Riwayat data (pagination) |
| GET | `/api/v3/weather/graph` | Data untuk chart |

### Query Parameters:
- `source`: `ecowitt` atau `wunderground`
- `model`: `lstm` atau `xgboost`
- `limit`: Jumlah data yang ditampilkan
- `page`, `per_page`: Pagination (untuk history)
- `range`: Range hari untuk graph (7, 14, 30)
- `datatype`: `temperature`, `humidity`, `pressure`, `wind_speed`

---

## 🧪 Testing dengan Postman

### Import Collection:
1. Buka Postman
2. Click **Import**
3. Pilih file `postman/TUWS_API_Collection.postman_collection.json`
4. Import juga environment `postman/TUWS_Local.postman_environment.json`

### Set API Key:
1. Pilih environment "TUWS Local Development"
2. Edit variable `api_key` dengan API key yang valid
3. Jika development tanpa auth, kosongkan saja

### Test Rate Limiting:
1. Buka request "Test Rate Limiting" di folder API v3
2. Kirim request berulang kali
3. Perhatikan header `X-RateLimit-Remaining` berkurang

### Test CORS:
1. Buka request "Test CORS (Preflight)" di folder API v3
2. Gunakan method OPTIONS
3. Periksa response header:
   - `Access-Control-Allow-Origin`
   - `Access-Control-Allow-Headers`
   - `Access-Control-Allow-Methods`

---

## 📁 Project Structure

```
tuwsbe/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── api.py                # API Biasa (Legacy)
│   ├── api_v3.py             # API v3 (RESTful)
│   ├── models.py             # SQLAlchemy models
│   ├── serializers.py        # Data serialization
│   ├── ml_lstm.py            # LSTM model
│   ├── ml_xgboost.py         # XGBoost model
│   ├── jobs.py               # Scheduler jobs
│   └── services/
│       └── prediction_service.py
├── ml_models/                # Trained ML models
├── migrations/               # Database migrations
├── tests/                    # Test suites
├── postman/                  # Postman collection & environments
├── run.py                    # Entry point
└── requirements.txt
```

---

## 🔧 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `API_KEY` | API key untuk authentication | (none - no auth) |
| `DATABASE_URL` | Database connection string | SQLite |
| `FLASK_ENV` | Environment mode | production |

---

## 📊 Response Format

### API Biasa:
```json
{
  "ok": true,
  "data": { ... }
}
```

### API v3:
```json
{
  "ok": true,
  "data": { ... },
  "meta": {
    "timestamp": "2024-12-23T10:30:00+07:00",
    "version": "v3"
  }
}
```

### Error Response:
```json
{
  "ok": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message"
  }
}
```
