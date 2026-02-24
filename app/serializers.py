from datetime import datetime, timezone, timedelta
import calendar
from collections import defaultdict
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import joinedload, load_only
from sqlalchemy import func as sa_func

from . import db
from . import models
from .common import helpers
from .common.helpers import WIB, get_wib_now

_CURRENT_CACHE = {}
_LABEL_CACHE = {}  # In-memory cache untuk Label (hanya 9 entri, jarang berubah)


def _load_label_cache():
    """Load semua label ke cache sekaligus (1 query untuk 9 label)."""
    global _LABEL_CACHE
    if _LABEL_CACHE:
        return
    try:
        labels = db.session.query(models.Label).options(
            load_only(models.Label.id, models.Label.name)
        ).all()
        for label in labels:
            _LABEL_CACHE[label.id] = {
                "label_id": label.id,
                "class_id": label.id - 1,
                "name": label.name
            }
    except Exception:
        pass


def _get_prediction_label(label_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """
    Helper untuk mengkonversi label_id FK ke format label dari database.
    
    Note: label_id adalah FK ke Label.id (1-9), bukan class_id XGBoost (0-8).
    Menggunakan in-memory cache karena Label hanya 9 entri dan jarang berubah.
    """
    if label_id is None:
        return None
    
    # Cek in-memory cache terlebih dahulu
    if label_id in _LABEL_CACHE:
        return _LABEL_CACHE[label_id].copy()
    
    # Load semua label ke cache (1 query saja)
    _load_label_cache()
    if label_id in _LABEL_CACHE:
        return _LABEL_CACHE[label_id].copy()
    
    # Fallback: gunakan LABEL_MAP dari prediction_service
    try:
        from .services.prediction_service import LABEL_MAP
        class_id = label_id - 1  # Convert label_id ke class_id
        label_name = LABEL_MAP.get(class_id, 'Unknown')
        return {"label_id": label_id, "class_id": class_id, "name": label_name}
    except Exception:
        return {"label_id": label_id, "class_id": label_id - 1, "name": "Unknown"}


def _serialize_prediction_log(pl: models.PredictionLog, source: Optional[str] = None) -> Dict[str, Any]:
    """
    Serialize PredictionLog dengan struktur tabel baru.
    
    Struktur baru:
    - PredictionLog -> DataXGBoost (weather_log IDs untuk XGBoost)
    - PredictionLog -> DataLSTM (weather_log IDs untuk LSTM, dalam JSON array)
    - PredictionLog -> XGBoostPredictionResult (hasil prediksi XGBoost)
    - PredictionLog -> LSTMPredictionResult (hasil prediksi LSTM)
    """
    # Model info
    model_dict = pl.model.to_dict() if pl.model else None
    
    # Data references
    data_xgboost = pl.data_xgboost
    data_lstm = pl.data_lstm
    
    # Prediction results
    xgboost_result = pl.xgboost_result
    lstm_result = pl.lstm_result
    
    base = {
        "id": pl.id,
        "model": model_dict,
        "created_at": pl.created_at.isoformat() if pl.created_at else None,
    }
    
    # Helper: gunakan relationship yang sudah di-joinedload, fallback ke db.session.get()
    def get_weather_log_obj(relationship_attr, model_class, log_id):
        """Ambil weather log dari relationship (sudah eager loaded) atau fallback ke Session.get()."""
        if relationship_attr is not None:
            try:
                return relationship_attr.to_dict()
            except Exception:
                pass
        if log_id is None:
            return None
        try:
            log = db.session.query(model_class).filter_by(id=log_id).first()
            return log.to_dict() if log else None
        except Exception:
            return None

    if source == 'wunderground':
        base.update({
            "weather_wunderground": get_weather_log_obj(
                data_xgboost.weather_log_wunderground if data_xgboost else None,
                models.WeatherLogWunderground,
                data_xgboost.weather_log_wunderground_id if data_xgboost else None),
            "wunderground_prediction": _get_prediction_label(xgboost_result.wunderground_result_id if xgboost_result else None),
            "wunderground_lstm_data": lstm_result.wunderground_result if lstm_result else None,
        })
    elif source == 'ecowitt':
        base.update({
            "weather_ecowitt": get_weather_log_obj(
                data_xgboost.weather_log_ecowitt if data_xgboost else None,
                models.WeatherLogEcowitt,
                data_xgboost.weather_log_ecowitt_id if data_xgboost else None),
            "ecowitt_prediction": _get_prediction_label(xgboost_result.ecowitt_result_id if xgboost_result else None),
            "ecowitt_lstm_data": lstm_result.ecowitt_result if lstm_result else None,
        })
    elif source == 'console':
        base.update({
            "weather_console": get_weather_log_obj(
                data_xgboost.weather_log_console if data_xgboost else None,
                models.WeatherLogConsole,
                data_xgboost.weather_log_console_id if data_xgboost else None),
            "console_prediction": _get_prediction_label(xgboost_result.console_result_id if xgboost_result else None),
            "console_lstm_data": lstm_result.console_result if lstm_result else None,
        })
    else:
        # All sources — gunakan relationship yang sudah di-joinedload
        base.update({
            "weather_wunderground": get_weather_log_obj(
                data_xgboost.weather_log_wunderground if data_xgboost else None,
                models.WeatherLogWunderground,
                data_xgboost.weather_log_wunderground_id if data_xgboost else None),
            "weather_ecowitt": get_weather_log_obj(
                data_xgboost.weather_log_ecowitt if data_xgboost else None,
                models.WeatherLogEcowitt,
                data_xgboost.weather_log_ecowitt_id if data_xgboost else None),
            "weather_console": get_weather_log_obj(
                data_xgboost.weather_log_console if data_xgboost else None,
                models.WeatherLogConsole,
                data_xgboost.weather_log_console_id if data_xgboost else None),
            "wunderground_prediction": _get_prediction_label(xgboost_result.wunderground_result_id if xgboost_result else None),
            "ecowitt_prediction": _get_prediction_label(xgboost_result.ecowitt_result_id if xgboost_result else None),
            "console_prediction": _get_prediction_label(xgboost_result.console_result_id if xgboost_result else None),
            "wunderground_lstm_data": lstm_result.wunderground_result if lstm_result else None,
            "ecowitt_lstm_data": lstm_result.ecowitt_result if lstm_result else None,
            "console_lstm_data": lstm_result.console_result if lstm_result else None,
        })

    return base


def _inject_lstm_fields(serialized: Dict[str, Any], lstm_result, source: Optional[str] = None):
    """Inject LSTM result fields into serialized dict based on source filter."""
    if lstm_result is None:
        return
    if source == 'wunderground':
        serialized["wunderground_lstm_data"] = lstm_result.wunderground_result
    elif source == 'ecowitt':
        serialized["ecowitt_lstm_data"] = lstm_result.ecowitt_result
    elif source == 'console':
        serialized["console_lstm_data"] = lstm_result.console_result
    else:
        serialized["wunderground_lstm_data"] = lstm_result.wunderground_result
        serialized["ecowitt_lstm_data"] = lstm_result.ecowitt_result
        serialized["console_lstm_data"] = lstm_result.console_result


def _pair_companion_lstm(pl, serialized, source=None):
    """
    Pair a single XGBoost PredictionLog with its companion LSTM PredictionLog.
    Use _batch_pair_companion_lstm for multiple entries to avoid N+1 queries.
    """
    if pl.lstm_result is not None:
        return  # Already has LSTM data
    
    companion = db.session.query(models.PredictionLog).options(
        joinedload(models.PredictionLog.lstm_result),
    ).filter(
        models.PredictionLog.lstm_result_id.isnot(None),
        models.PredictionLog.created_at == pl.created_at,
    ).first()
    
    if companion and companion.lstm_result:
        _inject_lstm_fields(serialized, companion.lstm_result, source)


def _batch_pair_companion_lstm(
    pls: List[models.PredictionLog],
    serialized_list: List[Dict[str, Any]],
    source: Optional[str] = None,
):
    """
    Batch-pair XGBoost PredictionLogs with their companion LSTM PredictionLogs.
    
    Replaces N individual queries with a single IN() query for all timestamps,
    eliminating the N+1 problem in get_latest5_payload and get_history_payload.
    """
    # Collect timestamps that need companion LSTM lookup
    need_pairing: List[int] = []  # indices into pls/serialized_list
    timestamps = []
    for i, pl in enumerate(pls):
        if pl.lstm_result is None:
            need_pairing.append(i)
            timestamps.append(pl.created_at)

    if not need_pairing:
        return  # All already have LSTM data

    # Single query: fetch all companion LSTM entries at once
    companions = db.session.query(models.PredictionLog).options(
        joinedload(models.PredictionLog.lstm_result),
    ).filter(
        models.PredictionLog.lstm_result_id.isnot(None),
        models.PredictionLog.created_at.in_(timestamps),
    ).all()

    # Build created_at -> lstm_result map
    lstm_by_ts: Dict[datetime, Any] = {}
    for c in companions:
        if c.lstm_result is not None and c.created_at not in lstm_by_ts:
            lstm_by_ts[c.created_at] = c.lstm_result

    # Inject LSTM results into serialized dicts
    for idx in need_pairing:
        lstm_result = lstm_by_ts.get(pls[idx].created_at)
        if lstm_result:
            _inject_lstm_fields(serialized_list[idx], lstm_result, source)


def _pair_and_serialize(pl, source=None):
    """Serialize a PredictionLog and pair with companion LSTM result."""
    s = _serialize_prediction_log(pl, source)
    _pair_companion_lstm(pl, s, source)
    return s


def get_current_payload(source: Optional[str] = None) -> Dict[str, Any]:
    """
    Get current weather data strictly from WeatherLog tables.
    No prediction data included.
    """
    now = datetime.now(timezone.utc)
    try:
        from flask import current_app
        app_key = getattr(current_app, 'import_name', None) or id(current_app)
    except Exception:
        app_key = 'global'
    
    # 1. Try Cache
    try:
        from . import cache as _cache
        # Gunakan format key yang konsisten
        cache_key = f"weather_current:{source or 'all'}"
        cached = _cache.get(cache_key)
        if cached:
            return cached
    except Exception:
        pass

    # 2. Fetch Data (Directly from WeatherLog)
    target_source = source if source in ('ecowitt', 'wunderground', 'console') else 'ecowitt'
    
    data = None
    if target_source == 'ecowitt':
        load_fields = [
            models.WeatherLogEcowitt.id,
            models.WeatherLogEcowitt.created_at,
            models.WeatherLogEcowitt.temperature_main_outdoor,
            models.WeatherLogEcowitt.humidity_outdoor,
            models.WeatherLogEcowitt.dew_point_outdoor,
            models.WeatherLogEcowitt.pressure_relative,
            models.WeatherLogEcowitt.rain_rate,
            models.WeatherLogEcowitt.wind_speed,
            models.WeatherLogEcowitt.wind_direction,
        ]
        wl = get_latest_weather_data('ecowitt', load_fields)
        if wl:
            data = {
                "id": wl.id,
                "timestamp": helpers.to_utc_iso(wl.created_at),
                "temp": wl.temperature_main_outdoor,
                "location": models.LOCATION if hasattr(models, 'LOCATION') else "Unknown",
                "humidity": wl.humidity_outdoor,
                "dew_point": wl.dew_point_outdoor,
                "pressure": wl.pressure_relative,
                "precip_rate": wl.rain_rate,
                "wind_speed": wl.wind_speed,
                "wind_degree": wl.wind_direction,
                "compass": helpers.deg_to_compass(wl.wind_direction),
            }

    elif target_source == 'wunderground':
        load_fields = [
            models.WeatherLogWunderground.id,
            models.WeatherLogWunderground.created_at,
            models.WeatherLogWunderground.temperature,
            models.WeatherLogWunderground.humidity,
            models.WeatherLogWunderground.pressure,
            models.WeatherLogWunderground.precipitation_rate,
            models.WeatherLogWunderground.wind_speed,
            models.WeatherLogWunderground.wind_direction,
        ]
        wl = get_latest_weather_data('wunderground', load_fields)
        if wl:
             data = {
                "id": wl.id,
                "timestamp": helpers.to_utc_iso(wl.created_at),
                "temp": wl.temperature,
                "location": models.LOCATION if hasattr(models, 'LOCATION') else "Unknown",
                "humidity": wl.humidity,
                "dew_point": None,
                "pressure": wl.pressure,
                "precip_rate": wl.precipitation_rate,
                "wind_speed": wl.wind_speed,
                "wind_degree": wl.wind_direction,
                "compass": helpers.deg_to_compass(wl.wind_direction),
            }
            
    else: # Console
         load_fields = [
             models.WeatherLogConsole.id,
             models.WeatherLogConsole.date_utc,
             models.WeatherLogConsole.temperature,
             models.WeatherLogConsole.humidity,
             models.WeatherLogConsole.pressure_relative,
             models.WeatherLogConsole.rain_rate,
             models.WeatherLogConsole.wind_speed,
             models.WeatherLogConsole.wind_direction,
         ]
         wl = get_latest_weather_data('console', load_fields)
         if wl:
             data = {
                 "id": wl.id,
                 "timestamp": helpers.to_utc_iso(wl.date_utc),
                 "temp": wl.temperature,
                 "location": "Console Station",
                 "humidity": wl.humidity,
                 "pressure": wl.pressure_relative,
                 "precip_rate": wl.rain_rate,
                 "wind_speed": wl.wind_speed,
                 "wind_degree": wl.wind_direction,
                 "compass": helpers.deg_to_compass(wl.wind_direction),
             }

    if not data:
        # Cache negative result for short time
        payload = {"ok": False, "message": "No weather data available"}
    else:
        payload = {"ok": True, "data": data}
    
    # 3. Set Cache
    try:
        from . import cache as _cache
        _cache.set(cache_key, payload, timeout=60)
    except Exception:
        pass
        
    return payload


def get_prediction_payload(source: Optional[str] = None, limit: int = 5) -> Dict[str, Any]:
    """
    Get prediction logs strictly from PredictionLog tables.
    Replaces get_latest5_payload.
    
    Cache: TTL 300s (5 menit). Prediksi update per jam, cache 5 menit aman.
    """
    # 1. Try Cache
    cache_key = f"weather_predict:{source or 'all'}:{limit}"
    try:
        from . import cache as _cache
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        pass

    # 2. Query Database
    # Eager load result tables
    q = db.session.query(models.PredictionLog).options(
         joinedload(models.PredictionLog.model),
         joinedload(models.PredictionLog.xgboost_result),
         joinedload(models.PredictionLog.lstm_result),
    )
    
    # Filter hanya yang punya XGBoost result (sebagai anchor)
    q = q.filter(models.PredictionLog.xgboost_result_id.isnot(None))
    
    if source:
         src = source.lower()
         if src == 'wunderground':
             q = q.filter(models.PredictionLog.xgboost_result.has(models.XGBoostPredictionResult.wunderground_result_id.isnot(None)))
         elif src == 'ecowitt':
             q = q.filter(models.PredictionLog.xgboost_result.has(models.XGBoostPredictionResult.ecowitt_result_id.isnot(None)))
         elif src == 'console':
             q = q.filter(models.PredictionLog.xgboost_result.has(models.XGBoostPredictionResult.console_result_id.isnot(None)))

    pls = q.order_by(models.PredictionLog.created_at.desc()).limit(limit).all()
    
    # Serialize and batch-pair with companion LSTM (1 query instead of N)
    serialized_list = [_serialize_prediction_log(p, source) for p in pls]
    _batch_pair_companion_lstm(pls, serialized_list, source)
    
    payload = {"ok": True, "count": len(serialized_list), "data": serialized_list}

    # 3. Set Cache
    try:
        from . import cache as _cache
        _cache.set(cache_key, payload, timeout=300)
    except Exception:
        pass

    return payload


def get_history_payload(page: int = 1, start_date: Optional[str] = None, end_date: Optional[str] = None, data_source: Optional[str] = None, model_id: Optional[int] = None, per_page: int = 5, sort: str = 'newest') -> Dict[str, Any]:
    """
    Get history strictly from WeatherLog tables.
    Matches Requirement: "weather/history dan graph dari weatherlog, tidak ada kaitannya dari tabel lain"
    
    Model ID parameter is ignored as this is now pure weather history.
    
    Cache: TTL 120s (2 menit). Data baru masuk tiap 5 menit.
    """
    if page < 1:
        page = 1

    source = data_source.lower() if data_source and data_source.lower() in ('ecowitt', 'wunderground', 'console') else 'ecowitt'

    # 1. Try Cache
    sort = sort.lower() if sort and sort.lower() in ('newest', 'oldest') else 'newest'
    cache_key = f"weather_history:{source}:{page}:{per_page}:{start_date or ''}:{end_date or ''}:{sort}"
    try:
        from . import cache as _cache
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        pass
    
    if source == 'ecowitt':
        model_class = models.WeatherLogEcowitt
        cols_to_load = [
            models.WeatherLogEcowitt.id,
            models.WeatherLogEcowitt.created_at,
            models.WeatherLogEcowitt.temperature_main_outdoor,
            models.WeatherLogEcowitt.humidity_outdoor,
            models.WeatherLogEcowitt.pressure_relative,
            models.WeatherLogEcowitt.rain_rate,
            models.WeatherLogEcowitt.wind_speed,
            models.WeatherLogEcowitt.wind_direction,
        ]
    elif source == 'wunderground':
        model_class = models.WeatherLogWunderground
        cols_to_load = [
            models.WeatherLogWunderground.id,
            models.WeatherLogWunderground.created_at,
            models.WeatherLogWunderground.temperature,
            models.WeatherLogWunderground.humidity,
            models.WeatherLogWunderground.pressure,
            models.WeatherLogWunderground.precipitation_rate,
            models.WeatherLogWunderground.wind_speed,
            models.WeatherLogWunderground.wind_direction,
        ]
    else: # Console
        model_class = models.WeatherLogConsole
        cols_to_load = [
            models.WeatherLogConsole.id,
            models.WeatherLogConsole.date_utc, # Special case
            models.WeatherLogConsole.temperature,
            models.WeatherLogConsole.humidity,
            models.WeatherLogConsole.pressure_relative,
            models.WeatherLogConsole.rain_rate,
            models.WeatherLogConsole.wind_speed,
            models.WeatherLogConsole.wind_direction,
        ]

    # Filters
    filters = []
    if start_date:
        try:
             # Support ISOZ or naive
             dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
             if source == 'console':
                 filters.append(models.WeatherLogConsole.date_utc >= dt)
             else:
                 filters.append(model_class.created_at >= dt)
        except ValueError:
             pass 
    if end_date:
        try:
             dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
             if source == 'console':
                 filters.append(models.WeatherLogConsole.date_utc <= dt)
             else:
                 filters.append(model_class.created_at <= dt)
        except ValueError:
             pass

    # Count
    total = db.session.query(sa_func.count(model_class.id)).filter(*filters).scalar()
    
    # Query Data
    from sqlalchemy.orm import load_only
    offset = (page - 1) * per_page
    
    # Order field
    if source == 'console':
        order_col = models.WeatherLogConsole.date_utc
    else:
        order_col = model_class.created_at

    order_expr = order_col.asc() if sort == 'oldest' else order_col.desc()
    records = db.session.query(model_class).options(load_only(*cols_to_load))\
        .filter(*filters)\
        .order_by(order_expr)\
        .offset(offset).limit(per_page).all()
        
    data = []
    for r in records:
        ts = r.date_utc if source == 'console' else r.created_at
        
        # Standardize output
        if source == 'ecowitt':
            item = {
                "id": r.id,
                "timestamp": helpers.to_utc_iso(ts),
                "temp": r.temperature_main_outdoor,
                "humidity": r.humidity_outdoor,
                "pressure": r.pressure_relative,
                "rain_rate": r.rain_rate,
                "wind_speed": r.wind_speed,
                "wind_dir": r.wind_direction
            }
        elif source == 'wunderground':
             item = {
                "id": r.id,
                "timestamp": helpers.to_utc_iso(ts),
                "temp": r.temperature,
                "humidity": r.humidity,
                "pressure": r.pressure,
                "rain_rate": r.precipitation_rate,
                "wind_speed": r.wind_speed,
                "wind_dir": r.wind_direction
            }
        else: # Console
             item = {
                "id": r.id,
                "timestamp": helpers.to_utc_iso(ts),
                "temp": r.temperature,
                "humidity": r.humidity,
                "pressure": r.pressure_relative,
                "rain_rate": r.rain_rate,
                "wind_speed": r.wind_speed,
                "wind_dir": r.wind_direction
            }
        data.append(item)

    payload = {
        "ok": True,
        "page": page,
        "per_page": per_page,
        "total": total,
        "data": data,
        "source": source
    }

    # 3. Set Cache
    try:
        from . import cache as _cache
        _cache.set(cache_key, payload, timeout=120)
    except Exception:
        pass

    return payload


def get_source_current_payload(source: str) -> Dict[str, Any]:
    if source not in ('wunderground', 'ecowitt', 'console'):
        return {"ok": False, "message": "invalid source"}

    # Join dengan XGBoostPredictionResult untuk filter berdasarkan source
    q = db.session.query(models.PredictionLog).options(
        joinedload(models.PredictionLog.model),
        joinedload(models.PredictionLog.data_xgboost)
            .joinedload(models.DataXGBoost.weather_log_console),
        joinedload(models.PredictionLog.data_xgboost)
            .joinedload(models.DataXGBoost.weather_log_ecowitt),
        joinedload(models.PredictionLog.data_xgboost)
            .joinedload(models.DataXGBoost.weather_log_wunderground),
        joinedload(models.PredictionLog.data_lstm),
        joinedload(models.PredictionLog.xgboost_result),
        joinedload(models.PredictionLog.lstm_result),
    ).join(
        models.XGBoostPredictionResult,
        models.PredictionLog.xgboost_result_id == models.XGBoostPredictionResult.id
    )
    
    if source == 'wunderground':
        q = q.filter(models.XGBoostPredictionResult.wunderground_result_id.isnot(None))
    elif source == 'ecowitt':
        q = q.filter(models.XGBoostPredictionResult.ecowitt_result_id.isnot(None))
    else:  # console
        q = q.filter(models.XGBoostPredictionResult.console_result_id.isnot(None))
    
    pl = q.order_by(models.PredictionLog.created_at.desc()).first()

    if not pl:
        return {"ok": False, "message": f"No {source} prediction logs found"}
    serialized = _serialize_prediction_log(pl, source)
    _pair_companion_lstm(pl, serialized, source)
    return {"ok": True, "data": serialized}

def _deprecated_get_graph_payload(range_param: Optional[str], month: Optional[str] = None, source: Optional[str] = None, datatype: Optional[str] = None) -> Dict[str, Any]:
    if not range_param:
        return {"ok": False, "message": "Parameter 'range' required (weekly|monthly)"}
    rp = range_param.lower()
    if rp not in ("weekly", "monthly"):
        return {"ok": False, "message": "range must be 'weekly' or 'monthly'"}

    src = (source or 'ecowitt').lower()
    if src not in ('ecowitt', 'wunderground'):
        return {"ok": False, "message": "invalid source; gunakan 'ecowitt' atau 'wunderground'"}

    if not datatype:
        return {"ok": False, "message": "Parameter 'datatype' required"}
    dt = datatype.lower()

    mapping = {
        'temperature': {'ecowitt': 'temperature_main_outdoor', 'wunderground': 'temperature'},
        'relative_pressure': {'ecowitt': 'pressure_relative', 'wunderground': 'pressure'},
        'humidity': {'ecowitt': 'humidity_outdoor', 'wunderground': 'humidity'},
        'wind_speed': {'ecowitt': 'wind_speed', 'wunderground': 'wind_speed'},
        'uvi': {'ecowitt': 'uvi', 'wunderground': 'ultraviolet_radiation'},
        'rainfall': {'ecowitt': 'rain_rate', 'wunderground': 'precipitation_rate'},
        'solar_radiation': {'ecowitt': 'solar_irradiance', 'wunderground': 'solar_radiation'},
    }
    
    if dt not in mapping:
        return {"ok": False, "message": f"unknown datatype '{dt}'"}

    col_name = mapping[dt][src]

    table = models.WeatherLogEcowitt if src == 'ecowitt' else models.WeatherLogWunderground

    WIB = timezone(timedelta(hours=7))
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc.astimezone(WIB)
    year_now = now_wib.year

    if rp == 'weekly':
        start_date = (now_wib.date() - timedelta(days=now_wib.weekday()))
        end_date = start_date + timedelta(days=6)
    else:
        if month:
            try:
                month_i = int(month)
            except Exception:
                return {"ok": False, "message": "invalid month"}
            if not (1 <= month_i <= 12):
                return {"ok": False, "message": "month must be 1-12"}
        else:
            month_i = now_wib.month

        _, last_day = calendar.monthrange(year_now, month_i)
        start_date = datetime(year_now, month_i, 1, 0, 0, 0, tzinfo=WIB).date()
        end_date = datetime(year_now, month_i, last_day, 23, 59, 59, tzinfo=WIB).date()

    year_start = datetime(year_now, 1, 1, 0, 0, 0, tzinfo=WIB)
    year_end = datetime(year_now, 12, 31, 23, 59, 59, tzinfo=WIB)

    start_dt_wib = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=WIB)
    end_dt_wib = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=WIB)
    if start_dt_wib < year_start:
        start_dt_wib = year_start
    if end_dt_wib > year_end:
        end_dt_wib = year_end

    start_dt_utc = start_dt_wib.astimezone(timezone.utc)
    end_dt_utc = end_dt_wib.astimezone(timezone.utc)

    try:
        col_attr = getattr(table, col_name)
        
        # Optimization: Use SQL Aggregation instead of fetching all rows
        # Group by date(created_at). Note: This approximates UTC days.
        # For strict WIB (UTC+7) grouping, dialect specific functions are needed.
        # We use cast to Date which works across SQLite/Postgres generically.
        from sqlalchemy import cast, Date
        
        date_group = cast(table.created_at, Date)
        
        rows = (
            db.session.query(
                date_group.label('day'), 
                sa_func.avg(col_attr).label('avg_val')
            )
            .filter(table.created_at >= start_dt_utc, table.created_at <= end_dt_utc)
            .group_by(date_group)
            .all()
        )
        
        # Convert aggregated results to dict {iso_date: value}
        per_day = {}
        for r in rows:
            d_val = r[0]
            val = r[1]
            if d_val and val is not None:
                if hasattr(d_val, 'isoformat'):
                    key = d_val.isoformat()
                else:
                    key = str(d_val)
                per_day[key] = float(val)

    except Exception as e:
        return {"ok": False, "message": f"database error: {e}"}

    # Helper dates generator
    dates = []
    cur = start_dt_wib.date()
    while cur <= end_dt_wib.date():
        dates.append(cur)
        cur = cur + timedelta(days=1)

    day_name = {0: 'Senin', 1: 'Selasa', 2: 'Rabu', 3: 'Kamis', 4: 'Jumat', 5: 'Sabtu', 6: 'Minggu'}

    data_out = []
    idx = 1
    y_values = []

    for d in dates:
        d_iso = d.isoformat()
        if d > now_wib.date():
            status = 'future'
            y = None
        elif d < now_wib.date():
            # Past
            if d_iso in per_day:
                y = per_day[d_iso]
                status = 'complete' 
            else:
                y = None
                status = 'no_data'
        else:
            # Today
            if d_iso in per_day:
                y = per_day[d_iso]
                status = 'partial'
            else:
                y = None
                status = 'no_data'

        if y is not None:
            try:
                y = float(round(y, 3))
            except Exception:
                pass
            y_values.append(y)

        data_out.append({
            'id': idx,
            'date': d_iso,
            'x': day_name[d.weekday()],
            'y': y,
            'status': status,
        })
        idx += 1

    if y_values:
        summary = {'max': max(y_values), 'min': min(y_values), 'avg': float(round(sum(y_values) / len(y_values), 3))}
    else:
        summary = {'max': None, 'min': None, 'avg': None}

    month_field = None
    if rp == 'monthly':
        month_field = int(month) if month else now_wib.month

    resp = {
        'ok': True,
        'range': rp,
        'datatype': dt,
        'source': src,
        'year': year_now,
        'month': month_field,
        'summary': summary,
        'data': data_out,
    }
    return resp

def get_latest_weather_data(source: str, load_fields: Optional[List[Any]] = None) -> Any:
    """
    Helper untuk mengambil satu data cuaca terbaru dari source tertentu.
    Digunakan oleh app/api_v3.py dan app/services/prediction_service.py.
    """
    if source == 'ecowitt':
        model_class = models.WeatherLogEcowitt
        order_field = models.WeatherLogEcowitt.request_time
    elif source == 'console':
        model_class = models.WeatherLogConsole
        order_field = models.WeatherLogConsole.date_utc
    else:  # wunderground
        model_class = models.WeatherLogWunderground
        order_field = models.WeatherLogWunderground.request_time
    
    q = db.session.query(model_class)
    
    if load_fields:
        from sqlalchemy.orm import load_only
        q = q.options(load_only(*load_fields))
        
    return q.order_by(order_field.desc()).first()


def get_graph_payload(range_param: Optional[str], month: Optional[str] = None, year: Optional[str] = None, source: Optional[str] = None, datatype: Optional[str] = None) -> Dict[str, Any]:
    """
    Get graph data (daily aggregation) from WeatherLog tables.
    
    Cache: TTL 300s (5 menit). Data aggregasi harian, jarang berubah drastis.
    """
    if not range_param:
        return {"ok": False, "message": "Parameter 'range' required (weekly|monthly)"}
    rp = range_param.lower()
    if rp not in ("weekly", "monthly"):
        return {"ok": False, "message": "range must be 'weekly' or 'monthly'"}

    src = (source or 'ecowitt').lower()
    if src not in ('ecowitt', 'wunderground'):
        return {"ok": False, "message": "invalid source; gunakan 'ecowitt' atau 'wunderground'"}

    if not datatype:
        return {"ok": False, "message": "Parameter 'datatype' required"}
    dt = datatype.lower()

    mapping = {
        'temperature': {'ecowitt': 'temperature_main_outdoor', 'wunderground': 'temperature'},
        'relative_pressure': {'ecowitt': 'pressure_relative', 'wunderground': 'pressure'},
        'humidity': {'ecowitt': 'humidity_outdoor', 'wunderground': 'humidity'},
        'wind_speed': {'ecowitt': 'wind_speed', 'wunderground': 'wind_speed'},
        'uvi': {'ecowitt': 'uvi', 'wunderground': 'ultraviolet_radiation'},
        'rainfall': {'ecowitt': 'rain_rate', 'wunderground': 'precipitation_rate'},
        'solar_radiation': {'ecowitt': 'solar_irradiance', 'wunderground': 'solar_radiation'},
    }
    
    if dt not in mapping:
        return {"ok": False, "message": f"unknown datatype '{dt}'"}

    # 1. Try Cache
    cache_key = f"weather_graph:{rp}:{src}:{dt}:{month or ''}:{year or ''}"
    try:
        from . import cache as _cache
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception:
        pass

    col_name = mapping[dt][src]
    table = models.WeatherLogEcowitt if src == 'ecowitt' else models.WeatherLogWunderground
    col_attr = getattr(table, col_name)

    # Timezone & Current Time
    now_wib = get_wib_now()
    
    # Determine Year
    try:
        year_i = int(year) if year else now_wib.year
    except ValueError:
        return {"ok": False, "message": "year must be integer"}

    # Determine Date Range
    if rp == 'weekly':
        # "Minggu harus ditentukan berdasarkan tanggal aktual pada tahun tersebut"
        # Logic: Use the ISO week of 'today' applied to the requested year.
        if year_i == now_wib.year:
            # Current week
            start_date = now_wib.date() - timedelta(days=now_wib.weekday())
        else:
            # Same ISO week number in target year
            current_iso_week = now_wib.isocalendar()[1]
            try:
                # Get Monday of the same week number in target year
                start_date = datetime.fromisocalendar(year_i, current_iso_week, 1).date()
            except ValueError:
                # Fallback: Last Monday of that year
                start_date = datetime(year_i, 12, 28).date() - timedelta(days=datetime(year_i, 12, 28).weekday())

        end_date = start_date + timedelta(days=6)
    else:
        # Monthly
        month_i = int(month) if month else now_wib.month
        if not (1 <= month_i <= 12):
            return {"ok": False, "message": "month must be 1-12"}
        
        _, last_day = calendar.monthrange(year_i, month_i)
        start_date = datetime(year_i, month_i, 1).date()
        end_date = datetime(year_i, month_i, last_day).date()

    # Boundaries in WIB -> converted to UTC for filtering
    start_dt_wib = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=WIB)
    end_dt_wib = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=WIB)

    start_dt_utc = start_dt_wib.astimezone(timezone.utc)
    end_dt_utc = end_dt_wib.astimezone(timezone.utc)

    # 1. Aggregation Query (Daily Avg)
    is_sqlite = 'sqlite' in db.engine.dialect.name
    
    # Determine grouping expression based on dialect
    if is_sqlite:
         date_group = sa_func.date(table.created_at) 
    else:
         # Enterprise Grade Postgres: timezone-aware grouping
         date_group = sa_func.date(
             sa_func.timezone('Asia/Jakarta', sa_func.timezone('UTC', table.created_at))
         )

    try:
        rows = (
            db.session.query(
                date_group.label('day'), 
                sa_func.avg(col_attr).label('avg_val')
            )
            .filter(table.created_at >= start_dt_utc, table.created_at <= end_dt_utc)
            .group_by(date_group)
            .all()
        )
        
        per_day = {}
        for r in rows:
            d_val = r[0]
            val = r[1]
            if d_val and val is not None:
                 if hasattr(d_val, 'isoformat'):
                     k = d_val.isoformat()
                 else:
                     k = str(d_val)
                 per_day[k] = float(val)

        # 2. Summary Query (Raw Data - Min/Max/Avg)
        summary_row = (
            db.session.query(
                sa_func.min(col_attr),
                sa_func.max(col_attr),
                sa_func.avg(col_attr)
            )
            .filter(table.created_at >= start_dt_utc, table.created_at <= end_dt_utc)
            .first()
        )
        
        if summary_row and any(x is not None for x in summary_row):
             glob_min, glob_max, glob_avg = summary_row
             summary = {
                 'min': float(round(glob_min, 3)) if glob_min is not None else None,
                 'max': float(round(glob_max, 3)) if glob_max is not None else None,
                 'avg': float(round(glob_avg, 3)) if glob_avg is not None else None
             }
        else:
             summary = {'min': None, 'max': None, 'avg': None}

    except Exception as e:
        return {"ok": False, "message": f"database error: {e}"}

    dates = []
    cur = start_date
    while cur <= end_date:
        dates.append(cur)
        cur = cur + timedelta(days=1)

    day_name = {0: 'Senin', 1: 'Selasa', 2: 'Rabu', 3: 'Kamis', 4: 'Jumat', 5: 'Sabtu', 6: 'Minggu'}
    data_out = []
    idx = 1
    
    today_date = now_wib.date()

    for d in dates:
        d_iso = d.isoformat()
        val = per_day.get(d_iso)
        
        if d > today_date:
            status = 'future'
            y = None
        elif d == today_date:
            if val is not None:
                status = 'partial'
                y = val
            else:
                status = 'no_data'
                y = None
        else:
            if val is not None:
                status = 'complete'
                y = val
            else:
                status = 'no_data'
                y = None

        if y is not None:
            y = float(round(y, 3))

        data_out.append({
            'id': idx,
            'date': d_iso,
            'x': day_name[d.weekday()],
            'y': y,
            'status': status,
        })
        idx += 1

    month_field = month_i if rp == 'monthly' else now_wib.month

    resp = {
        'ok': True,
        'range': rp,
        'datatype': dt,
        'source': src,
        'year': year_i,
        'month': month_field,
        'summary': summary,
        'data': data_out,
    }

    # Set Cache (after successful DB query & aggregation)
    try:
        from . import cache as _cache
        _cache.set(cache_key, resp, timeout=300)
    except Exception:
        pass

    return resp