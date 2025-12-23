"""
API v3 - RESTful API dengan CORS, Rate Limiting, dan X-API-KEY Authentication
==============================================================================

Endpoints:
- GET  /api/v3/weather/current     - Data cuaca terkini
- GET  /api/v3/weather/hourly      - Prediksi per jam (LSTM/XGBoost)
- GET  /api/v3/weather/details     - Detail prediksi
- GET  /api/v3/weather/history     - Riwayat prediksi
- GET  /api/v3/weather/graph       - Data untuk grafik
- GET  /api/v3/health              - Health check (public)

Security:
- X-API-KEY header required for protected endpoints
- Rate limiting per IP address
- CORS enabled
"""

from flask import Blueprint, jsonify, request, current_app, g
from functools import wraps
from typing import Optional
import os
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import threading

from . import db
from sqlalchemy import text, func, or_, and_
from . import models
from . import serializers
from . import cache

# =====================================================================
# BLUEPRINT SETUP
# =====================================================================

bp_v3 = Blueprint('api_v3', __name__)

# =====================================================================
# RATE LIMITING
# =====================================================================

class RateLimiter:
    """
    Simple in-memory rate limiter.
    Thread-safe implementation using locks.
    """
    def __init__(self):
        self.requests = defaultdict(list)
        self.lock = threading.Lock()
    
    def is_allowed(self, key: str, max_requests: int = 100, window_seconds: int = 60) -> tuple:
        """
        Check if request is allowed based on rate limit.
        Returns (allowed: bool, remaining: int, reset_time: int)
        """
        now = time.time()
        window_start = now - window_seconds
        
        with self.lock:
            # Clean old requests
            self.requests[key] = [t for t in self.requests[key] if t > window_start]
            
            current_count = len(self.requests[key])
            remaining = max(0, max_requests - current_count - 1)
            reset_time = int(window_start + window_seconds)
            
            if current_count >= max_requests:
                return False, 0, reset_time
            
            self.requests[key].append(now)
            return True, remaining, reset_time
    
    def clear(self):
        """Clear all rate limit data."""
        with self.lock:
            self.requests.clear()


# Global rate limiter instance
rate_limiter = RateLimiter()

# Rate limit configuration from environment
RATE_LIMIT_REQUESTS = int(os.environ.get('RATE_LIMIT_REQUESTS', 100))
RATE_LIMIT_WINDOW = int(os.environ.get('RATE_LIMIT_WINDOW', 60))


def get_client_ip() -> str:
    """Get client IP address, considering proxies."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr or 'unknown'


# =====================================================================
# AUTHENTICATION & AUTHORIZATION
# =====================================================================

def require_api_key(f):
    """
    Decorator to require X-API-KEY header for protected endpoints.
    If API_KEY is not set in environment, all requests are allowed (development mode).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = os.environ.get('API_KEY') or os.environ.get('API_READ_KEY')
        
        # If no API key configured, allow all (development mode)
        if not api_key:
            return f(*args, **kwargs)
        
        provided_key = request.headers.get('X-API-KEY')
        
        if not provided_key:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'MISSING_API_KEY',
                    'message': 'X-API-KEY header is required'
                }
            }), 401
        
        if provided_key != api_key:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'INVALID_API_KEY',
                    'message': 'Invalid API key provided'
                }
            }), 401
        
        return f(*args, **kwargs)
    return decorated_function


def apply_rate_limit(f):
    """
    Decorator to apply rate limiting to endpoints.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = get_client_ip()
        allowed, remaining, reset_time = rate_limiter.is_allowed(
            client_ip, 
            RATE_LIMIT_REQUESTS, 
            RATE_LIMIT_WINDOW
        )
        
        # Add rate limit headers to response
        g.rate_limit_remaining = remaining
        g.rate_limit_reset = reset_time
        g.rate_limit_limit = RATE_LIMIT_REQUESTS
        
        if not allowed:
            response = jsonify({
                'ok': False,
                'error': {
                    'code': 'RATE_LIMIT_EXCEEDED',
                    'message': f'Rate limit exceeded. Try again in {reset_time - int(time.time())} seconds'
                }
            })
            response.status_code = 429
            response.headers['X-RateLimit-Limit'] = str(RATE_LIMIT_REQUESTS)
            response.headers['X-RateLimit-Remaining'] = '0'
            response.headers['X-RateLimit-Reset'] = str(reset_time)
            response.headers['Retry-After'] = str(reset_time - int(time.time()))
            return response
        
        return f(*args, **kwargs)
    return decorated_function


@bp_v3.after_request
def add_rate_limit_headers(response):
    """Add rate limit headers to all responses."""
    if hasattr(g, 'rate_limit_limit'):
        response.headers['X-RateLimit-Limit'] = str(g.rate_limit_limit)
        response.headers['X-RateLimit-Remaining'] = str(g.rate_limit_remaining)
        response.headers['X-RateLimit-Reset'] = str(g.rate_limit_reset)
    return response


# =====================================================================
# HELPER FUNCTIONS
# =====================================================================

WIB = timezone(timedelta(hours=7))


def _to_wib_iso(dt):
    """Convert datetime to WIB timezone ISO format."""
    if not dt:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        wib = dt.astimezone(WIB)
        return wib.isoformat()
    except Exception:
        try:
            return dt.isoformat()
        except Exception:
            return None


def _deg_to_compass(deg: Optional[float]) -> Optional[str]:
    """Convert degrees to compass direction."""
    if deg is None:
        return None
    try:
        d = float(deg) % 360
    except Exception:
        return None
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    ix = int((d / 22.5) + 0.5) % 16
    return dirs[ix]


def _validate_source(source: Optional[str]) -> tuple:
    """Validate source parameter. Returns (valid_source, error_response or None)."""
    if not source:
        source = 'ecowitt'
    source = source.lower()
    if source not in ('ecowitt', 'wunderground'):
        return None, (jsonify({
            'ok': False,
            'error': {
                'code': 'INVALID_PARAMETER',
                'message': "Invalid source. Use 'ecowitt' or 'wunderground'"
            }
        }), 400)
    return source, None


def _validate_model(model: Optional[str]) -> tuple:
    """Validate model parameter. Returns (valid_model, error_response or None)."""
    if not model:
        model = 'lstm'
    model = model.lower()
    if model not in ('lstm', 'xgboost'):
        return None, (jsonify({
            'ok': False,
            'error': {
                'code': 'INVALID_PARAMETER',
                'message': "Invalid model. Use 'lstm' or 'xgboost'"
            }
        }), 400)
    return model, None


# =====================================================================
# API ENDPOINTS
# =====================================================================

@bp_v3.route('/health', methods=['GET'])
@apply_rate_limit
def health():
    """
    Health check endpoint (public, no API key required).
    
    Returns:
        - Database status
        - Scheduler status
        - API version info
    """
    ok = True
    details = {
        'api_version': 'v3',
        'timestamp': datetime.now(WIB).isoformat(),
    }
    
    # Check database
    try:
        db.session.execute(text('SELECT 1'))
        details['database'] = 'ok'
    except Exception as e:
        ok = False
        details['database'] = f'error: {str(e)}'
    
    # Check scheduler
    try:
        sched = current_app.extensions.get('apscheduler')
        if sched is None:
            details['scheduler'] = 'not_initialized'
        else:
            state = getattr(sched, 'state', None)
            jobs = getattr(sched, 'get_jobs', lambda: [])()
            job_ids = [j.id for j in jobs] if jobs else []
            
            if state == 1:
                details['scheduler'] = 'running'
            elif state == 0:
                details['scheduler'] = 'stopped'
            else:
                details['scheduler'] = f'unknown_state_{state}'
            
            details['scheduler_jobs'] = job_ids
    except Exception as e:
        details['scheduler'] = f'error: {str(e)}'
    
    status_code = 200 if ok else 500
    return jsonify({
        'ok': ok,
        'data': details
    }), status_code


@bp_v3.route('/weather/current', methods=['GET'])
@apply_rate_limit
@require_api_key
def weather_current():
    """
    Get current weather data.
    
    Query Parameters:
        - source: 'ecowitt' (default) or 'wunderground'
    
    Returns:
        Current weather conditions with prediction
    """
    source = request.args.get('source', 'ecowitt').lower()
    source, error = _validate_source(source)
    if error:
        return error
    
    payload = serializers.get_source_current_payload(source)
    if not payload.get('ok'):
        return jsonify({
            'ok': False,
            'error': {
                'code': 'NO_DATA',
                'message': 'No weather data available'
            }
        }), 404
    
    pl = payload['data']
    wu = pl.get('weather_wunderground')
    eco = pl.get('weather_ecowitt')
    
    # Get latest prediction log
    try:
        pl_db = db.session.query(models.PredictionLog).order_by(
            models.PredictionLog.created_at.desc()
        ).first()
    except Exception:
        pl_db = None
    
    # Build response based on source
    if source == 'ecowitt':
        weather_data = eco or {}
        prediction = pl.get('ecowitt_prediction')
    else:
        weather_data = wu or {}
        prediction = pl.get('wunderground_prediction')
    
    response_data = {
        'id': pl_db.id if pl_db else None,
        'source': source,
        'timestamp': _to_wib_iso(pl_db.created_at if pl_db else None),
        'weather': {
            'temperature': weather_data.get('temperature_main_outdoor') if source == 'ecowitt' else weather_data.get('temperature'),
            'humidity': weather_data.get('humidity_outdoor') if source == 'ecowitt' else weather_data.get('humidity'),
            'pressure': weather_data.get('pressure_relative') if source == 'ecowitt' else weather_data.get('pressure'),
            'wind_speed': weather_data.get('wind_speed'),
            'wind_direction': weather_data.get('wind_direction'),
            'wind_compass': _deg_to_compass(weather_data.get('wind_direction')),
            'rain_rate': weather_data.get('rain_rate') if source == 'ecowitt' else weather_data.get('precipitation_rate'),
            'uvi': weather_data.get('uvi') if source == 'ecowitt' else weather_data.get('ultraviolet_radiation'),
            'dew_point': weather_data.get('dew_point_outdoor') if source == 'ecowitt' else None,
        },
        'prediction': prediction,
    }
    
    return jsonify({
        'ok': True,
        'data': response_data
    }), 200


@bp_v3.route('/weather/hourly', methods=['GET'])
@apply_rate_limit
@require_api_key
def weather_hourly():
    """
    Get hourly weather prediction.
    
    Query Parameters:
        - model: 'lstm' (default) or 'xgboost'
        - source: 'ecowitt' (default) or 'wunderground'
        - limit: 1-24 (optional, default shows all 24 hours)
    
    Returns:
        - For LSTM: 24-hour rainfall intensity predictions
        - For XGBoost: Rain direction classification
    """
    # Validate parameters
    model_param = request.args.get('model', 'lstm').lower()
    model_param, error = _validate_model(model_param)
    if error:
        return error
    
    source = request.args.get('source', 'ecowitt').lower()
    source, error = _validate_source(source)
    if error:
        return error
    
    # Validate limit
    limit_param = request.args.get('limit')
    limit = None
    if limit_param is not None:
        try:
            limit = int(limit_param)
            if limit < 1 or limit > 24:
                return jsonify({
                    'ok': False,
                    'error': {
                        'code': 'INVALID_PARAMETER',
                        'message': 'Limit must be between 1 and 24'
                    }
                }), 400
        except ValueError:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'INVALID_PARAMETER',
                    'message': 'Limit must be a valid integer'
                }
            }), 400
    
    # Get latest prediction
    pl = db.session.query(models.PredictionLog).order_by(
        models.PredictionLog.created_at.desc()
    ).first()
    
    if not pl:
        return jsonify({
            'ok': False,
            'error': {
                'code': 'NO_DATA',
                'message': 'No prediction data available'
            }
        }), 404
    
    # Ensure created_at has timezone
    created_at = pl.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    created_at_wib = created_at.astimezone(WIB)
    
    if model_param == 'lstm':
        from .services.prediction_service import get_model_info
        
        # Get LSTM data
        lstm_data = pl.ecowitt_predict_data if source == 'ecowitt' else pl.wunderground_predict_data
        
        if not lstm_data:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'NO_DATA',
                    'message': f'No LSTM prediction data for {source}'
                }
            }), 404
        
        # Get model info from database
        lstm_model_db = pl.lstm_model
        lstm_model_info = get_model_info('lstm')
        
        # Build predictions array
        predictions = []
        total_available = len(lstm_data)
        
        for i, value in enumerate(lstm_data):
            if limit is not None and len(predictions) >= limit:
                break
            
            pred_time = created_at_wib + timedelta(hours=i+1)
            predictions.append({
                'hour': i + 1,
                'datetime': pred_time.isoformat(),
                'date': pred_time.strftime('%Y-%m-%d'),
                'time': pred_time.strftime('%H:%M'),
                'value': value,
            })
        
        return jsonify({
            'ok': True,
            'data': {
                'model': {
                    'id': lstm_model_db.id if lstm_model_db else lstm_model_info['id'],
                    'name': lstm_model_db.name if lstm_model_db else lstm_model_info['name'],
                    'range_prediction': lstm_model_db.range_prediction if lstm_model_db else lstm_model_info['range_prediction'],
                },
                'prediction': {
                    'id': pl.id,
                    'source': source,
                    'predicted_at': created_at_wib.isoformat(),
                    'total_hours': total_available,
                    'showing': len(predictions),
                    'limit_applied': limit,
                },
                'hourly': predictions,
            }
        }), 200
    
    else:  # xgboost
        from .services.prediction_service import get_label_from_db, get_model_info
        
        # Get XGBoost result
        xgboost_result = pl.ecowitt_predict_result if source == 'ecowitt' else pl.wunderground_predict_result
        
        # Get label and model info from database
        label_info = get_label_from_db(xgboost_result) if xgboost_result is not None else None
        xgboost_model_info = get_model_info('xgboost')
        model_db = pl.xgboost_model
        
        return jsonify({
            'ok': True,
            'data': {
                'model': {
                    'id': model_db.id if model_db else xgboost_model_info['id'],
                    'name': model_db.name if model_db else xgboost_model_info['name'],
                    'range_prediction': model_db.range_prediction if model_db else xgboost_model_info['range_prediction'],
                },
                'prediction': {
                    'id': pl.id,
                    'source': source,
                    'predicted_at': created_at_wib.isoformat(),
                },
                'classification': label_info,
            }
        }), 200


@bp_v3.route('/weather/details', methods=['GET'])
@apply_rate_limit
@require_api_key
def weather_details():
    """
    Get detailed weather prediction data.
    
    Query Parameters:
        - id: Prediction ID (optional, defaults to latest)
        - source: 'ecowitt' (default) or 'wunderground'
    
    Returns:
        Detailed weather data with all sensor readings
    """
    source = request.args.get('source', 'ecowitt').lower()
    source, error = _validate_source(source)
    if error:
        return error
    
    pid = request.args.get('id')
    
    base_q = db.session.query(models.PredictionLog)
    
    if source == 'ecowitt':
        base_q = base_q.filter(models.PredictionLog.weather_log_ecowitt_id.isnot(None))
    else:
        base_q = base_q.filter(models.PredictionLog.weather_log_wunderground_id.isnot(None))
    
    if pid:
        try:
            pid_int = int(pid)
        except ValueError:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'INVALID_PARAMETER',
                    'message': 'ID must be a valid integer'
                }
            }), 400
        
        pl = base_q.filter_by(id=pid_int).first()
        if not pl:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'NOT_FOUND',
                    'message': f'Prediction with ID {pid_int} not found'
                }
            }), 404
    else:
        pl = base_q.order_by(models.PredictionLog.created_at.desc()).first()
        if not pl:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'NO_DATA',
                    'message': 'No prediction data found'
                }
            }), 404
    
    # Get weather log
    if source == 'ecowitt':
        wl = pl.weather_log_ecowitt
    else:
        wl = pl.weather_log_wunderground
    
    time_wib = _to_wib_iso(pl.created_at)
    
    # Build detailed response based on source
    if source == 'ecowitt' and wl:
        details = {
            'uvi': wl.uvi,
            'vpd_outdoor': wl.vpd_outdoor,
            'temperature': wl.temperature_main_outdoor,
            'feels_like': wl.temperature_feels_like_outdoor,
            'dew_point': wl.dew_point_outdoor,
            'humidity': wl.humidity_outdoor,
            'pressure_absolute': wl.pressure_absolute,
            'pressure_relative': wl.pressure_relative,
            'wind_speed': wl.wind_speed,
            'wind_gust': wl.wind_gust,
            'wind_direction': wl.wind_direction,
            'wind_compass': _deg_to_compass(wl.wind_direction),
            'rain_rate': wl.rain_rate,
            'rain_daily': wl.rain_daily,
            'rain_hourly': wl.rain_hour,
            'solar_irradiance': wl.solar_irradiance,
        }
    elif source == 'wunderground' and wl:
        details = {
            'uvi': wl.ultraviolet_radiation,
            'temperature': wl.temperature,
            'humidity': wl.humidity,
            'pressure': wl.pressure,
            'wind_speed': wl.wind_speed,
            'wind_gust': wl.wind_gust,
            'wind_direction': wl.wind_direction,
            'wind_compass': _deg_to_compass(wl.wind_direction),
            'rain_rate': wl.precipitation_rate,
            'rain_total': wl.precipitation_total,
            'solar_radiation': wl.solar_radiation,
        }
    else:
        details = None
    
    return jsonify({
        'ok': True,
        'data': {
            'id': pl.id,
            'source': source,
            'timestamp': time_wib,
            'weather': details,
        }
    }), 200


@bp_v3.route('/weather/history', methods=['GET'])
@apply_rate_limit
@require_api_key
def weather_history():
    """
    Get prediction history.
    
    Query Parameters:
        - page: Page number (default: 1)
        - per_page: Items per page (default: 10, max: 50)
        - source: 'ecowitt' (default) or 'wunderground'
        - date: Single date filter (YYYY-MM-DD)
        - time: Single time filter (HH:MM)
        - start_date: Start date range (YYYY-MM-DD)
        - end_date: End date range (YYYY-MM-DD)
        - start_time: Start time range (HH:MM)
        - end_time: End time range (HH:MM)
    
    Returns:
        Paginated prediction history
    """
    source = request.args.get('source', 'ecowitt').lower()
    source, error = _validate_source(source)
    if error:
        return error
    
    # Pagination
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except ValueError:
        return jsonify({
            'ok': False,
            'error': {
                'code': 'INVALID_PARAMETER',
                'message': 'Page must be a valid integer'
            }
        }), 400
    
    try:
        per_page = int(request.args.get('per_page', 10))
        if per_page < 1:
            per_page = 10
        if per_page > 50:
            per_page = 50
    except ValueError:
        per_page = 10
    
    offset = (page - 1) * per_page
    
    # Date/Time parsing helpers
    def parse_date(s):
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None
    
    def parse_time(s):
        try:
            return datetime.strptime(s, '%H:%M').time()
        except (ValueError, TypeError):
            try:
                return datetime.strptime(s, '%H:%M:%S').time()
            except (ValueError, TypeError):
                return None
    
    def wib_time_to_utc_time(t_obj):
        if t_obj is None:
            return None
        wib_seconds = t_obj.hour * 3600 + t_obj.minute * 60 + t_obj.second
        utc_seconds = (wib_seconds - 25200) % 86400
        return (datetime.min + timedelta(seconds=utc_seconds)).time()
    
    # Get filter parameters
    date_str = request.args.get('date')
    time_str = request.args.get('time')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    start_time_str = request.args.get('start_time')
    end_time_str = request.args.get('end_time')
    
    # Validate paired parameters
    if (start_date_str and not end_date_str) or (not start_date_str and end_date_str):
        return jsonify({
            'ok': False,
            'error': {
                'code': 'INVALID_PARAMETER',
                'message': 'Both start_date and end_date are required together'
            }
        }), 400
    
    if (start_time_str and not end_time_str) or (not start_time_str and end_time_str):
        return jsonify({
            'ok': False,
            'error': {
                'code': 'INVALID_PARAMETER',
                'message': 'Both start_time and end_time are required together'
            }
        }), 400
    
    # Build query
    base_q = db.session.query(models.PredictionLog)
    
    if source == 'ecowitt':
        base_q = base_q.filter(models.PredictionLog.weather_log_ecowitt_id.isnot(None))
    else:
        base_q = base_q.filter(models.PredictionLog.weather_log_wunderground_id.isnot(None))
    
    # Date/Time filter variables
    filter_date_start_utc = None
    filter_date_end_utc = None
    filter_time_start_utc = None
    filter_time_end_utc = None
    use_date_range = False
    use_time_filter = False
    
    # Process date filter
    if date_str:
        d = parse_date(date_str)
        if not d:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'INVALID_PARAMETER',
                    'message': 'Invalid date format. Use YYYY-MM-DD'
                }
            }), 400
        
        dt_start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=WIB)
        dt_end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=WIB)
        filter_date_start_utc = dt_start.astimezone(timezone.utc)
        filter_date_end_utc = dt_end.astimezone(timezone.utc)
        use_date_range = True
    
    elif start_date_str and end_date_str:
        sd = parse_date(start_date_str)
        ed = parse_date(end_date_str)
        if not sd or not ed:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'INVALID_PARAMETER',
                    'message': 'Invalid date format. Use YYYY-MM-DD'
                }
            }), 400
        if sd > ed:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'INVALID_PARAMETER',
                    'message': 'start_date must be before or equal to end_date'
                }
            }), 400
        
        dt_start = datetime(sd.year, sd.month, sd.day, 0, 0, 0, tzinfo=WIB)
        dt_end = datetime(ed.year, ed.month, ed.day, 23, 59, 59, tzinfo=WIB)
        filter_date_start_utc = dt_start.astimezone(timezone.utc)
        filter_date_end_utc = dt_end.astimezone(timezone.utc)
        use_date_range = True
    
    # Process time filter
    if time_str:
        t = parse_time(time_str)
        if not t:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'INVALID_PARAMETER',
                    'message': 'Invalid time format. Use HH:MM'
                }
            }), 400
        
        if use_date_range and date_str:
            # Combine date and time for exact match
            d = parse_date(date_str)
            spec_dt = datetime(d.year, d.month, d.day, t.hour, t.minute, t.second, tzinfo=WIB)
            spec_utc = spec_dt.astimezone(timezone.utc)
            filter_date_start_utc = spec_utc
            filter_date_end_utc = spec_utc
            use_time_filter = False
        else:
            # Filter by time only (any date)
            utc_t = wib_time_to_utc_time(t)
            filter_time_start_utc = utc_t
            filter_time_end_utc = utc_t
            use_time_filter = True
    
    elif start_time_str and end_time_str:
        st = parse_time(start_time_str)
        et = parse_time(end_time_str)
        if not st or not et:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'INVALID_PARAMETER',
                    'message': 'Invalid time format. Use HH:MM'
                }
            }), 400
        
        if date_str and st > et:
            return jsonify({
                'ok': False,
                'error': {
                    'code': 'INVALID_PARAMETER',
                    'message': 'start_time must be before or equal to end_time when using single date'
                }
            }), 400
        
        filter_time_start_utc = wib_time_to_utc_time(st)
        filter_time_end_utc = wib_time_to_utc_time(et)
        use_time_filter = True
    
    # Apply date filter
    if use_date_range:
        if filter_date_start_utc == filter_date_end_utc:
            base_q = base_q.filter(models.PredictionLog.created_at == filter_date_start_utc)
        else:
            base_q = base_q.filter(
                models.PredictionLog.created_at >= filter_date_start_utc,
                models.PredictionLog.created_at <= filter_date_end_utc
            )
    
    # Apply time filter
    if use_time_filter:
        db_time = func.time(models.PredictionLog.created_at)
        
        if filter_time_start_utc == filter_time_end_utc:
            base_q = base_q.filter(db_time == filter_time_start_utc)
        else:
            if filter_time_start_utc <= filter_time_end_utc:
                base_q = base_q.filter(db_time.between(filter_time_start_utc, filter_time_end_utc))
            else:
                # Time range crosses midnight (e.g., 22:00 - 06:00)
                base_q = base_q.filter(
                    or_(db_time >= filter_time_start_utc, db_time <= filter_time_end_utc)
                )
    
    # Get total and paginated results
    total = base_q.count()
    
    pls = (
        base_q.order_by(models.PredictionLog.created_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )
    
    # Build response data
    from .services.prediction_service import get_label_from_db
    
    items = []
    for p in pls:
        wl = p.weather_log_ecowitt if source == 'ecowitt' else p.weather_log_wunderground
        xgboost_result = p.ecowitt_predict_result if source == 'ecowitt' else p.wunderground_predict_result
        
        item = {
            'id': p.id,
            'timestamp': _to_wib_iso(p.created_at),
            'classification': get_label_from_db(xgboost_result) if xgboost_result is not None else None,
            'weather_summary': {
                'temperature': getattr(wl, 'temperature_main_outdoor' if source == 'ecowitt' else 'temperature', None) if wl else None,
                'humidity': getattr(wl, 'humidity_outdoor' if source == 'ecowitt' else 'humidity', None) if wl else None,
                'rain_rate': getattr(wl, 'rain_rate' if source == 'ecowitt' else 'precipitation_rate', None) if wl else None,
            }
        }
        items.append(item)
    
    return jsonify({
        'ok': True,
        'data': items,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': (total + per_page - 1) // per_page,
            'has_next': page * per_page < total,
            'has_prev': page > 1,
        }
    }), 200


@bp_v3.route('/weather/graph', methods=['GET'])
@apply_rate_limit
@require_api_key
def weather_graph():
    """
    Get data for weather graphs.
    
    Query Parameters:
        - range: 'weekly' or 'monthly' (required)
        - datatype: Data type to graph (required)
          Options: temperature, humidity, rainfall, wind_speed, uvi, solar_radiation, relative_pressure
        - source: 'ecowitt' (default) or 'wunderground'
        - month: Month number 1-12 (for monthly range)
    
    Returns:
        Time-series data for graphing
    """
    range_param = request.args.get('range')
    if not range_param:
        return jsonify({
            'ok': False,
            'error': {
                'code': 'MISSING_PARAMETER',
                'message': "Parameter 'range' is required (weekly or monthly)"
            }
        }), 400
    
    datatype = request.args.get('datatype')
    if not datatype:
        return jsonify({
            'ok': False,
            'error': {
                'code': 'MISSING_PARAMETER',
                'message': "Parameter 'datatype' is required"
            }
        }), 400
    
    source = request.args.get('source', 'ecowitt').lower()
    month = request.args.get('month')
    
    payload = serializers.get_graph_payload(range_param, month=month, source=source, datatype=datatype)
    
    if not payload.get('ok'):
        return jsonify({
            'ok': False,
            'error': {
                'code': 'INVALID_REQUEST',
                'message': payload.get('message', 'Invalid request')
            }
        }), 400
    
    return jsonify(payload), 200


# =====================================================================
# ERROR HANDLERS
# =====================================================================

@bp_v3.errorhandler(404)
def not_found(error):
    return jsonify({
        'ok': False,
        'error': {
            'code': 'NOT_FOUND',
            'message': 'The requested resource was not found'
        }
    }), 404


@bp_v3.errorhandler(500)
def internal_error(error):
    return jsonify({
        'ok': False,
        'error': {
            'code': 'INTERNAL_ERROR',
            'message': 'An internal server error occurred'
        }
    }), 500
