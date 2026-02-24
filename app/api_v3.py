"""
API v3 - RESTful Weather API
============================

Security Features:
- Rate limiting (100 req/min per IP)
- Strict query param validation
- Schema-based validation
- X-APP-KEY authentication

Endpoints:
1. GET /health - System health check (no auth)
2. GET /weather/current - Current weather data
3. GET /weather/predict - Weather predictions (LSTM/XGBoost)
4. GET /weather/details - Detailed weather data
5. GET /weather/history - Weather history (paginated)
6. GET /weather/graph - Graph data
7. POST/GET /weather/console - Console station data receiver (no auth)
"""

import os
import re
import time
import hmac
import logging
import threading
from functools import wraps
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from flask import Blueprint, jsonify, request, g
from sqlalchemy import text, func as sa_func
from sqlalchemy.orm import load_only, joinedload

from . import db, scheduler
from . import models
from . import serializers
from .jobs import process_console_data
from .services.prediction_service import LABEL_MAP
from .common import helpers

# =====================================================================
# BLUEPRINT
# =====================================================================

bp_v3 = Blueprint('api_v3', __name__, url_prefix='/api/v3')

# =====================================================================
# TIMEZONE
# =====================================================================

WIB = timezone(timedelta(hours=7))

# =====================================================================
# CONSTANTS
# =====================================================================

LOCATION = "Sukapura"  # dari neighborhood Wunderground

# =====================================================================
# RATE LIMITER (In-Memory, Thread-Safe)
# =====================================================================

class RateLimiter:
    """
    Thread-safe in-memory rate limiter with bounded memory.
    
    Enterprise Features:
    - Periodic cleanup of stale IP entries (setiap 100 request)
    - Hard cap pada jumlah tracked IPs (default 10,000)
    - Eviction policy: LRU (Least Recently Used) saat cap tercapai
    """
    
    MAX_TRACKED_IPS = 10_000  # Hard cap untuk mencegah OOM
    CLEANUP_INTERVAL = 100    # Cleanup setiap N request
    
    def __init__(self, max_requests=100, window_seconds=60):
        self._requests = defaultdict(list)
        self._lock = threading.Lock()
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._request_count = 0
    
    def _cleanup_stale_entries(self, now: float):
        """
        Hapus semua IP yang tidak punya request dalam window terakhir.
        Dipanggil secara periodik untuk mencegah memory leak.
        """
        window_start = now - self.window_seconds
        stale_keys = [
            k for k, timestamps in self._requests.items()
            if not timestamps or timestamps[-1] <= window_start
        ]
        for k in stale_keys:
            del self._requests[k]
        
        if stale_keys:
            logging.debug(f"[RateLimiter] Cleaned {len(stale_keys)} stale IPs. Active: {len(self._requests)}")
    
    def _evict_oldest_if_needed(self):
        """
        Jika jumlah tracked IPs melebihi cap, hapus IP dengan
        aktivitas paling lama (LRU eviction).
        """
        if len(self._requests) <= self.MAX_TRACKED_IPS:
            return
        
        # Sort by last activity timestamp (ascending) dan hapus yang tertua
        sorted_keys = sorted(
            self._requests.keys(),
            key=lambda k: self._requests[k][-1] if self._requests[k] else 0
        )
        evict_count = len(self._requests) - self.MAX_TRACKED_IPS
        for k in sorted_keys[:evict_count]:
            del self._requests[k]
        
        logging.warning(f"[RateLimiter] Evicted {evict_count} oldest IPs (cap: {self.MAX_TRACKED_IPS})")
    
    def is_allowed(self, key: str) -> tuple:
        """Check if request is allowed. Returns (allowed, remaining, reset_time)."""
        now = time.time()
        window_start = now - self.window_seconds
        
        with self._lock:
            self._request_count += 1
            
            # Periodic cleanup setiap N request
            if self._request_count % self.CLEANUP_INTERVAL == 0:
                self._cleanup_stale_entries(now)
                self._evict_oldest_if_needed()
            
            # Clean old requests untuk key ini
            self._requests[key] = [t for t in self._requests[key] if t > window_start]
            
            current = len(self._requests[key])
            remaining = max(0, self.max_requests - current - 1)
            reset_time = int(now + self.window_seconds)
            
            if current >= self.max_requests:
                return False, 0, reset_time
            
            self._requests[key].append(now)
            return True, remaining, reset_time

# Global rate limiter instance
_rate_limiter = RateLimiter(
    max_requests=int(os.environ.get('RATE_LIMIT_REQUESTS', 100)),
    window_seconds=int(os.environ.get('RATE_LIMIT_WINDOW', 60))
)

# =====================================================================
# QUERY PARAM VALIDATION SCHEMAS
# =====================================================================

PARAM_SCHEMAS = {
    'source': {
        'type': 'enum',
        'values': ['ecowitt', 'wunderground'],
        'default': 'ecowitt',
        'required': False
    },
    'model': {
        'type': 'enum',
        'values': ['lstm', 'xgboost'],
        'default': 'lstm',
        'required': False
    },
    'limit': {
        'type': 'int',
        'min': 1,
        'max': 24,
        'default': 12,
        'required': False
    },
    'range': {
        'type': 'enum',
        'values': ['weekly', 'monthly'],
        'required': True
    },
    'datatype': {
        'type': 'enum',
        'values': ['temperature', 'humidity', 'rainfall', 'wind_speed', 'uvi', 'solar_radiation', 'relative_pressure'],
        'required': True
    },
    'month': {
        'type': 'int',
        'min': 1,
        'max': 12,
        'required': False
    },
    'page': {
        'type': 'int',
        'min': 1,
        'default': 1,
        'required': False
    },
    'per_page': {
        'type': 'int',
        'min': 1,
        'max': 10,
        'default': 5,
        'required': False
    },
    'date': {
        'type': 'date',
        'format': r'^\d{4}-\d{2}-\d{2}$',
        'required': False
    },
    'time': {
        'type': 'time',
        'format': r'^\d{2}:\d{2}$',
        'required': False
    },
    'start_date': {
        'type': 'iso8601',
        'required': False
    },
    'end_date': {
        'type': 'iso8601',
        'required': False
    },
    'sort': {
        'type': 'enum',
        'values': ['newest', 'oldest'],
        'default': 'newest',
        'required': False
    }
}

# Allowed query params per endpoint
ENDPOINT_PARAMS = {
    'health': [],
    'weather_current': ['source'],
    'weather_predict': ['source', 'model', 'limit'],
    'weather_details': ['source'],
    'weather_history': ['source', 'page', 'per_page', 'start_date', 'end_date', 'sort'],
    'weather_graph': ['range', 'datatype', 'source', 'month'],
    'weather_console': []  # POST accepts form data
}


# =====================================================================
# HELPER FUNCTIONS
# =====================================================================

def _meta(status="success", code=200, source=None, extra=None):
    """Build standard meta response."""
    m = {
        "status": status,
        "code": code,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if source:
        m["source"] = source
    if extra:
        m.update(extra)
    return m


def _error(code, message, status_code=400, extra=None):
    """Build standard error response."""
    return jsonify({
        "meta": _meta("error", status_code, extra=extra),
        "error": {
            "code": code,
            "message": message
        },
        "data": None
    }), status_code

# =====================================================================
# AUTH DECORATOR
# =====================================================================

def require_auth(f):
    """Decorator untuk require X-APP-KEY header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        app_key = os.environ.get('APPKEY')
        
        # APPKEY wajib dikonfigurasi di production
        if not app_key:
            logging.warning("[Auth] APPKEY not configured in environment")
            return _error("SERVER_CONFIG", "Authentication not configured", 500)
        
        provided_key = request.headers.get('X-APP-KEY')
        
        if not provided_key:
            return _error("MISSING_AUTH", "X-APP-KEY header is required", 401)
        
        # Use timing-safe comparison to prevent timing attacks
        if not hmac.compare_digest(provided_key.encode(), app_key.encode()):
            return _error("INVALID_AUTH", "Invalid X-APP-KEY", 401)
        
        return f(*args, **kwargs)
    return decorated


# =====================================================================
# RATE LIMITING DECORATOR
# =====================================================================

def rate_limit(f):
    """Decorator untuk rate limiting per IP."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Get client IP (supports reverse proxy)
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        if client_ip:
            client_ip = client_ip.split(',')[0].strip()
        
        allowed, remaining, reset_time = _rate_limiter.is_allowed(client_ip)
        
        # Add rate limit headers to response
        g.rate_limit_remaining = remaining
        g.rate_limit_reset = reset_time
        g.rate_limit_limit = _rate_limiter.max_requests
        
        if not allowed:
            response = jsonify({
                "meta": _meta("error", 429),
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Too many requests. Please slow down."
                },
                "data": None
            })
            response.headers['X-RateLimit-Limit'] = str(_rate_limiter.max_requests)
            response.headers['X-RateLimit-Remaining'] = '0'
            response.headers['X-RateLimit-Reset'] = str(reset_time)
            response.headers['Retry-After'] = str(_rate_limiter.window_seconds)
            return response, 429
        
        return f(*args, **kwargs)
    return decorated


# =====================================================================
# STRICT QUERY PARAM VALIDATOR
# =====================================================================

def strict_params(endpoint_name):
    """
    Decorator untuk validasi ketat query params.
    Rejects unknown params dan validates format.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            allowed_params = ENDPOINT_PARAMS.get(endpoint_name, [])
            
            # Check for unknown params
            for param in request.args:
                if param not in allowed_params:
                    return _error(
                        "UNKNOWN_PARAMETER",
                        f"Unknown query parameter: '{param}'. Allowed: {', '.join(allowed_params) if allowed_params else 'none'}",
                        400
                    )
            
            # Validate each provided param
            for param, value in request.args.items():
                schema = PARAM_SCHEMAS.get(param)
                if not schema:
                    continue
                
                # Check empty values
                if value.strip() == '':
                    return _error(
                        "INVALID_PARAMETER",
                        f"Query param '{param}' cannot be empty",
                        400
                    )
                
                # Check for leading/trailing spaces (Strict No Space Policy)
                if value != value.strip():
                     return _error(
                        "INVALID_PARAMETER",
                        f"Query param '{param}' cannot contain spaces",
                        400
                    )

                
                # Type validation
                if schema['type'] == 'enum':
                    if value.lower() not in schema['values']:
                        return _error(
                            "INVALID_PARAMETER",
                            f"Invalid value for '{param}'. Allowed: {', '.join(schema['values'])}",
                            400
                        )
                
                elif schema['type'] == 'int':
                    try:
                        int_val = int(value)
                        if 'min' in schema and int_val < schema['min']:
                            return _error(
                                "INVALID_PARAMETER",
                                f"'{param}' must be >= {schema['min']}",
                                400
                            )
                        if 'max' in schema and int_val > schema['max']:
                            return _error(
                                "INVALID_PARAMETER",
                                f"'{param}' must be <= {schema['max']}",
                                400
                            )
                    except ValueError:
                        return _error(
                            "INVALID_PARAMETER",
                            f"'{param}' must be a valid integer",
                            400
                        )
                
                elif schema['type'] in ('date', 'time'):
                    if not re.match(schema['format'], value):
                        return _error(
                            "INVALID_PARAMETER",
                            f"Invalid format for '{param}'",
                            400
                        )
                
                elif schema['type'] == 'iso8601':
                    try:
                        datetime.fromisoformat(value.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        return _error(
                            "INVALID_PARAMETER",
                            f"'{param}' must be a valid ISO 8601 datetime (e.g. 2026-02-01T00:00:00Z)",
                            400
                        )
            
            return f(*args, **kwargs)
        return decorated
    return decorator


# =====================================================================
# RATE LIMIT HEADERS (after_request for blueprint)
# =====================================================================

@bp_v3.after_request
def add_rate_limit_headers(response):
    """Add rate limit headers to all API responses."""
    if hasattr(g, 'rate_limit_limit'):
        response.headers['X-RateLimit-Limit'] = str(g.rate_limit_limit)
        response.headers['X-RateLimit-Remaining'] = str(g.rate_limit_remaining)
        response.headers['X-RateLimit-Reset'] = str(g.rate_limit_reset)
    return response


# =====================================================================
# 0. OPENAPI SPECIFICATION ENDPOINT
# =====================================================================

@bp_v3.route('/openapi.yaml', methods=['GET'])
def openapi_spec():
    """
    Serve OpenAPI specification file.
    No authentication required.
    """
    import pathlib
    
    # Find the openapi.yaml file relative to the app
    app_dir = pathlib.Path(__file__).parent.parent
    openapi_path = app_dir / 'docs' / 'openapi.yaml'
    
    if not openapi_path.exists():
        return _error("NOT_FOUND", "OpenAPI specification not found", 404)
    
    try:
        with open(openapi_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        from flask import Response
        return Response(content, mimetype='text/yaml')
    except Exception as e:
        logging.error(f"Failed to read OpenAPI spec: {e}")
        return _error("SERVER_ERROR", "Failed to load OpenAPI specification", 500)


# =====================================================================
# 1. HEALTH ENDPOINT
# =====================================================================

@bp_v3.route('/health', methods=['GET'])
@rate_limit
@strict_params('health')
def health():
    """
    Health check endpoint (no auth).
    Returns database, scheduler, and API status.
    """
    ok = True
    data = {
        "api_version": "v3",
        "database": "unknown",
        "scheduler": "unknown"
    }
    
    # Check database
    try:
        db.session.execute(text('SELECT 1'))
        data["database"] = "connected"
    except Exception as e:
        ok = False
        data["database"] = "error"  # Don't leak error details
        logging.error(f"Health check DB error: {e}")
    
    # Check scheduler
    try:
        if scheduler is None:
            data["scheduler"] = "not_initialized"
        else:
            is_running = getattr(scheduler, 'running', False)
            if is_running:
                data["scheduler"] = "running"
                jobs = scheduler.get_jobs() if hasattr(scheduler, 'get_jobs') else []
                data["jobs"] = [j.id for j in jobs]
            else:
                data["scheduler"] = "stopped"
    except Exception as e:
        data["scheduler"] = "error"  # Don't leak error details
        logging.error(f"Health check scheduler error: {e}")
    
    return jsonify({
        "meta": _meta("success" if ok else "error", 200 if ok else 500),
        "data": data
    }), 200 if ok else 500


# =====================================================================
# 2. CURRENT WEATHER ENDPOINT
# =====================================================================

@bp_v3.route('/weather/current', methods=['GET'])
@rate_limit
@require_auth
@strict_params('weather_current')
def weather_current():
    """
    Get current weather data.
    Query params: source (ecowitt|wunderground, default: ecowitt)
    """
    source = request.args.get('source', 'ecowitt')
    
    # Use serializer
    payload = serializers.get_current_payload(source=source)
    
    if not payload.get('ok'):
        return _error("NO_DATA", payload.get('message', "No weather data available"), 404, extra={"source": source})
        
    return jsonify({
        "meta": _meta(source=source),
        "data": payload.get('data')
    }), 200


# =====================================================================
# 3. PREDICT ENDPOINT
# =====================================================================

@bp_v3.route('/weather/predict', methods=['GET'])
@rate_limit
@require_auth
@strict_params('weather_predict')
def weather_predict():
    """
    Get weather predictions.
    Query params:
        - source: ecowitt|wunderground (default: ecowitt)
        - model: lstm|xgboost (default: lstm)
        - limit: 1-24, default 12 (for lstm only, error if used with xgboost)
    """
    source = request.args.get('source', 'ecowitt')
    model = request.args.get('model', 'lstm').lower().strip()
    
    # Validate limit
    limit_raw = request.args.get('limit')
    limit = 12
    if limit_raw:
        try:
            limit = int(limit_raw)
        except ValueError:
            return _error("INVALID_PARAMETER", "Limit must be valid integer")
            
    if model == 'xgboost' and limit_raw:
         return _error("INVALID_PARAMETER", "Limit not allowed for XGBoost")
         
    # Call Serializer
    # Helper: get_prediction_payload returns a list.
    # Note: get_prediction_payload di serializers.py didesain generik.
    # Kita perlu sesuaikan outputnya agar sama dengan format response v3 yang lama
    # yaitu XGBoost return single object, LSTM return array.
    
    # Namun `get_prediction_payload` yang baru saya buat mengembalikan LIST of prediction logs.
    # Ini mungkin tidak cocok 100% dengan endpoint ini yang mengharapkan:
    # XGBoost -> Single object (latest)
    # LSTM -> Array of hourly predictions (from single latest log)
    
    # Wait, `get_prediction_payload` logic was:
    # "Get prediction logs strictly from PredictionLog tables."
    # AND it handles: "Serialize and batch-pair with companion LSTM"
    
    # Endpoint `weather_predict` sebelumnya melogika:
    # Ambil 1 PredictionLog TERBARU.
    # Jika XGBoost: return result XGBoost dari log tersebut.
    # Jika LSTM: return result LSTM (array) dari log tersebut.
    
    # Serializer `get_prediction_payload` yang saya buat return multiple logs (limit).
    # Ini cocok untuk dashboard history prediksi, TAPI endpoint ini `/weather/predict`
    # sepertinya untuk "Latest Prediction".
    
    # Mari kita gunakan logic `get_prediction_payload` TAPI limit=1.
    payload = serializers.get_prediction_payload(source=source, limit=1)
    
    if not payload.get('data'):
        return _error("NO_DATA", "No prediction data available", 404)
        
    latest_log = payload['data'][0] # Serialized PredictionLog
    
    # Now extrat specific part based on model
    log_id = latest_log['id']
    timestamp_iso = latest_log['created_at'] # UTC ISO
    
    # Convert TS to WIB for target calc
    # Note: Serializer returns ISO string. We parse back.
    ts_utc = datetime.fromisoformat(timestamp_iso.replace('Z', '+00:00'))
    ts_wib = ts_utc.astimezone(WIB)
    base_hour_wib = ts_wib.replace(minute=0, second=0, microsecond=0)
    
    if model == 'xgboost':
        # Extract XGBoost prediction
        # Structure: "ecowitt_prediction": {"name": "Hujan Ringan", ...}
        pred_key = f"{source}_prediction"
        pred_obj = latest_log.get(pred_key)
        
        if not pred_obj:
             return _error("NO_DATA", f"No XGBoost prediction for {source}", 404)
             
        target_dt_wib = base_hour_wib + timedelta(hours=1)
        data = {
            "id": log_id,
            "timestamp": timestamp_iso,
            "time_target_predict": target_dt_wib.strftime("%H:%M"),
            "date_target_predict": target_dt_wib.strftime("%d-%m-%y"),
            "temp": None, 
            "weather_predict": pred_obj.get('name')
        }
        
    else: # LSTM
        # Extract LSTM prediction
        # Structure: "ecowitt_lstm_data": [0.0, 0.1, ...]
        lstm_key = f"{source}_lstm_data"
        result_array = latest_log.get(lstm_key)
        
        if not result_array:
             return _error("NO_DATA", f"No LSTM prediction for {source}", 404)
             
        predictions = []
        for i in range(min(limit, len(result_array))):
            hour_offset = i + 1
            target_dt_wib = base_hour_wib + timedelta(hours=hour_offset)
            predictions.append({
                "id": i + 1,
                "timestamp": timestamp_iso,
                "time_target_predict": target_dt_wib.strftime("%H:%M"),
                "date_target_predict": target_dt_wib.strftime("%d-%m-%y"),
                "temp": None,
                "weather_predict": round(result_array[i], 3) if result_array[i] is not None else None
            })
        data = predictions

    return jsonify({
        "meta": _meta(source=source, extra={"model": model}),
        "data": data
    }), 200


# =====================================================================
# 4. DETAILS ENDPOINT
# =====================================================================

@bp_v3.route('/weather/details', methods=['GET'])
@rate_limit
@require_auth
@strict_params('weather_details')
def weather_details():
    """
    Get detailed weather data.
    Query params: source (ecowitt|wunderground, default: ecowitt)
    
    Cache: TTL 60s. Data terbaru saja, sama dengan /weather/current.
    """
    # Source validation handled by @strict_params
    source = request.args.get('source', 'ecowitt')
    
    # Build params_applied early
    params_applied = {}
    if request.args.get('source'):
        params_applied["source"] = source
    
    extra_meta_success = {"params_applied": params_applied} if params_applied else None
    
    # 1. Try Cache
    cache_key = f"weather_details:{source}"
    try:
        from app import cache as _cache
        cached = _cache.get(cache_key)
        if cached is not None:
            return jsonify({
                "meta": _meta(source=source, extra=extra_meta_success),
                "data": cached
            }), 200
    except Exception:
        pass
    
    # 2. Query latest data
    if source == 'ecowitt':
        load_fields = [
            models.WeatherLogEcowitt.id,
            models.WeatherLogEcowitt.created_at,
            models.WeatherLogEcowitt.vpd_outdoor,
            models.WeatherLogEcowitt.temperature_feels_like_outdoor,
            models.WeatherLogEcowitt.uvi,
            models.WeatherLogEcowitt.solar_irradiance,
            models.WeatherLogEcowitt.wind_gust,
            models.WeatherLogEcowitt.pressure_relative,
        ]
    else:
        load_fields = [
            models.WeatherLogWunderground.id,
            models.WeatherLogWunderground.created_at,
            models.WeatherLogWunderground.ultraviolet_radiation,
            models.WeatherLogWunderground.solar_radiation,
            models.WeatherLogWunderground.wind_gust,
            models.WeatherLogWunderground.pressure,
        ]

    wl = serializers.get_latest_weather_data(source, load_fields=load_fields)
    
    if not wl:
        return _error("NO_DATA", "No weather data available", 404, extra=extra_meta_success)
    
    # Build response
    if source == 'ecowitt':
        data = {
            "id": wl.id,
            "timestamp": helpers.to_utc_iso(wl.created_at),
            "vpd_outdoor": wl.vpd_outdoor,
            "feels_like": wl.temperature_feels_like_outdoor,
            "uvi": wl.uvi,
            "solar_irradiance": wl.solar_irradiance,
            "wind_gust": wl.wind_gust,
            "pressure_relative": wl.pressure_relative,
        }
    else:
        data = {
            "id": wl.id,
            "timestamp": helpers.to_utc_iso(wl.created_at),
            "vpd_outdoor": None,
            "feels_like": None,
            "uvi": wl.ultraviolet_radiation,
            "solar_irradiance": wl.solar_radiation,
            "wind_gust": wl.wind_gust,
            "pressure_relative": wl.pressure,
        }
    
    # 3. Set Cache
    try:
        from app import cache as _cache
        _cache.set(cache_key, data, timeout=60)
    except Exception:
        pass
    
    return jsonify({
        "meta": _meta(source=source, extra=extra_meta_success),
        "data": data
    }), 200


# =====================================================================
# 5. HISTORY ENDPOINT
# =====================================================================

@bp_v3.route('/weather/history', methods=['GET'])
@rate_limit
@require_auth
@strict_params('weather_history')
def weather_history():
    """
    Get paginated weather history with filtering and sorting.
    Query params:
        - source: ecowitt|wunderground (default: ecowitt)
        - page: integer >= 1 (default: 1)
        - per_page: 1-10 (default: 5)
        - start_date: ISO 8601 datetime, filter from (optional)
        - end_date: ISO 8601 datetime, filter until (optional)
        - sort: 'newest' (DESC) or 'oldest' (ASC). Default: 'newest'
    """
    # Params
    source = request.args.get('source', 'ecowitt')
    page = int(request.args.get('page') or 1)
    per_page = int(request.args.get('per_page') or 5)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    sort = request.args.get('sort', 'newest')
    
    # Use serializer
    payload = serializers.get_history_payload(
        page=page,
        per_page=per_page,
        start_date=start_date,
        end_date=end_date,
        data_source=source,
        sort=sort
    )
    
    if not payload.get('ok'):
        return _error("INVALID_REQUEST", payload.get('message', "Request failed"), 400)
    
    # Build Extra Meta
    total = payload.get('total', 0)
    total_pages = (total + per_page - 1) // per_page if total > 0 else 0
    
    extra_meta = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }
    
    return jsonify({
        "meta": _meta(source=payload.get('source'), extra=extra_meta),
        "data": payload.get('data')
    }), 200


# =====================================================================
# 6. GRAPH ENDPOINT
# =====================================================================

@bp_v3.route('/weather/graph', methods=['GET'])
@rate_limit
@require_auth
@strict_params('weather_graph')
def weather_graph():
    """
    Get graph data.
    Query params:
        - range: weekly|monthly (required)
        - datatype: temperature|humidity|rainfall|wind_speed|uvi|solar_radiation|relative_pressure (required)
        - source: ecowitt|wunderground (default: ecowitt)
        - month: 1-12 (for monthly, default: current month)
        - year: YYYY (default: current year)
    """
    # Validate range
    range_param = request.args.get('range')
    if not range_param:
        return _error("MISSING_PARAMETER", "Query param 'range' is required (weekly or monthly)")
    if range_param.lower() not in ('weekly', 'monthly'):
        return _error("INVALID_PARAMETER", "Range must be 'weekly' or 'monthly'")
    
    # Validate datatype
    datatype = request.args.get('datatype')
    if not datatype:
        return _error("MISSING_PARAMETER", "Query param 'datatype' is required")
    
    ALLOWED_DATATYPES = {
        'temperature', 'humidity', 'rainfall', 'wind_speed', 
        'uvi', 'solar_radiation', 'relative_pressure'
    }
    # Datatype validated by strict_params decorator using PARAM_SCHEMAS
    
    # Validate source
    source = request.args.get('source', 'ecowitt')
    
    # Validate month (for monthly)
    month_raw = request.args.get('month')
    if range_param.lower() == 'monthly':
        if month_raw is None:
            return _error("MISSING_PARAMETER", "Query param 'month' is required when range is 'monthly'")
        if month_raw.strip() == '':
            return _error("INVALID_PARAMETER", "Query param 'month' cannot be empty")
            
    # Validate year
    year_raw = request.args.get('year')
    if year_raw is not None:
        if year_raw.strip() == '':
             return _error("INVALID_PARAMETER", "Query param 'year' cannot be empty")
        try:
            int(year_raw)
        except ValueError:
            return _error("INVALID_PARAMETER", "Query param 'year' must be a valid integer")
    
    # Use serializers for graph logic
    payload = serializers.get_graph_payload(
        range_param=range_param,
        month=month_raw,
        year=year_raw,
        source=source,
        datatype=datatype
    )
    
    if not payload.get('ok'):
        return _error("INVALID_REQUEST", payload.get('message', 'Invalid request'))
    
    # Build params_applied
    params_applied = {
        "range": range_param.lower(),
        "datatype": datatype
    }
    if request.args.get('source'):
        params_applied["source"] = source
    if month_raw:
        params_applied["month"] = int(month_raw) if month_raw else None
    if year_raw:
        params_applied["year"] = int(year_raw)
    
    return jsonify({
        "meta": _meta(source=source, extra={
            "range": payload.get('range'),
            "datatype": payload.get('datatype'),
            "year": payload.get('year'),
            "month": payload.get('month'),
            "params_applied": params_applied
        }),
        "data": payload.get('data'),
        "summary": payload.get('summary')
    }), 200


# =====================================================================
# 7. CONSOLE DATA ENDPOINT (POST/GET) - RESTful v3
# =====================================================================

@bp_v3.route('/weather/console', methods=['POST', 'GET'])
@rate_limit
def weather_console():
    """
    Endpoint untuk menerima data dari Console Station.
    No authentication required (for device compatibility).
    
    POST: Menerima data cuaca dari console station
    GET: Juga didukung untuk kompatibilitas beberapa console
    
    Required fields: tempf, humidity, winddir, baromrelin
    
    Returns:
        201: Data berhasil disimpan
        400: No data / Invalid data / Missing required fields
        500: Server error
    """
    waktu_terima = datetime.now(timezone.utc)
    
    logging.info(f"[Console] Data diterima pada {waktu_terima.isoformat()}")
    
    # Cek apakah Console endpoint aktif (env var: CONSOLE_ENDPOINT_ENABLED)
    console_enabled = os.environ.get("CONSOLE_ENDPOINT_ENABLED", "true").lower() in ("1", "true", "yes")
    if not console_enabled:
        logging.info("[Console] Endpoint dinonaktifkan via CONSOLE_ENDPOINT_ENABLED")
        return jsonify({
            "meta": _meta("error", 503),
            "error": {
                "code": "SERVICE_DISABLED",
                "message": "Console endpoint is disabled"
            },
            "data": None
        }), 503
    
    # Get data from POST form or GET query params
    if request.method == 'POST':
        raw_data = request.form.to_dict()
    else:
        raw_data = request.args.to_dict()
    
    if not raw_data:
        logging.warning("[Console] Koneksi masuk tanpa data")
        return jsonify({
            "meta": _meta("error", 400),
            "error": {
                "code": "NO_DATA",
                "message": "No data received"
            },
            "data": None
        }), 400
    
    # =========================================================
    # SECURITY CHECK (Mandatory — at least one method required)
    # =========================================================
    
    whitelist_env = os.environ.get('CONSOLE_IP_WHITELIST')
    console_key = os.environ.get('CONSOLE_KEY')
    
    # Enterprise Policy: Tolak semua request jika tidak ada metode auth yang dikonfigurasi
    if not whitelist_env and not console_key:
        logging.error("[Console] SECURITY: No auth configured (CONSOLE_IP_WHITELIST & CONSOLE_KEY both unset). Rejecting.")
        return _error("SERVER_CONFIG", "Console authentication not configured", 503)
    
    # 1. IP Whitelist (jika dikonfigurasi)
    if whitelist_env:
        allowed_ips = [ip.strip() for ip in whitelist_env.split(',') if ip.strip()]
        client_ip = request.remote_addr
        if client_ip not in allowed_ips:
            logging.warning(f"[Console] Blocked IP: {client_ip}")
            return _error("FORBIDDEN", "Station IP not allowed", 403)

    # 2. Key Authentication (jika dikonfigurasi)
    if console_key:
        # Check header, form/query 'key', or 'PASSKEY' (common in weather stations)
        req_key = request.headers.get('X-CONSOLE-KEY') or raw_data.get('key') or raw_data.get('PASSKEY') or raw_data.get('CONSOLE_KEY')
        
        if not req_key or not hmac.compare_digest(req_key, console_key):
            logging.warning(f"[Console] Auth failed from {request.remote_addr}")
            return _error("UNAUTHORIZED", "Invalid Console Key", 401)
    
    # =========================================================
    # FIELD VALIDATION
    # =========================================================
    
    # Required fields for valid weather data
    REQUIRED_FIELDS = ['tempf', 'humidity', 'winddir', 'baromrelin']
    
    # Check required fields
    missing_fields = [f for f in REQUIRED_FIELDS if f not in raw_data or raw_data[f] == '']
    if missing_fields:
        logging.warning(f"[Console] Missing required fields: {missing_fields}")
        return jsonify({
            "meta": _meta("error", 400),
            "error": {
                "code": "MISSING_FIELDS",
                "message": f"Missing required fields: {', '.join(missing_fields)}"
            },
            "data": None
        }), 400
    
    # Validate numeric fields
    NUMERIC_FIELDS = [
        'tempf', 'humidity', 'winddir', 'baromrelin',
        'tempinf', 'humidityin', 'baromabsin',
        'windspeedmph', 'windgustmph', 'solarradiation', 'uv',
        'rainratein', 'dailyrainin', 'hourlyrainin'
    ]
    
    invalid_fields = []
    for field in NUMERIC_FIELDS:
        if field in raw_data and raw_data[field] != '':
            try:
                float(raw_data[field])
            except (ValueError, TypeError):
                invalid_fields.append(field)
    
    if invalid_fields:
        logging.warning(f"[Console] Invalid numeric fields: {invalid_fields}")
        return jsonify({
            "meta": _meta("error", 400),
            "error": {
                "code": "INVALID_DATA_TYPE",
                "message": f"Expected numeric values for: {', '.join(invalid_fields)}"
            },
            "data": None
        }), 400
    
    # Range validation for key fields
    try:
        temp = float(raw_data.get('tempf', 0))
        humidity = float(raw_data.get('humidity', 0))
        winddir = float(raw_data.get('winddir', 0))
        
        # Temperature: -40°F to 140°F (-40°C to 60°C)
        if temp < -40 or temp > 140:
            return jsonify({
                "meta": _meta("error", 400),
                "error": {
                    "code": "OUT_OF_RANGE",
                    "message": f"Temperature out of range (-40 to 140°F): {temp}"
                },
                "data": None
            }), 400
        
        # Humidity: 0-100%
        if humidity < 0 or humidity > 100:
            return jsonify({
                "meta": _meta("error", 400),
                "error": {
                    "code": "OUT_OF_RANGE",
                    "message": f"Humidity out of range (0-100%): {humidity}"
                },
                "data": None
            }), 400
        
        # Wind direction: 0-360°
        if winddir < 0 or winddir > 360:
            return jsonify({
                "meta": _meta("error", 400),
                "error": {
                    "code": "OUT_OF_RANGE",
                    "message": f"Wind direction out of range (0-360°): {winddir}"
                },
                "data": None
            }), 400
            
    except (ValueError, TypeError) as e:
        return jsonify({
            "meta": _meta("error", 400),
            "error": {
                "code": "VALIDATION_ERROR",
                "message": str(e)
            },
            "data": None
        }), 400
    
    # Filter sensitive fields sebelum logging (PASSKEY, key, CONSOLE_KEY)
    _SENSITIVE_FIELDS = {'PASSKEY', 'key', 'CONSOLE_KEY', 'passkey'}
    safe_data = {k: ('***' if k in _SENSITIVE_FIELDS else v) for k, v in raw_data.items()}
    logging.debug(f"[Console] Raw data: {safe_data}")
    
    try:
        result = process_console_data(raw_data)
        
        if result:
            logging.info(f"[Console] Data berhasil diproses (ID: {result.id})")
            return jsonify({
                "meta": _meta("success", 201),
                "data": {
                    "id": result.id,
                    "timestamp": helpers.to_utc_iso(result.created_at)
                }
            }), 201
        else:
            logging.warning("[Console] Gagal memproses data")
            return jsonify({
                "meta": _meta("error", 500),
                "error": {
                    "code": "PROCESSING_FAILED",
                    "message": "Failed to process console data"
                },
                "data": None
            }), 500
    
    except Exception as e:
        logging.error(f"[Console] Error: {e}")
        db.session.rollback()
        return jsonify({
            "meta": _meta("error", 500),
            "error": {
                "code": "SERVER_ERROR",
                "message": "Internal server error"
            },
            "data": None
        }), 500

