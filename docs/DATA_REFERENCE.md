# Data Reference: Fetch & Storage

Data disimpan langsung ke database tanpa konversi unit.

---

## Timestamp Handling

| Sumber | Source Field | Kolom DB | Keterangan |
|--------|--------------|----------|------------|
| **Wunderground** | `obsTimeUtc` | `request_time` | ISO 8601 → UTC |
| **Ecowitt** | root `time` | `request_time` | Epoch → UTC |
| **Console** | `dateutc` | `date_utc` | Device timestamp |

---

## Wunderground

### Data dari API

| No | Parameter | Unit |
|----|-----------|------|
| 1 | Temperature | °C |
| 2 | Heat Index | °C |
| 3 | Dew Point | °C |
| 4 | Wind Chill | °C |
| 5 | Humidity | % |
| 6 | Pressure | hPa |
| 7 | Wind Speed | m/s |
| 8 | Wind Gust | m/s |
| 9 | Wind Direction | ° |
| 10 | Solar Radiation | W/m² |
| 11 | UV Index | - |
| 12 | Precipitation Rate | mm/hr |
| 13 | Precipitation Total | mm |

### Disimpan ke `weather_log_wunderground`

| No | Kolom DB | Unit |
|----|----------|------|
| 1 | `temperature` | °C |
| 2 | `humidity` | % |
| 3 | `pressure` | hPa |
| 4 | `wind_speed` | m/s |
| 5 | `wind_gust` | m/s |
| 6 | `wind_direction` | ° |
| 7 | `solar_radiation` | W/m² |
| 8 | `ultraviolet_radiation` | - |
| 9 | `precipitation_rate` | mm/hr |
| 10 | `precipitation_total` | mm |
| 11 | `request_time` | UTC |
| 12 | `created_at` | UTC |

---

## Ecowitt

### Data dari API

| No | Kategori | Parameter | Unit |
|----|----------|-----------|------|
| 1 | Outdoor | Temperature | °C |
| 2 | Outdoor | Feels Like | °C |
| 3 | Outdoor | Apparent Temperature | °C |
| 4 | Outdoor | Dew Point | °C |
| 5 | Outdoor | VPD | inHg |
| 6 | Outdoor | Humidity | % |
| 7 | Indoor | Temperature | °C |
| 8 | Indoor | Feels Like | °C |
| 9 | Indoor | Apparent Temperature | °C |
| 10 | Indoor | Dew Point | °C |
| 11 | Indoor | Humidity | % |
| 12 | Solar & UV | Solar Illumination | lux |
| 13 | Solar & UV | UV Index | - |
| 14 | Rainfall | Rain Rate | mm/hr |
| 15 | Rainfall | Rain Hourly | mm |
| 16 | Rainfall | Rain Daily | mm |
| 17 | Rainfall | Rain Event | mm |
| 18 | Rainfall | Rain Weekly | mm |
| 19 | Rainfall | Rain Monthly | mm |
| 20 | Rainfall | Rain Yearly | mm |
| 21 | Wind | Wind Speed | m/s |
| 22 | Wind | Wind Gust | m/s |
| 23 | Wind | Wind Direction | ° |
| 24 | Pressure | Relative Pressure | hPa |
| 25 | Pressure | Absolute Pressure | hPa |
| 26 | Battery | Sensor Array | - |

### Disimpan ke `weather_log_ecowitt`

| No | Kolom DB | Unit |
|----|----------|------|
| 1 | `temperature_main_outdoor` | °C |
| 2 | `temperature_feels_like_outdoor` | °C |
| 3 | `temperature_apparent_outdoor` | °C |
| 4 | `dew_point_outdoor` | °C |
| 5 | `vpd_outdoor` | inHg |
| 6 | `humidity_outdoor` | % |
| 7 | `temperature_main_indoor` | °C |
| 8 | `temperature_feels_like_indoor` | °C |
| 9 | `temperature_apparent_indoor` | °C |
| 10 | `dew_point_indoor` | °C |
| 11 | `humidity_indoor` | % |
| 12 | `solar_irradiance` | lux |
| 13 | `uvi` | - |
| 14 | `rain_rate` | mm/hr |
| 15 | `rain_hour` | mm |
| 16 | `rain_daily` | mm |
| 17 | `rain_event` | mm |
| 18 | `rain_weekly` | mm |
| 19 | `rain_monthly` | mm |
| 20 | `rain_yearly` | mm |
| 21 | `wind_speed` | m/s |
| 22 | `wind_gust` | m/s |
| 23 | `wind_direction` | ° |
| 24 | `pressure_relative` | hPa |
| 25 | `pressure_absolute` | hPa |
| 26 | `battery_sensor_array` | - |
| 27 | `request_time` | UTC |
| 28 | `created_at` | UTC |

---

## Console

### Data dari POST (Imperial Units)

| No | Kategori | Parameter | Unit |
|----|----------|-----------|------|
| 1 | System | Runtime | detik |
| 2 | System | Heap | bytes |
| 3 | Indoor | Temperature | °F |
| 4 | Indoor | Humidity | % |
| 5 | Barometer | Relative Pressure | inHg |
| 6 | Barometer | Absolute Pressure | inHg |
| 7 | Outdoor | Temperature | °F |
| 8 | Outdoor | Humidity | % |
| 9 | Wind | Wind Direction | ° |
| 10 | Wind | Wind Speed | mph |
| 11 | Wind | Wind Gust | mph |
| 12 | Wind | Max Daily Gust | mph |
| 13 | Solar & UV | Solar Radiation | W/m² |
| 14 | Solar & UV | UV Index | - |
| 15 | Rainfall | Rain Rate | in/hr |
| 16 | Rainfall | Rain Event | in |
| 17 | Rainfall | Rain Hourly | in |
| 18 | Rainfall | Rain Daily | in |
| 19 | Rainfall | Rain Weekly | in |
| 20 | Rainfall | Rain Monthly | in |
| 21 | Rainfall | Rain Yearly | in |
| 22 | Rainfall | Rain Total | in |
| 23 | Misc | VPD | kPa |

### Disimpan ke `weather_log_console`

| No | Kolom DB | Unit |
|----|----------|------|
| 1 | `runtime` | detik |
| 2 | `heap` | bytes |
| 3 | `temperature_indoor` | °F |
| 4 | `humidity_indoor` | % |
| 5 | `pressure_relative` | inHg |
| 6 | `pressure_absolute` | inHg |
| 7 | `temperature` | °F |
| 8 | `humidity` | % |
| 9 | `wind_direction` | ° |
| 10 | `wind_speed` | mph |
| 11 | `wind_gust` | mph |
| 12 | `max_daily_gust` | mph |
| 13 | `solar_radiation` | W/m² |
| 14 | `uvi` | - |
| 15 | `rain_rate` | in/hr |
| 16 | `rain_event` | in |
| 17 | `rain_hourly` | in |
| 18 | `rain_daily` | in |
| 19 | `rain_weekly` | in |
| 20 | `rain_monthly` | in |
| 21 | `rain_yearly` | in |
| 22 | `rain_total` | in |
| 23 | `vpd` | kPa |
| 24 | `date_utc` | UTC |
| 25 | `created_at` | UTC |

---

## Ringkasan Perbedaan Unit

| Parameter | Wunderground | Ecowitt | Console |
|-----------|--------------|---------|---------|
| **Temperature** | °C | °C | °F |
| **Solar** | W/m² | lux | W/m² |
| **Wind Speed** | m/s | m/s | mph |
| **Pressure** | hPa | hPa | inHg |
| **Rain** | mm | mm | in |
| **VPD** | - | inHg | kPa |
