# API v3 Reference Documentation

> **Base URL**: `/api/v3`  
> **Authentication**: `X-APP-KEY` header (except noted)  
> **Rate Limit**: 100 requests/minute per IP

---

## Table of Contents
1. [Authentication](#authentication)
2. [Response Format](#response-format)
3. [Endpoints](#endpoints)
   - [Health Check](#1-health-check)
   - [Current Weather](#2-current-weather)
   - [Weather Prediction](#3-weather-prediction)
   - [Weather Details](#4-weather-details)
   - [Weather History](#5-weather-history)
   - [Graph Data](#6-graph-data)
   - [Console Receiver](#7-console-receiver)

---

## Authentication

All endpoints (except `/health` and `/weather/console`) require the `X-APP-KEY` header.

```http
X-APP-KEY: your-secret-key-here
```

| Error Code | HTTP Status | Description |
|------------|-------------|-------------|
| `MISSING_AUTH` | 401 | Header `X-APP-KEY` not provided |
| `INVALID_AUTH` | 401 | Invalid API key |

---

## Response Format

All responses follow this structure:

```json
{
  "meta": {
    "status": "success|error",
    "code": 200,
    "timestamp": "2026-02-05T03:19:13+00:00",
    "source": "ecowitt",
    "params_applied": {
      "source": "ecowitt"
    }
  },
  "data": { ... },
  "error": null
}

> **Note:** `params_applied` now appears in `meta` even for 404/Empty Data responses if valid parameters were provided.
```

### Rate Limit Headers
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 99
X-RateLimit-Reset: 1738732800
```

---

## Timezone & Datetime Guide

### Penyimpanan di Database
Semua timestamp di database disimpan dalam **UTC** (kolom `created_at` dan `date_utc`).

### Response API
Semua field `timestamp` di response menggunakan format **UTC ISO 8601**:
```
2026-02-24T03:10:01.369196+00:00
```

### Filter Pencarian (`start_date` / `end_date`)

Server menggunakan `datetime.fromisoformat()` untuk parsing — artinya **server menghormati timezone yang Anda kirim**:

| Input Client | Diparsing Sebagai | Keterangan |
|---|---|---|
| `2026-02-01T00:00:00Z` | UTC 00:00 | `Z` = UTC |
| `2026-02-01T00:00:00+07:00` | WIB 00:00 = UTC 17:00 sebelumnya | Offset WIB dihormati |
| `2026-02-01T00:00:00` | UTC 00:00 (naive) | Tanpa offset → dianggap UTC |

> [!IMPORTANT]
> Jika Anda ingin memfilter berdasarkan **waktu WIB**, selalu sertakan offset `+07:00`. Jika tidak ada offset, server menganggap input sebagai UTC.

#### Contoh Penggunaan Filter

**Mencari data tanggal 1 Feb 2026 (WIB penuh, 00:00-23:59 WIB):**
```http
GET /api/v3/weather/history?start_date=2026-02-01T00:00:00+07:00&end_date=2026-02-01T23:59:59+07:00
```

**Mencari data tanggal 1 Feb 2026 (UTC penuh):**
```http
GET /api/v3/weather/history?start_date=2026-02-01T00:00:00Z&end_date=2026-02-01T23:59:59Z
```

> [!NOTE]
> Kedua contoh di atas memberikan hasil **berbeda** karena 1 hari WIB (00:00-23:59 WIB) = 23 Feb 17:00 UTC s.d. 1 Feb 16:59 UTC.

### Predict Endpoint — Target Waktu WIB
Field `time_target_predict` dan `date_target_predict` menggunakan **WIB**:
```json
"time_target_predict": "11:00"    // WIB, bukan UTC
"date_target_predict": "24-02-26" // tanggal WIB
```

Logika: Timestamp prediksi (UTC) dikonversi ke WIB → dibulatkan ke jam → ditambah offset jam.

### Graph Endpoint — Grouping per Hari WIB
Data grafik diagregasi (AVG) **per hari WIB**, bukan UTC. SQL:
```sql
GROUP BY date(timezone('Asia/Jakarta', timezone('UTC', created_at)))
```
Sehingga data pukul 01:00 WIB (= 18:00 UTC hari sebelumnya) masuk ke hari WIB yang benar.

---

## Endpoints

### 1. Health Check

**URL**: `GET /api/v3/health`  
**Auth**: None  
**Rate Limited**: Yes

Check system health status.

#### Response
```json
{
  "meta": { "status": "success", "code": 200, "timestamp": "..." },
  "data": {
    "api_version": "v3",
    "database": "connected",
    "scheduler": "running",
    "jobs": ["fetch_ecowitt", "fetch_wunderground", "predict"]
  }
}
```

---

### 2. Current Weather

**URL**: `GET /api/v3/weather/current`  
**Auth**: Required  
**Rate Limited**: Yes

Get the latest weather data.

#### Query Parameters
| Parameter | Type | Required | Default | Values |
|-----------|------|----------|---------|--------|
| `source` | enum | No | `ecowitt` | `ecowitt`, `wunderground` |

#### Example Request
```http
GET /api/v3/weather/current?source=ecowitt
X-APP-KEY: your-key
```

#### Response
```json
{
  "meta": { "status": "success", "code": 200, "source": "ecowitt" },
  "data": {
    "id": 12345,
    "timestamp": "2026-02-05T03:15:00+00:00",
    "temp": 28.5,
    "location": "Sukapura",
    "humidity": 75,
    "dew_point": 23.2,
    "pressure": 1010.5,
    "precip_rate": 0.0,
    "wind_speed": 5.2,
    "wind_degree": 135,
    "compass": "SE"
  }
}
```

---

### 3. Weather Prediction

**URL**: `GET /api/v3/weather/predict`  
**Auth**: Required  
**Rate Limited**: Yes

Get weather predictions from ML models.

#### Query Parameters
| Parameter | Type | Required | Default | Values |
|-----------|------|----------|---------|--------|
| `source` | enum | No | `ecowitt` | `ecowitt`, `wunderground` |
| `model` | enum | No | `lstm` | `lstm`, `xgboost` |
| `limit` | int | No | `12` | `1-24` (LSTM only) |

> [!WARNING]
> Parameter `limit` is **not allowed** for XGBoost model.

#### Example: LSTM Prediction
```http
GET /api/v3/weather/predict?source=ecowitt&model=lstm&limit=6
```

```json
{
  "meta": { "status": "success", "source": "ecowitt", "model": "lstm" },
  "data": [
    {
      "id": 1,
      "timestamp": "2026-02-05T03:00:00+00:00",
      "time_target_predict": "11:00",
      "date_target_predict": "05-02-26",
      "temp": null,
      "weather_predict": 0.125
    },
    ...
  ]
}
```

#### Example: XGBoost Prediction
```http
GET /api/v3/weather/predict?source=ecowitt&model=xgboost
```

```json
{
  "meta": { "status": "success", "source": "ecowitt", "model": "xgboost" },
  "data": {
    "id": 100,
    "timestamp": "2026-02-05T03:00:00+00:00",
    "time_target_predict": "11:00",
    "date_target_predict": "05-02-26",
    "temp": null,
    "weather_predict": "Berpotensi Hujan dari Arah Tenggara"
  }
}
```

#### XGBoost Labels
| Class | Label |
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

---

### 4. Weather Details

**URL**: `GET /api/v3/weather/details`  
**Auth**: Required  
**Rate Limited**: Yes

Get detailed weather metrics (UVI, solar, pressure, etc).

#### Query Parameters
| Parameter | Type | Required | Default | Values |
|-----------|------|----------|---------|--------|
| `source` | enum | No | `ecowitt` | `ecowitt`, `wunderground` |

#### Response
```json
{
  "meta": { "status": "success", "source": "ecowitt" },
  "data": {
    "id": 12345,
    "timestamp": "2026-02-05T03:15:00+00:00",
    "vpd_outdoor": 1.25,
    "feels_like": 30.2,
    "uvi": 5,
    "solar_irradiance": 850.5,
    "wind_gust": 8.3,
    "pressure_relative": 1010.5
  }
}
```

---

### 5. Weather History

**URL**: `GET /api/v3/weather/history`  
**Auth**: Required  
**Rate Limited**: Yes

Get paginated historical weather data with filtering and sorting by `created_at`.

#### Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `source` | string | No | Data source (`ecowitt` or `wunderground`). Default: `ecowitt`. |
| `page` | int | No | Page number (min 1). Default: 1. |
| `per_page` | int | No | Items per page (1-10). Default: 5. |
| `start_date` | ISO 8601 | No | Filter mulai dari datetime ini. Gunakan offset timezone untuk presisi (lihat [Timezone Guide](#timezone--datetime-guide)). |
| `end_date` | ISO 8601 | No | Filter sampai datetime ini. |
| `sort` | string | No | Sort order: `newest` (DESC) or `oldest` (ASC). Default: `newest`. |

> [!IMPORTANT]
> **Timezone pada filter:** Jika Anda mengirim `start_date=2026-02-01T00:00:00Z` (UTC), itu setara dengan `2026-02-01T07:00:00+07:00` (WIB). Untuk mencari berdasarkan hari WIB, selalu gunakan offset `+07:00`. Lihat [Timezone Guide](#timezone--datetime-guide) untuk contoh lengkap.

> **Validation Rules:**
> - `start_date` and `end_date` must be valid ISO 8601 datetime strings.
> - If both are provided, `start_date` must be earlier than or equal to `end_date`.
> - Either one can be used alone (open-ended range).
> - `sort` only accepts `newest` or `oldest`.

#### Example Requests

**Default** (latest 5 entries):
```http
GET /api/v3/weather/history?source=ecowitt
X-APP-KEY: your-key
```

**Filter by date range**:
```http
GET /api/v3/weather/history?source=ecowitt&start_date=2026-02-01T00:00:00Z&end_date=2026-02-10T23:59:59Z&page=1&per_page=5
```

**Sort ascending** (oldest first):
```http
GET /api/v3/weather/history?source=ecowitt&sort=oldest&page=1&per_page=5
```

#### Response
```json
{
  "meta": {
    "status": "success",
    "source": "ecowitt",
    "page": 1,
    "per_page": 5,
    "total": 288,
    "total_pages": 58,
    "has_next": true,
    "has_prev": false,
    "params_applied": {
      "source": "ecowitt",
      "start_date": "2026-02-01T00:00:00+00:00",
      "end_date": "2026-02-10T23:59:59+00:00",
      "sort": "newest"
    }
  },
  "data": [
    {
      "id": 12345,
      "timestamp": "2026-02-05T03:15:00+00:00",
      "temp": 28.5,
      "humidity": 75,
      "pressure": 1010.5,
      "rain_rate": 0.0,
      "wind_speed": 5.2,
      "wind_dir": 135
    }
  ]
}
```

---

### 6. Graph Data

**URL**: `GET /api/v3/weather/graph`  
**Auth**: Required  
**Rate Limited**: Yes

Get aggregated data for graphs. Data diagregasi **per hari WIB** (bukan UTC). Lihat [Timezone Guide](#timezone--datetime-guide).

#### Parameters:

| Name | Type | Required | Description |
|---|---|---|---|
| `range` | string | **Yes** | Time range: `weekly` or `monthly`. |
| `datatype` | string | **Yes** | Type of data to graph. |
| `source` | string | No | Data source. Default: `ecowitt`. |
| `month` | int | **Yes** (monthly) | Bulan (1-12). Wajib jika `range=monthly`. |

**Allowed Datatypes**:
`temperature`, `humidity`, `rainfall`, `wind_speed`, `uvi`, `solar_radiation`, `relative_pressure`.

#### Datatype Values
| Value | Description |
|-------|-------------|
| `temperature` | Temperature (°C) |
| `humidity` | Humidity (%) |
| `rainfall` | Rainfall (mm) |
| `wind_speed` | Wind Speed (km/h) |
| `uvi` | UV Index |
| `solar_radiation` | Solar Radiation (W/m²) |
| `relative_pressure` | Relative Pressure (hPa) |

#### Example Request
```http
GET /api/v3/weather/graph?range=weekly&datatype=temperature&source=ecowitt
```

#### Response
```json
{
  "meta": {
    "status": "success",
    "source": "ecowitt",
    "range": "weekly",
    "datatype": "temperature",
    "month": 2
  },
  "data": [
    { "id": 1, "date": "2026-02-24", "x": "Senin", "y": 28.5, "status": "complete" },
    { "id": 2, "date": "2026-02-25", "x": "Selasa", "y": 27.8, "status": "partial" },
    { "id": 3, "date": "2026-02-26", "x": "Rabu", "y": null, "status": "future" }
  ],
  "summary": {
    "avg": 28.15,
    "min": 25.1,
    "max": 31.5
  }
}
```

#### Status per Hari
| Status | Keterangan |
|---|---|
| `complete` | Hari sudah lewat, ada data |
| `partial` | Hari ini, data masih berjalan |
| `no_data` | Hari sudah lewat, tidak ada data |
| `future` | Hari belum terjadi, `y` selalu `null` |

---

### 7. Console Receiver

**URL**: `POST /api/v3/weather/console`  
**URL**: `GET /api/v3/weather/console` (for compatibility)  
**Auth**: Optional (IP Whitelist & X-CONSOLE-KEY support)  
**Rate Limited**: Yes

Receive weather data from console station. Used by hardware devices.

#### Required Fields
| Field | Type | Description |
|-------|------|-------------|
| `tempf` | float | Temperature (°F) |
| `humidity` | float | Humidity (%) |
| `winddir` | float | Wind direction (0-360°) |
| `baromrelin` | float | Relative barometric pressure |

#### Optional Fields
| Field | Type | Description |
|-------|------|-------------|
| `tempinf` | float | Indoor temperature (°F) |
| `humidityin` | float | Indoor humidity (%) |
| `baromabsin` | float | Absolute pressure |
| `windspeedmph` | float | Wind speed (mph) |
| `windgustmph` | float | Wind gust (mph) |
| `solarradiation` | float | Solar radiation (W/m²) |
| `uv` | float | UV index |
| `rainratein` | float | Rain rate (in/hr) |
| `dailyrainin` | float | Daily rain (in) |
| `hourlyrainin` | float | Hourly rain (in) |

#### Example Request
```http
POST /api/v3/weather/console
Content-Type: application/x-www-form-urlencoded

tempf=80.5&humidity=75&winddir=135&baromrelin=29.92&windspeedmph=5.2
```

#### Success Response (201)
```json
{
  "meta": { "status": "success", "code": 201 },
  "data": {
    "id": 12346,
    "timestamp": "2026-02-05T03:19:13+00:00"
  }
}
```

#### Error Responses
| Code | HTTP | Description |
|------|------|-------------|
| `NO_DATA` | 400 | No data received |
| `MISSING_FIELDS` | 400 | Required fields missing |
| `INVALID_DATA_TYPE` | 400 | Non-numeric value for numeric field |
| `OUT_OF_RANGE` | 400 | Value outside acceptable range |
| `PROCESSING_FAILED` | 500 | Failed to process data |

---

## Error Codes Reference

| Error Code | HTTP | Description |
|------------|------|-------------|
| `MISSING_AUTH` | 401 | Missing X-APP-KEY header |
| `INVALID_AUTH` | 401 | Invalid API key |
| `RATE_LIMITED` | 429 | Too many requests |
| `UNKNOWN_PARAMETER` | 400 | Unknown query parameter |
| `INVALID_PARAMETER` | 400 | Invalid parameter value |
| `MISSING_PARAMETER` | 400 | Required parameter missing |
| `NO_DATA` | 404 | No data available |
| `SERVER_ERROR` | 500 | Internal server error |

---

## OpenAPI Specification

Download the OpenAPI 3.0 specification:  
`GET /api/v3/openapi.yaml`

This endpoint requires no authentication.

---

## Cache Strategy

Semua GET endpoint (kecuali `/health`) menggunakan cache dual-layer:
- **Primary**: Redis (jika tersedia)
- **Fallback**: In-memory dictionary (otomatis jika Redis mati)

| Endpoint | Cache Key | TTL | Tabel Sumber |
|---|---|---|---|
| `/weather/current` | `weather_current:{source}` | 60 detik | `weather_log_*` (1 baris terbaru) |
| `/weather/predict` | `weather_predict:{source}:{limit}` | 300 detik | `prediction_log` + 7 tabel JOIN |
| `/weather/details` | `weather_details:{source}` | 60 detik | `weather_log_ecowitt` atau `wunderground` |
| `/weather/history` | `weather_history:{src}:{pg}:{pp}:{sd}:{ed}:{sort}` | 120 detik | `weather_log_*` (paginasi) |
| `/weather/graph` | `weather_graph:{rng}:{src}:{dt}:{mo}:{yr}` | 300 detik | `weather_log_*` (aggregasi harian) |
| `/health` | Tidak di-cache | - | Selalu real-time |
| `/weather/console` | Tidak di-cache | - | Operasi tulis (POST) |

Jika cache HIT, database tidak diquery sama sekali. Jika cache MISS, data diquery dari database lalu disimpan ke cache.
Jika cache error (Redis mati), endpoint tetap berfungsi normal dengan fallback ke in-memory cache.

---

## Unit Conversion

### Kapan Konversi Terjadi

**Saat penyimpanan data ke database:**
- Ecowitt dan Wunderground: data sudah dalam satuan metrik, disimpan apa adanya.
- Console: data dalam satuan Imperial (Fahrenheit, mph, inHg, in/hr), disimpan apa adanya tanpa konversi.

**Saat API response:**
- Tidak ada konversi unit. Data dikembalikan apa adanya dari database.
- Satu-satunya transformasi: `deg_to_compass()` mengubah derajat angin ke nama arah (N, NE, E, dst.) di endpoint `/weather/current`.
- Semua timestamp diformat ke ISO 8601 UTC menggunakan `to_utc_iso()`.

**Saat prediksi ML (pipeline internal, bukan API):**
Data Console dikonversi ke satuan metrik sebelum dimasukkan ke model:

| Konversi | Fungsi | Contoh |
|---|---|---|
| Fahrenheit ke Celsius | `fahrenheit_to_celsius()` | 100 F menjadi 37.78 C |
| inHg ke hPa | `inch_hg_to_hpa()` | 29.92 inHg menjadi 1013.21 hPa |
| mph ke m/s | `mph_to_ms()` | 10 mph menjadi 4.47 m/s |
| in/hr ke mm/hr | `inch_per_hour_to_mm_per_hour()` | 0.33 in/hr menjadi 8.38 mm/hr |
| W/m2 ke lux | `wm2_to_lux()` | 100 W/m2 menjadi 12670 lux |

Konversi ini hanya terjadi di pipeline prediksi internal, bukan di response API.

### Ringkasan Satuan per Sumber Data

| Parameter | Wunderground (DB) | Ecowitt (DB) | Console (DB) |
|---|---|---|---|
| Temperature | Celsius | Celsius | Fahrenheit |
| Solar | W/m2 | lux | W/m2 |
| Wind Speed | m/s | m/s | mph |
| Pressure | hPa | hPa | inHg |
| Rain | mm/hr | mm/hr | in/hr |
