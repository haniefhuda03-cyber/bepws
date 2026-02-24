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


