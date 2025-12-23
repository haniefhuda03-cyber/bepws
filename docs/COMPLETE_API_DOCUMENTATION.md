# 📚 TUWS Weather API - Dokumentasi Lengkap

**Version:** 3.0  
**Last Updated:** December 23, 2025  
**Author:** TUWS Development Team

---

## 📋 Daftar Isi

1. [Pendahuluan](#1-pendahuluan)
2. [Autentikasi](#2-autentikasi)
3. [API Biasa (Legacy)](#3-api-biasa-legacy)
4. [API v3 (RESTful)](#4-api-v3-restful)
5. [Perbandingan API](#5-perbandingan-api)
6. [Error Handling](#6-error-handling)
7. [Rate Limiting](#7-rate-limiting)

---

## 1. Pendahuluan

TUWS Weather API menyediakan dua versi API:

| Versi | Base URL | Deskripsi |
|-------|----------|-----------|
| **API Biasa (Legacy)** | `/api` | API sederhana dengan X-API-KEY auth |
| **API v3 (RESTful)** | `/api/v3` | API modern dengan CORS, Rate Limiting, dan struktur response yang konsisten |

---

## 2. Autentikasi

### Header yang Digunakan

```
X-API-KEY: your-api-key
```

**CATATAN:** Kedua API menggunakan header `X-API-KEY` untuk autentikasi (bukan `api_key` query parameter).

### Development Mode

Jika environment variable `API_KEY` atau `API_READ_KEY` tidak di-set, API akan berjalan tanpa autentikasi.

### Contoh Request

```bash
curl -H "X-API-KEY: tuws2526" http://localhost:5000/api/health
```

---

## 3. API Biasa (Legacy)

Base URL: `/api`

### 3.1 Health Check

Memeriksa status sistem.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/health` |
| **Auth Required** | ❌ No |

**Response:**
```json
{
  "ok": true,
  "details": {
    "db": "ok",
    "scheduler": "running",
    "scheduler_jobs": ["fetch-weather", "hourly-prediction"],
    "fetch_weather_next_run": "2024-12-23 11:00:00+07:00"
  }
}
```

---

### 3.2 Data Cuaca (General)

Mengambil data cuaca terkini dengan prediksi.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/data` |
| **Auth Required** | ✅ Yes (X-API-KEY) |

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `type` | string | ✅ Yes | - | Jenis data: `general`, `hourly`, `details` |
| `source` | string | No | `ecowitt` | Sumber: `ecowitt` atau `wunderground` |
| `model` | string | No | `lstm` | Model ML (untuk type=hourly): `lstm` atau `xgboost` |
| `limit` | integer | No | - | Batasi jumlah data (1-24, untuk hourly) |

#### Contoh Request

**Data General:**
```
GET /api/data?type=general&source=ecowitt
Headers: X-API-KEY: tuws2526
```

**Prediksi Hourly (LSTM):**
```
GET /api/data?type=hourly&model=lstm&source=ecowitt&limit=6
Headers: X-API-KEY: tuws2526
```

**Prediksi Klasifikasi (XGBoost):**
```
GET /api/data?type=hourly&model=xgboost&source=ecowitt
Headers: X-API-KEY: tuws2526
```

**Detail Cuaca:**
```
GET /api/data?type=details&source=ecowitt
Headers: X-API-KEY: tuws2526
```

#### Response (type=general)
```json
{
  "ok": true,
  "data": {
    "id": 123,
    "time": "2024-12-23T10:30:00+07:00",
    "temp": 28.5,
    "humidity": 75,
    "pressure": 1013.25,
    "uvi": 5.2,
    "compass": "NE",
    "deg": 45.0,
    "dew_point": 22.5,
    "rain_rate": 0.0,
    "weather": "Cerah / Berawan",
    "wind_speed": 3.5
  }
}
```

#### Response (type=hourly, model=lstm)
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
    }
  ]
}
```

#### Response (type=hourly, model=xgboost)
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
      "label_id": 1,
      "class_id": 0,
      "name": "Cerah / Berawan"
    }
  }
}
```

---

### 3.3 History

Mengambil riwayat data cuaca dengan pagination.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/history` |
| **Auth Required** | ✅ Yes (X-API-KEY) |

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | integer | No | 1 | Nomor halaman |
| `per_page` | integer | No | 10 | Item per halaman (max: 50) |
| `source` | string | No | `ecowitt` | Sumber: `ecowitt` atau `wunderground` |
| `date` | string | No | - | Filter tanggal spesifik (format: `YYYY-MM-DD`) |
| `time` | string | No | - | Filter waktu spesifik (format: `HH:MM`) |
| `start_date` | string | No | - | Tanggal awal range (format: `YYYY-MM-DD`) |
| `end_date` | string | No | - | Tanggal akhir range (format: `YYYY-MM-DD`) |
| `start_time` | string | No | - | Waktu awal range (format: `HH:MM`) |
| `end_time` | string | No | - | Waktu akhir range (format: `HH:MM`) |

#### Contoh Request

**Basic pagination:**
```
GET /api/history?page=1&per_page=10&source=ecowitt
Headers: X-API-KEY: tuws2526
```

**Filter by date:**
```
GET /api/history?date=2024-12-23&source=ecowitt
Headers: X-API-KEY: tuws2526
```

**Filter by date and time:**
```
GET /api/history?date=2024-12-23&time=10:30&source=ecowitt
Headers: X-API-KEY: tuws2526
```

**Filter by date range:**
```
GET /api/history?start_date=2024-12-20&end_date=2024-12-23&source=ecowitt
Headers: X-API-KEY: tuws2526
```

**Filter by time range:**
```
GET /api/history?start_time=08:00&end_time=17:00&source=ecowitt
Headers: X-API-KEY: tuws2526
```

#### Response
```json
{
  "ok": true,
  "page": 1,
  "per_page": 10,
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

### 3.4 Graph

Mengambil data untuk grafik/chart.

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/graph` |
| **Auth Required** | ✅ Yes (X-API-KEY) |

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `range` | string | ✅ **Yes** | - | Range data: `weekly` atau `monthly` |
| `datatype` | string | ✅ **Yes** | - | Tipe data untuk chart |
| `source` | string | No | `ecowitt` | Sumber data |
| `month` | integer | No | - | Filter bulan (1-12, untuk range monthly) |

#### Nilai datatype yang Tersedia
- `temperature` - Suhu
- `humidity` - Kelembaban
- `pressure` - Tekanan udara
- `wind_speed` - Kecepatan angin
- `rain_rate` / `rainfall` - Intensitas hujan
- `uvi` - UV Index
- `solar_irradiance` / `solar_radiation` - Iradiasi matahari

#### Contoh Request
```
GET /api/graph?range=weekly&datatype=temperature&source=ecowitt
Headers: X-API-KEY: tuws2526
```

#### Response
```json
{
  "ok": true,
  "range": "weekly",
  "datatype": "temperature",
  "source": "ecowitt",
  "data": [
    {"date": "2024-12-17", "min": 24.5, "max": 32.1, "avg": 28.3},
    {"date": "2024-12-18", "min": 23.8, "max": 31.5, "avg": 27.6}
  ]
}
```

---

## 4. API v3 (RESTful)

Base URL: `/api/v3`

### Fitur Tambahan API v3:
- ✅ **CORS** - Cross-Origin Resource Sharing
- ✅ **Rate Limiting** - 100 requests per 60 detik
- ✅ **Structured Error Response**
- ✅ **Consistent Response Format**

---

### 4.1 Health Check

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/health` |
| **Auth Required** | ❌ No |
| **Rate Limited** | ✅ Yes |

**Response:**
```json
{
  "ok": true,
  "data": {
    "api_version": "v3",
    "timestamp": "2024-12-23T10:30:00+07:00",
    "database": "ok",
    "scheduler": "running",
    "scheduler_jobs": ["fetch-weather", "hourly-prediction"]
  }
}
```

---

### 4.2 Weather Current

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/weather/current` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source` | string | No | `ecowitt` | Sumber: `ecowitt` atau `wunderground` |

#### Response
```json
{
  "ok": true,
  "data": {
    "id": 123,
    "source": "ecowitt",
    "timestamp": "2024-12-23T10:30:00+07:00",
    "weather": {
      "temperature": 28.5,
      "humidity": 75,
      "pressure": 1013.25,
      "wind_speed": 3.5,
      "wind_direction": 45.0,
      "wind_compass": "NE",
      "rain_rate": 0.0,
      "uvi": 5.2,
      "dew_point": 22.5
    },
    "prediction": {
      "label_id": 1,
      "class_id": 0,
      "name": "Cerah / Berawan"
    }
  }
}
```

---

### 4.3 Weather Hourly (Predictions)

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/weather/hourly` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source` | string | No | `ecowitt` | Sumber: `ecowitt` atau `wunderground` |
| `model` | string | No | `lstm` | Model ML: `lstm` atau `xgboost` |
| `limit` | integer | No | - | Batasi jumlah data (1-24) |

#### Response (LSTM)
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
      "showing": 24,
      "limit_applied": null
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

#### Response (XGBoost)
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
      "label_id": 1,
      "class_id": 0,
      "name": "Cerah / Berawan"
    }
  }
}
```

---

### 4.4 Weather Details

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/weather/details` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source` | string | No | `ecowitt` | Sumber data |
| `id` | integer | No | - | ID prediksi (default: terbaru) |

#### Response
```json
{
  "ok": true,
  "data": {
    "id": 123,
    "source": "ecowitt",
    "recorded_at": "2024-12-23T10:30:00+07:00",
    "details": {
      "uvi": 5.2,
      "vpd_outdoor": 1.2,
      "feels_like": 30.0,
      "rain_rate": 0.0,
      "solar_irradiance": 850.0,
      "wind_gust": 5.0,
      "pressure_relative": 1010.0
    }
  }
}
```

---

### 4.5 Weather History

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/weather/history` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | integer | No | 1 | Nomor halaman |
| `per_page` | integer | No | 10 | Item per halaman (max: 50) |
| `source` | string | No | `ecowitt` | Sumber data |
| `date` | string | No | - | Filter tanggal (format: `YYYY-MM-DD`) |
| `time` | string | No | - | Filter waktu (format: `HH:MM`) |
| `start_date` | string | No | - | Tanggal awal range |
| `end_date` | string | No | - | Tanggal akhir range |
| `start_time` | string | No | - | Waktu awal range (format: `HH:MM`) |
| `end_time` | string | No | - | Waktu akhir range (format: `HH:MM`) |

#### Response
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

### 4.6 Weather Graph

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/weather/graph` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `range` | string | ✅ **Yes** | - | Range: `weekly` atau `monthly` |
| `datatype` | string | ✅ **Yes** | - | Tipe data untuk chart |
| `source` | string | No | `ecowitt` | Sumber data |
| `month` | integer | No | - | Filter bulan (1-12) |

#### Response
```json
{
  "ok": true,
  "data": {
    "range": "weekly",
    "datatype": "temperature",
    "source": "ecowitt",
    "series": [
      {"date": "2024-12-17", "min": 24.5, "max": 32.1, "avg": 28.3}
    ]
  }
}
```

---

### 4.7 Labels

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/labels` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

#### Response
```json
{
  "ok": true,
  "data": [
    {"id": 1, "name": "Cerah / Berawan"},
    {"id": 2, "name": "Berpotensi Hujan dari Arah Utara"},
    {"id": 3, "name": "Berpotensi Hujan dari Arah Timur Laut"},
    {"id": 4, "name": "Berpotensi Hujan dari Arah Timur"},
    {"id": 5, "name": "Berpotensi Hujan dari Arah Tenggara"},
    {"id": 6, "name": "Berpotensi Hujan dari Arah Selatan"},
    {"id": 7, "name": "Berpotensi Hujan dari Arah Barat Daya"},
    {"id": 8, "name": "Berpotensi Hujan dari Arah Barat"},
    {"id": 9, "name": "Berpotensi Hujan dari Arah Barat Laut"}
  ]
}
```

---

### 4.8 Models

| Attribute | Value |
|-----------|-------|
| **Endpoint** | `GET /api/v3/models` |
| **Auth Required** | ✅ Yes (X-API-KEY) |
| **Rate Limited** | ✅ Yes |

#### Response
```json
{
  "ok": true,
  "data": [
    {"id": 1, "name": "default_xgboost", "range_prediction": 60},
    {"id": 2, "name": "default_lstm", "range_prediction": 1440}
  ]
}
```

---

## 5. Perbandingan API

### 5.1 Informasi Umum

| Aspek | API Biasa | API v3 |
|-------|-----------|--------|
| Base URL | `/api` | `/api/v3` |
| CORS | ❌ | ✅ |
| Rate Limiting | ❌ | ✅ (100/60s) |
| Auth Header | `X-API-KEY` | `X-API-KEY` |

### 5.2 Endpoint Mapping

| Fungsi | API Biasa | API v3 |
|--------|-----------|--------|
| Health Check | `GET /api/health` | `GET /api/v3/health` |
| Labels | - | `GET /api/v3/labels` |
| Models | - | `GET /api/v3/models` |
| Weather Current | `GET /api/data?type=general` | `GET /api/v3/weather/current` |
| Weather Hourly | `GET /api/data?type=hourly` | `GET /api/v3/weather/hourly` |
| Weather Details | `GET /api/data?type=details` | `GET /api/v3/weather/details` |
| Weather History | `GET /api/history` | `GET /api/v3/weather/history` |
| Weather Graph | `GET /api/graph` | `GET /api/v3/weather/graph` |

### 5.3 History Parameters (Identical)

| Parameter | API Biasa | API v3 |
|-----------|:---------:|:------:|
| `page` | ✅ | ✅ |
| `per_page` | ✅ (max 50) | ✅ (max 50) |
| `source` | ✅ | ✅ |
| `date` | ✅ | ✅ |
| `time` | ✅ | ✅ |
| `start_date` | ✅ | ✅ |
| `end_date` | ✅ | ✅ |
| `start_time` | ✅ | ✅ |
| `end_time` | ✅ | ✅ |

### 5.4 Graph Parameters (Identical)

| Parameter | API Biasa | API v3 |
|-----------|:---------:|:------:|
| `range` | ✅ Required | ✅ Required |
| `datatype` | ✅ Required | ✅ Required |
| `source` | ✅ Optional | ✅ Optional |
| `month` | ✅ Optional | ✅ Optional |

---

## 6. Error Handling

### API Biasa
```json
{
  "ok": false,
  "message": "Error description"
}
```

### API v3
```json
{
  "ok": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message"
  }
}
```

### Error Codes (API v3)

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `MISSING_API_KEY` | 401 | X-API-KEY header tidak ada |
| `INVALID_API_KEY` | 401 | API key tidak valid |
| `RATE_LIMIT_EXCEEDED` | 429 | Rate limit terlampaui |
| `INVALID_PARAMETER` | 400 | Parameter tidak valid |
| `NOT_FOUND` | 404 | Resource tidak ditemukan |
| `NO_DATA` | 404 | Data tidak tersedia |

---

## 7. Rate Limiting

### Konfigurasi
- **Limit:** 100 requests
- **Window:** 60 detik
- **Per:** IP Address

### Response Headers
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1703318460
```

### Rate Limit Exceeded Response
```json
{
  "ok": false,
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded. Try again in 30 seconds"
  }
}
```

**Headers:**
```
Retry-After: 30
X-RateLimit-Remaining: 0
```

---

## 8. Sumber Data (Label dari Database)

Semua label prediksi diambil dari tabel `label` di database:

| ID | Class ID (XGBoost) | Nama |
|----|:------------------:|------|
| 1 | 0 | Cerah / Berawan |
| 2 | 1 | Berpotensi Hujan dari Arah Utara |
| 3 | 2 | Berpotensi Hujan dari Arah Timur Laut |
| 4 | 3 | Berpotensi Hujan dari Arah Timur |
| 5 | 4 | Berpotensi Hujan dari Arah Tenggara |
| 6 | 5 | Berpotensi Hujan dari Arah Selatan |
| 7 | 6 | Berpotensi Hujan dari Arah Barat Daya |
| 8 | 7 | Berpotensi Hujan dari Arah Barat |
| 9 | 8 | Berpotensi Hujan dari Arah Barat Laut |

## 9. Model dari Database

Informasi model diambil dari tabel `model`:

| ID | Name | Range Prediction (menit) |
|----|------|-------------------------|
| 1 | default_xgboost | 60 (1 jam) |
| 2 | default_lstm | 1440 (24 jam) |
