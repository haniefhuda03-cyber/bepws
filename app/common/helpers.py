"""
Helper Functions Module
========================

Shared helper functions for API endpoints.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

WIB = timezone(timedelta(hours=7))

def get_wib_now() -> datetime:
    """Get current time in WIB (UTC+7)."""
    return datetime.now(timezone.utc).astimezone(WIB)


def deg_to_compass(degrees: float) -> str:
    """
    Konversi derajat arah angin ke compass direction.
    
    Args:
        degrees: Arah angin dalam derajat (0-360)
        
    Returns:
        Compass direction string (N, NNE, NE, etc.), or None if input is None
    """
    if degrees is None:
        return None
    
    directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]
    
    idx = int((degrees + 11.25) / 22.5) % 16
    return directions[idx]


def safe_float(val, default: float = 0.0) -> float:
    """Safely convert value to float with default."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default: int = 0) -> int:
    """Safely convert value to int with default."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def fahrenheit_to_celsius(f: Optional[float]) -> Optional[float]:
    """Konversi Fahrenheit ke Celsius."""
    if f is None:
        return None
    try:
        return round((float(f) - 32) * 5 / 9, 2)
    except (ValueError, TypeError):
        return None


def inch_hg_to_hpa(inhg: Optional[float]) -> Optional[float]:
    """Konversi inHg ke hPa."""
    if inhg is None:
        return None
    try:
        return round(float(inhg) * 33.8639, 2)
    except (ValueError, TypeError):
        return None


def wm2_to_lux(wm2: Optional[float]) -> float:
    """Konversi W/m² ke lux: W/m² × 126.7"""
    if wm2 is None:
        return 0.0
    try:
        return round(float(wm2) * 126.7, 2)
    except (ValueError, TypeError):
        return 0.0


def mph_to_ms(mph: Optional[float]) -> Optional[float]:
    """Konversi mph ke m/s: mph × 0.44704"""
    if mph is None:
        return None
    try:
        return round(float(mph) * 0.44704, 2)
    except (ValueError, TypeError):
        return None


def inch_per_hour_to_mm_per_hour(inch_hr: Optional[float]) -> float:
    """Konversi in/hr ke mm/hr: in/hr × 25.4"""
    if inch_hr is None:
        return 0.0
    try:
        return round(float(inch_hr) * 25.4, 2)
    except (ValueError, TypeError):
        return 0.0


def classify_weather_condition(
    rain_rate_mm: Optional[float],
    humidity: Optional[float],
    solar_lux: Optional[float],
    wind_speed_ms: Optional[float] = None,
) -> str:
    """
    Klasifikasi kondisi cuaca saat ini berdasarkan multi-parameter sensor.

    Args:
        rain_rate_mm: Intensitas hujan dalam mm/hr (sudah dikonversi ke metric).
        humidity: Kelembaban udara (%).
        solar_lux: Intensitas cahaya matahari dalam lux.
        wind_speed_ms: Kecepatan angin dalam m/s (opsional).

    Returns:
        String kategori kondisi cuaca.
    """
    rr = safe_float(rain_rate_mm, 0.0)
    hum = safe_float(humidity, 0.0)
    lux = safe_float(solar_lux, 0.0)
    ws = safe_float(wind_speed_ms, 0.0)

    # 1. Prioritas: jika ada hujan, klasifikasi berdasarkan intensitas (BMKG)
    if rr > 10.0:
        return 'Hujan Sangat Lebat'
    if rr > 5.0:
        return 'Hujan Lebat'
    if rr > 1.0:
        return 'Hujan Sedang'
    if rr > 0.0:
        return 'Hujan Ringan'

    # 2. Tidak hujan — klasifikasi berdasarkan cahaya & kelembaban
    if lux >= 30000:
        return 'Cerah'
    if lux >= 10000:
        if hum >= 80:
            return 'Cerah Berawan'
        return 'Cerah'
    if lux >= 3000:
        if hum >= 85:
            return 'Berawan'
        return 'Cerah Berawan'

    # lux < 3000 (mendung / malam)
    if hum >= 90:
        return 'Mendung'
    if hum >= 80:
        return 'Berawan'
    return 'Cerah Berawan'


def parse_flexible_date(value: str) -> Optional[datetime]:
    """
    Parse tanggal/datetime dari berbagai format umum.
    
    Format yang didukung:
    - ISO 8601:       2026-02-01T00:00:00Z, 2026-02-01T07:00:00+07:00
    - Date only:      2026-02-01, 2026/02/01
    - Date reversed:  01-02-2026, 01/02/2026 (DD-MM-YYYY)
    - Compact:        20260201
    - With time:      2026-02-01 14:30:00, 2026-02-01 14:30
    
    Jika tidak ada timezone info, diasumsikan WIB (UTC+7) lalu dikonversi ke UTC.
    
    Returns:
        datetime object in UTC, or None if parsing fails
    """
    if not value or not value.strip():
        return None
    
    value = value.strip()
    
    # 1. Try ISO 8601 first (most standard)
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            # Naive → assume WIB input, convert to UTC
            dt = dt.replace(tzinfo=WIB).astimezone(timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        pass
    
    # 2. Try common formats
    _FORMATS = [
        # Date-only (assume start of day WIB)
        ('%Y/%m/%d', True),
        ('%d-%m-%Y', True),
        ('%d/%m/%Y', True),
        ('%Y%m%d', True),
        # Date + time
        ('%Y-%m-%d %H:%M:%S', True),
        ('%Y-%m-%d %H:%M', True),
        ('%Y/%m/%d %H:%M:%S', True),
        ('%Y/%m/%d %H:%M', True),
        ('%d-%m-%Y %H:%M:%S', True),
        ('%d-%m-%Y %H:%M', True),
        ('%d/%m/%Y %H:%M:%S', True),
        ('%d/%m/%Y %H:%M', True),
    ]
    
    for fmt, assume_wib in _FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            if assume_wib:
                dt = dt.replace(tzinfo=WIB).astimezone(timezone.utc)
            return dt
        except ValueError:
            continue
    
    return None


def to_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """
    Konversi datetime ke ISO string UTC.
    
    Args:
        dt: Datetime object
        
    Returns:
        ISO format string in UTC timezone, or None if dt is None
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def to_wib_iso(dt: Optional[datetime]) -> Optional[str]:
    """
    Konversi datetime ke ISO string WIB (UTC+7).
    
    Args:
        dt: Datetime object
        
    Returns:
        ISO format string in WIB timezone, or None if dt is None
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(WIB).isoformat()


