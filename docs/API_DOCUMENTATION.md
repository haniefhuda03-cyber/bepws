# 📖 TUWS Weather API Documentation

## Daftar Isi
- [Pendahuluan](#pendahuluan)
- [Authentication](#authentication)
- [API Biasa (Legacy)](#api-biasa-legacy)
- [API v3 (RESTful)](#api-v3-restful)
- [Response Format](#response-format)
- [Error Handling](#error-handling)
- [Testing dengan Postman](#testing-dengan-postman)

---

## Pendahuluan

TUWS Weather API menyediakan data cuaca dan prediksi menggunakan model Machine Learning (LSTM dan XGBoost).

### Base URL
- **Local Development:** `http://localhost:5000`
- **Production:** `https://your-domain.com`

### Dua Versi API

| Versi | Base Path | Fitur |
|-------|-----------|-------|
| **API Biasa (Legacy)** | `/api` | X-API-KEY authentication |
| **API v3 (RESTful)** | `/api/v3` | X-API-KEY + CORS + Rate Limiting |

---

## Authentication

Semua endpoint (kecuali `/health`) memerlukan header `X-API-KEY`.

### Header yang Diperlukan
```
X-API-KEY: <your-api-key>
```

### Contoh Request
```bash
curl -H "X-API-KEY: tuws2526" http://localhost:5000/api/data?type=general
```

### Development Mode
Jika environment variable `API_READ_KEY` tidak di-set, API akan berjalan tanpa authentication.

---

# API Biasa (Legacy)

Base URL: `/api`

## 1. Health Check

Cek status kesehatan API.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/health` |
| **Auth Required** | ❌ No |

### Response
```json
{
  "ok": true,
  "details": {
    "db": "ok",
    "scheduler": "running",
    "scheduler_jobs": ["fetch-weather"],
    "fetch_weather_next_run": "2024-12-23T10:30:00+00:00"
  }
}
```

---

## 2. Data Endpoint

Endpoint utama untuk mengambil data cuaca.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/data` |
| **Auth Required** | ✅ Yes (X-API-KEY) |

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `type` | string | No | `general` | Jenis data: `general`, `hourly`, `detail` |
| `source` | string | No | `ecowitt` | Sumber data: `ecowitt`, `wunderground` |
| `model` | string | No | `lstm` | Model ML (untuk type=hourly): `lstm`, `xgboost` |
| `limit` | integer | No | 24 | Batasi jumlah data (untuk type=hourly, 1-24) |
| `id` | integer | No | - | ID spesifik (untuk type=detail) |

### 2.1 type=general

Mendapatkan data cuaca terkini.

**Request:**
```
GET /api/data?type=general&source=ecowitt
```

**Response:**
```json
{
  "ok": true,
  "data": {
    "id": 123,
    "time": "2024-12-23T10:30:00+07:00",
    "location": null,
    "pressure": 1013.25,
    "uvi": 5.2,
    "compass": "NE",
    "deg": 45.0,
    "dew_point": 22.5,
    "humidity": 75,
    "temp": 28.5,
    "rain_rate": 0.0,
    "weather": "Cerah / Berawan",
    "wind_speed": 3.5
  }
}
```

### 2.2 type=hourly (LSTM)

Mendapatkan prediksi intensitas hujan per jam menggunakan model LSTM.

**Request:**
```
GET /api/data?type=hourly&model=lstm&source=ecowitt&limit=6
```

**Response:**
```json
{
  "ok": true,
  "model": {
    "id": 2,
    "name": "default_lstm",
    "range_prediction": 1440
  },
  "prediction": {
    "id": 123,
    "source": "ecowitt",
    "predicted_at": "2024-12-23T10:30:00+07:00",
    "total_hours": 24,
    "showing": 6,
    "limit_applied": 6
  },
  "data": [
    {
      "hour": 1,
      "datetime": "2024-12-23T11:30:00+07:00",
      "date": "2024-12-23",
      "time": "11:30",
      "value": 0.5
    },
    {
      "hour": 2,
      "datetime": "2024-12-23T12:30:00+07:00",
      "date": "2024-12-23",
      "time": "12:30",
      "value": 1.2
    }
  ]
}
```

### 2.3 type=hourly (XGBoost)

Mendapatkan klasifikasi arah hujan menggunakan model XGBoost.

**Request:**
```
GET /api/data?type=hourly&model=xgboost&source=ecowitt
```

**Response:**
```json
{
  "ok": true,
  "model": "xgboost",
  "data": {
    "id": 123,
    "model": {
      "type": "xgboost",
      "id": 1,
      "name": "default_xgboost",
      "range_prediction": 60
    },
    "source": "ecowitt",
    "created_at": "2024-12-23T10:30:00+07:00",
    "label": {
      "label_id": 8,
      "class_id": 7,
      "name": "Berpotensi Hujan dari Arah Barat"
    }
  }
}
```

### 2.4 type=detail

Mendapatkan detail lengkap data cuaca.

**Request:**
```
GET /api/data?type=detail&source=ecowitt
```

**Response (Ecowitt):**
```json
{
  "ok": true,
  "data": {
    "id": 123,
    "created_at": "2024-12-23T10:30:00+07:00",
    "time": "2024-12-23T10:30:00+07:00",
    "humidity": 75,
    "humidity_indoor": 60,
    "temp": 28.5,
    "temp_indoor": 26.0,
    "uvi": 5.2,
    "vpd_outdoor": 1.2,
    "feels_like": 30.0,
    "rain_rate": 0.0,
    "solar_irradiance": 850.0,
    "wind_gust": 5.0,
    "pressure_relative": 1013.25,
    "dew_point": 22.5,
    "compass": "NE",
    "deg": 45.0,
    "wind_speed": 3.5
  }
}
```

---

## 3. History Endpoint

Mengambil riwayat data cuaca dengan pagination dan filter.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/history` |
| **Auth Required** | ✅ Yes (X-API-KEY) |

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | integer | No | 1 | Nomor halaman |
| `per_page` | integer | No | 10 | Item per halaman (max 50) |
| `source` | string | No | `ecowitt` | Sumber data: `ecowitt`, `wunderground` |
| `date` | string | No | - | Filter tanggal spesifik (format: `YYYY-MM-DD`) |
| `time` | string | No | - | Filter waktu spesifik (format: `HH:MM` atau `HH:MM:SS`) |
| `start_date` | string | No | - | Tanggal awal range (harus dengan `end_date`) |
| `end_date` | string | No | - | Tanggal akhir range (harus dengan `start_date`) |
| `start_time` | string | No | - | Waktu awal range (harus dengan `end_time`) |
| `end_time` | string | No | - | Waktu akhir range (harus dengan `start_time`) |

### Contoh Request

**Basic pagination:**
```
GET /api/history?page=1&source=ecowitt
```

**Filter by date:**
```
GET /api/history?date=2024-12-23&source=ecowitt
```

**Filter by date range:**
```
GET /api/history?start_date=2024-12-20&end_date=2024-12-23&source=ecowitt
```

**Filter by time range:**
```
GET /api/history?start_time=08:00&end_time=17:00&source=ecowitt
```

**Response:**
```json
{
  "ok": true,
  "page": 1,
  "per_page": 5,
  "total": 100,
  "data": [
    {
      "id": 123,
      "time": "2024-12-23T10:30:00+07:00",
      "temp": 28.5,
      "humidity": 75,
      "pressure": 1013.25,
      "pressure_relative": 1010.0,
      "UVI": 5.2,
      "compass": "NE",
      "degree": 45.0,
      "dew_point": 22.5,
      "feels_like": 30.0,
      "vpd": 1.2,
      "wind_speed": 3.5,
      "wind_gust": 5.0,
      "rain_rate": 0.0,
      "solar_irradiance": 850.0
    }
  ]
}
```

---

## 4. Graph Endpoint

Mengambil data untuk grafik/chart.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/graph` |
| **Auth Required** | ✅ Yes (X-API-KEY) |

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `range` | string | ✅ **Yes** | - | Range data: `weekly` atau `monthly` |
| `datatype` | string | ✅ **Yes** | - | Tipe data untuk chart |
| `source` | string | No | `ecowitt` | Sumber data: `ecowitt`, `wunderground` |
| `month` | integer | No | - | Filter bulan (1-12, untuk range monthly) |

### Nilai datatype yang Tersedia
- `temperature` - Suhu
- `humidity` - Kelembaban
- `pressure` - Tekanan udara
- `wind_speed` - Kecepatan angin
- `rain_rate` - Intensitas hujan
- `uvi` - UV Index
- `solar_irradiance` - Iradiasi matahari

### Contoh Request
```
GET /api/graph?range=7&source=ecowitt&datatype=temperature
```

**Response:**
```json
{
  "ok": true,
  "data": {
    "labels": ["2024-12-17", "2024-12-18", "2024-12-19"],
    "datasets": [
      {
        "label": "Temperature",
        "data": [28.5, 29.0, 27.8]
      }
    ]
  }
}
```

---

# API v3 (RESTful)

Base URL: `/api/v3`

## Fitur Tambahan API v3

| Fitur | Deskripsi |
|-------|-----------|
| **CORS** | Cross-Origin Resource Sharing enabled |
| **Rate Limiting** | 100 requests per 60 detik |
| **Rate Limit Headers** | `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` |

---

## 1. Health Check

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/health` |
| **Auth Required** | ❌ No |
| **Rate Limited** | ✅ Yes |

### Response Headers
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 99
X-RateLimit-Reset: 1703318400
```

### Response Body
```json
{
  "ok": true,
  "data": {
    "status": "healthy",
    "version": "v3",
    "database": "ok",
    "timestamp": "2024-12-23T10:30:00+07:00"
  }
}
```

---

## 2. Current Weather

Mendapatkan data cuaca dan prediksi terkini.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/weather/current` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source` | string | No | `ecowitt` | Sumber data: `ecowitt`, `wunderground` |

### Contoh Request
```
GET /api/v3/weather/current?source=ecowitt
Headers: X-API-KEY: tuws2526
```

### Response
```json
{
  "ok": true,
  "data": {
    "weather": {
      "id": 123,
      "source": "ecowitt",
      "recorded_at": "2024-12-23T10:30:00+07:00",
      "temperature": 28.5,
      "humidity": 75,
      "pressure": 1013.25,
      "wind_speed": 3.5,
      "wind_direction": 45.0,
      "compass": "NE",
      "uvi": 5.2,
      "rain_rate": 0.0,
      "solar_irradiance": 850.0
    },
    "prediction": {
      "id": 123,
      "source": "ecowitt",
      "predicted_at": "2024-12-23T10:30:00+07:00",
      "classification": {
        "label_id": 1,
        "class_id": 0,
        "name": "Cerah / Berawan"
      }
    }
  }
}
```

---

## 3. Hourly Prediction

Mendapatkan prediksi per jam.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/weather/hourly` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `model` | string | No | `lstm` | Model ML: `lstm`, `xgboost` |
| `source` | string | No | `ecowitt` | Sumber data: `ecowitt`, `wunderground` |
| `limit` | integer | No | 24 | Batasi jumlah data (1-24) |

### Contoh Request (LSTM)
```
GET /api/v3/weather/hourly?model=lstm&source=ecowitt&limit=6
Headers: X-API-KEY: tuws2526
```

### Response (LSTM)
```json
{
  "ok": true,
  "data": {
    "model": {
      "id": 2,
      "name": "default_lstm",
      "range_prediction": 1440
    },
    "prediction": {
      "id": 123,
      "source": "ecowitt",
      "predicted_at": "2024-12-23T10:30:00+07:00",
      "total_hours": 24,
      "showing": 6,
      "limit_applied": 6
    },
    "hourly": [
      {
        "hour": 1,
        "datetime": "2024-12-23T11:30:00+07:00",
        "date": "2024-12-23",
        "time": "11:30",
        "value": 0.5
      }
    ]
  }
}
```

### Contoh Request (XGBoost)
```
GET /api/v3/weather/hourly?model=xgboost&source=ecowitt
Headers: X-API-KEY: tuws2526
```

### Response (XGBoost)
```json
{
  "ok": true,
  "data": {
    "model": {
      "id": 1,
      "name": "default_xgboost",
      "range_prediction": 60
    },
    "prediction": {
      "id": 123,
      "source": "ecowitt",
      "predicted_at": "2024-12-23T10:30:00+07:00"
    },
    "classification": {
      "label_id": 8,
      "class_id": 7,
      "name": "Berpotensi Hujan dari Arah Barat"
    }
  }
}
```

---

## 4. Weather Details

Mendapatkan detail lengkap data cuaca.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/weather/details` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source` | string | No | `ecowitt` | Sumber data: `ecowitt`, `wunderground` |
| `id` | integer | No | - | ID prediksi spesifik |

### Contoh Request
```
GET /api/v3/weather/details?source=ecowitt
Headers: X-API-KEY: tuws2526
```

### Response
```json
{
  "ok": true,
  "data": {
    "id": 123,
    "source": "ecowitt",
    "recorded_at": "2024-12-23T10:30:00+07:00",
    "temperature": {
      "outdoor": 28.5,
      "indoor": 26.0,
      "feels_like": 30.0,
      "dew_point": 22.5
    },
    "humidity": {
      "outdoor": 75,
      "indoor": 60
    },
    "pressure": {
      "absolute": 1015.0,
      "relative": 1013.25
    },
    "wind": {
      "speed": 3.5,
      "gust": 5.0,
      "direction": 45.0,
      "compass": "NE"
    },
    "rain": {
      "rate": 0.0,
      "daily": 0.0,
      "hourly": 0.0,
      "weekly": 5.2,
      "monthly": 120.5,
      "yearly": 1500.0
    },
    "solar": {
      "irradiance": 850.0,
      "uvi": 5.2
    },
    "vpd": 1.2
  }
}
```

---

## 5. Weather History

Mengambil riwayat data cuaca dengan pagination.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/weather/history` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | integer | No | 1 | Nomor halaman |
| `per_page` | integer | No | 10 | Item per halaman (max 50) |
| `source` | string | No | `ecowitt` | Sumber data: `ecowitt`, `wunderground` |
| `date` | string | No | - | Filter tanggal (format: `YYYY-MM-DD`) |
| `time` | string | No | - | Filter waktu spesifik (format: `HH:MM`) |
| `start_date` | string | No | - | Tanggal awal range |
| `end_date` | string | No | - | Tanggal akhir range |
| `start_time` | string | No | - | Waktu awal range (format: `HH:MM`) |
| `end_time` | string | No | - | Waktu akhir range (format: `HH:MM`) |

### Contoh Request

**Basic pagination:**
```
GET /api/v3/weather/history?page=1&per_page=10&source=ecowitt
Headers: X-API-KEY: tuws2526
```

**Filter by specific date and time:**
```
GET /api/v3/weather/history?date=2024-12-23&time=10:30&source=ecowitt
Headers: X-API-KEY: tuws2526
```

**Filter by date range:**
```
GET /api/v3/weather/history?start_date=2024-12-20&end_date=2024-12-23&source=ecowitt
Headers: X-API-KEY: tuws2526
```

**Filter by time range:**
```
GET /api/v3/weather/history?start_time=08:00&end_time=17:00&source=ecowitt
Headers: X-API-KEY: tuws2526
```

### Response
```json
{
  "ok": true,
  "data": {
    "items": [
      {
        "id": 123,
        "recorded_at": "2024-12-23T10:30:00+07:00",
        "temperature": 28.5,
        "humidity": 75,
        "pressure": 1013.25,
        "wind_speed": 3.5,
        "rain_rate": 0.0
      }
    ],
    "pagination": {
      "page": 1,
      "per_page": 10,
      "total_items": 100,
      "total_pages": 10,
      "has_next": true,
      "has_prev": false
    }
  }
}
```

---

## 6. Graph Data

Mengambil data untuk chart/grafik.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/weather/graph` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `range` | string | ✅ **Yes** | - | Range data: `weekly` atau `monthly` |
| `datatype` | string | ✅ **Yes** | - | Tipe data untuk chart |
| `source` | string | No | `ecowitt` | Sumber data |
| `month` | integer | No | - | Filter bulan (1-12, untuk range monthly) |

### Nilai datatype
- `temperature` - Suhu
- `humidity` - Kelembaban  
- `pressure` - Tekanan udara
- `wind_speed` - Kecepatan angin
- `rain_rate` - Intensitas hujan
- `uvi` - UV Index
- `solar_irradiance` - Iradiasi matahari

### Contoh Request
```
GET /api/v3/weather/graph?range=7&source=ecowitt&datatype=temperature
Headers: X-API-KEY: tuws2526
```

### Response
```json
{
  "ok": true,
  "data": {
    "chart": {
      "type": "line",
      "title": "Temperature - Last 7 Days"
    },
    "labels": ["2024-12-17", "2024-12-18", "2024-12-19"],
    "datasets": [
      {
        "label": "Temperature (°C)",
        "data": [28.5, 29.0, 27.8],
        "borderColor": "#FF6384",
        "fill": false
      }
    ]
  }
}
```

---

# Response Format

## Success Response

### API Biasa
```json
{
  "ok": true,
  "data": { ... }
}
```

### API v3
```json
{
  "ok": true,
  "data": { ... }
}
```

## Error Response

### API Biasa
```json
{
  "ok": false,
  "message": "Human readable error message"
}
```

### API v3
```json
{
  "ok": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable error message"
  }
}
```

---

# Error Handling

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad Request - Invalid parameters |
| 401 | Unauthorized - Missing or invalid X-API-KEY |
| 404 | Not Found - Resource not found |
| 429 | Too Many Requests - Rate limit exceeded (API v3 only) |
| 500 | Internal Server Error |

## Error Codes (API v3)

| Code | Description |
|------|-------------|
| `MISSING_API_KEY` | X-API-KEY header tidak ada |
| `INVALID_API_KEY` | X-API-KEY tidak valid |
| `RATE_LIMIT_EXCEEDED` | Melebihi batas request |
| `INVALID_PARAMETER` | Parameter tidak valid |
| `NO_DATA` | Data tidak ditemukan |
| `INTERNAL_ERROR` | Error internal server |

---

# Testing dengan Postman

## Import Collection

1. Buka Postman
2. Click **Import** → **Files**
3. Pilih `postman/TUWS_API_Collection.postman_collection.json`

## Import Environment

1. Click **Import** → **Files**
2. Pilih `postman/TUWS_Local.postman_environment.json`

## Setup

1. Pilih environment "TUWS Local Development" di dropdown pojok kanan atas
2. API Key sudah terisi: `tuws2526`

## Test Cases

### Test Authentication
1. Request tanpa X-API-KEY → Expected: 401
2. Request dengan key salah → Expected: 401
3. Request dengan key benar → Expected: 200

### Test Rate Limiting (API v3)
1. Kirim request ke `/api/v3/health` beberapa kali
2. Perhatikan header `X-RateLimit-Remaining` berkurang
3. Setelah 100 request → Expected: 429

### Test CORS (API v3)
1. Kirim OPTIONS request ke `/api/v3/weather/current`
2. Set header `Origin: http://localhost:3000`
3. Periksa response header `Access-Control-Allow-*`

---

# Daftar Label Klasifikasi

Data label tersimpan di database `label`:

| ID | Class ID | Name |
|----|----------|------|
| 1 | 0 | Cerah / Berawan |
| 2 | 1 | Berpotensi Hujan dari Arah Utara |
| 3 | 2 | Berpotensi Hujan dari Arah Timur Laut |
| 4 | 3 | Berpotensi Hujan dari Arah Timur |
| 5 | 4 | Berpotensi Hujan dari Arah Tenggara |
| 6 | 5 | Berpotensi Hujan dari Arah Selatan |
| 7 | 6 | Berpotensi Hujan dari Arah Barat Daya |
| 8 | 7 | Berpotensi Hujan dari Arah Barat |
| 9 | 8 | Berpotensi Hujan dari Arah Barat Laut |

---

# Daftar Model ML

Data model tersimpan di database `model`:

| ID | Name | Range Prediction |
|----|------|------------------|
| 1 | default_xgboost | 60 menit |
| 2 | default_lstm | 1440 menit (24 jam) |

---

## Changelog

### v3.0.0
- Tambah CORS support
- Tambah Rate Limiting (100 req/60s)
- Tambah rate limit headers
- Response format lebih konsisten
- Error codes yang lebih deskriptif

### v1.0.0 (Legacy)
- Initial release
- Basic X-API-KEY authentication
- Endpoints: data, history, graph, health
