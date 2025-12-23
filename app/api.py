from flask import Blueprint, jsonify, request, current_app
from typing import Optional
import os
from datetime import datetime, timedelta, timezone

from . import db
from sqlalchemy import text, func, or_, and_
from . import models
from . import serializers
from . import cache

bp = Blueprint('api', __name__)

def _to_wib_iso(dt):
    if not dt:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        wib = dt.astimezone(timezone(timedelta(hours=7)))
        return wib.isoformat()
    except Exception:
        try:
            return dt.isoformat()
        except Exception:
            return None


def _require_api_key():
    api_key = os.environ.get('API_READ_KEY')
    if not api_key:
        return True, None
    provided = request.headers.get('X-API-KEY')
    if provided and provided == api_key:
        return True, None
    return False, (jsonify({'ok': False, 'message': 'Unauthorized'}), 401)


def _choose_temp(wu: Optional[dict], eco: Optional[dict]):
    if eco and eco.get('temperature_main_outdoor') is not None:
        return eco.get('temperature_main_outdoor')
    if wu and wu.get('temperature') is not None:
        return wu.get('temperature')
    return None


def _deg_to_compass(deg: Optional[float]) -> Optional[str]:
    if deg is None:
        return None
    try:
        d = float(deg) % 360
    except Exception:
        return None
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    ix = int((d / 22.5) + 0.5) % 16
    return dirs[ix]


@bp.route('/data', methods=['GET'])
def data():
    ok, rest = _require_api_key()
    if not ok:
        return rest[0]

    t = request.args.get('type', 'general')
    source = request.args.get('source')
    if not source:
        source = 'ecowitt'
    source = source.lower()
    if source not in ('ecowitt', 'wunderground'):
        return jsonify({'ok': False, 'message': "invalid source; gunakan 'ecowitt' atau 'wunderground'"}), 400

    if t == 'general':
        payload = serializers.get_source_current_payload(source)
        if not payload.get('ok'):
            return jsonify({'ok': False, 'message': 'No data available'}), 404
        pl = payload['data']
        wu = pl.get('weather_wunderground')
        eco = pl.get('weather_ecowitt')

        try:
            pl_db = db.session.query(models.PredictionLog).order_by(models.PredictionLog.created_at.desc()).first()
        except Exception:
            pl_db = None

        pred_id = pl_db.id if pl_db else None
        created_at_wib = _to_wib_iso(getattr(pl_db, 'created_at', None)) if pl_db else None
        weather_obj = None
        if pl_db:
            weather_obj = pl_db.weather_log_ecowitt if source == 'ecowitt' else pl_db.weather_log_wunderground

        if source == 'ecowitt':
            temp = eco.get('temperature_main_outdoor') if eco else None
            humidity = eco.get('humidity_outdoor') if eco else None
            dew_point = eco.get('dew_point_outdoor') if eco else None
            pressure = eco.get('pressure_relative') if eco else None
            uvi = eco.get('uvi') if eco else None
            wind_speed = eco.get('wind_speed') if eco else None
            rain_rate = eco.get('rain_rate') if eco else None
            weather = pl.get('ecowitt_prediction').get('name') if pl.get('ecowitt_prediction') else None
            deg = eco.get('wind_direction') if eco else None
        else:
            temp = wu.get('temperature') if wu else None
            humidity = wu.get('humidity') if wu else None
            dew_point = None
            pressure = wu.get('pressure') if wu else None
            uvi = wu.get('ultraviolet_radiation') if wu else None
            rain_rate = wu.get('precipitation_rate') if wu else None
            wind_speed = wu.get('wind_speed') if wu else None
            weather = pl.get('wunderground_prediction').get('name') if pl.get('wunderground_prediction') else None
            deg = wu.get('wind_direction') if wu else None

        general = {
            'id': pred_id,
            'time': created_at_wib,
            'location': None,
            'pressure': pressure,
            'uvi': uvi,
            'compass': _deg_to_compass(deg),
            'deg': deg,
            'dew_point': dew_point,
            'humidity': humidity,
            'temp': temp,
            'rain_rate': rain_rate,
            'weather': weather,
            'wind_speed': wind_speed,
        }

        if 'source' in request.args:
            key = 'weather_ecowitt' if source == 'ecowitt' else 'weather_wunderground'
            resp_data = {key: general}
        else:
            resp_data = general

        return jsonify({'ok': True, 'data': resp_data}), 200

    if t == 'hourly':
        # =====================================================
        # UPDATED: Hourly endpoint dengan dukungan query param &model=
        # - model=lstm (default): Return prediksi intensitas hujan 24 jam
        # - model=xgboost: Return hasil klasifikasi arah hujan
        # =====================================================
        WIB = timezone(timedelta(hours=7))
        
        # Parse `model` param (default: lstm)
        model_param = request.args.get('model', 'lstm').lower()
        if model_param not in ('lstm', 'xgboost'):
            return jsonify({'ok': False, 'message': "invalid model; gunakan 'lstm' atau 'xgboost'"}), 400
        
        # Parse `limit` param
        limit_param = request.args.get('limit')
        limit = None
        if limit_param is not None:
            try:
                limit = int(limit_param)
            except Exception:
                return jsonify({'ok': False, 'message': 'invalid limit'}), 400
            if limit < 1 or limit > 24:
                return jsonify({'ok': False, 'message': 'limit harus antara 1 dan 24'}), 400
        
        # Ambil prediksi terbaru
        pl = db.session.query(models.PredictionLog).order_by(
            models.PredictionLog.created_at.desc()
        ).first()
        
        if not pl:
            return jsonify({'ok': False, 'message': 'No prediction data available'}), 404
        
        source_param_provided = 'source' in request.args
        
        # =====================================================
        # MODEL = LSTM: Return array 24 jam prediksi intensitas hujan
        # =====================================================
        if model_param == 'lstm':
            from .services.prediction_service import get_model_info
            
            # Ambil data LSTM dari prediction_log
            if source == 'ecowitt':
                lstm_data = pl.ecowitt_predict_data
            else:
                lstm_data = pl.wunderground_predict_data
            
            if not lstm_data:
                return jsonify({'ok': False, 'message': f'No LSTM prediction data for {source}'}), 404
            
            # Pastikan created_at ada timezone
            created_at = pl.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            created_at_wib = created_at.astimezone(WIB)
            
            # Ambil model info dari database via relasi
            lstm_model_db = pl.lstm_model
            lstm_model_info = get_model_info('lstm')
            
            # Buat array predictions dengan waktu dikalkulasi dinamis
            # Mulai dari created_at + 1 jam, dst
            predictions = []
            total_available = len(lstm_data)
            
            for i, value in enumerate(lstm_data):
                # Jika limit diberikan, batasi jumlah data
                if limit is not None and len(predictions) >= limit:
                    break
                
                # Waktu prediksi = created_at + (i+1) jam
                pred_time = created_at_wib + timedelta(hours=i+1)
                
                predictions.append({
                    'hour': i + 1,  # Jam ke-1, ke-2, dst dari waktu prediksi
                    'datetime': pred_time.isoformat(),
                    'date': pred_time.strftime('%Y-%m-%d'),
                    'time': pred_time.strftime('%H:%M'),
                    'value': value,  # Intensitas hujan (mm/jam)
                })
            
            response_data = {
                'ok': True,
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
                'data': predictions,
            }
            
            if source_param_provided:
                key = 'weather_ecowitt' if source == 'ecowitt' else 'weather_wunderground'
                return jsonify({'ok': True, 'model': 'lstm', 'data': {key: predictions}}), 200
            return jsonify(response_data), 200
        
        # =====================================================
        # MODEL = XGBOOST: Return hasil klasifikasi
        # =====================================================
        else:  # xgboost
            from .services.prediction_service import get_label_from_db, get_model_info
            
            if source == 'ecowitt':
                xgboost_result = pl.ecowitt_predict_result
            else:
                xgboost_result = pl.wunderground_predict_result
            
            # Pastikan created_at ada timezone
            created_at = pl.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            created_at_wib = created_at.astimezone(WIB)
            
            # Ambil label dari database
            label_info = get_label_from_db(xgboost_result) if xgboost_result is not None else None
            
            # Ambil model info dari database
            xgboost_model_info = get_model_info('xgboost')
            
            # Ambil info model dari relasi jika tersedia
            model_db = pl.xgboost_model
            
            result = {
                'id': pl.id,
                'model': {
                    'type': 'xgboost',
                    'id': model_db.id if model_db else xgboost_model_info['id'],
                    'name': model_db.name if model_db else xgboost_model_info['name'],
                    'range_prediction': model_db.range_prediction if model_db else xgboost_model_info['range_prediction'],
                },
                'source': source,
                'created_at': created_at_wib.isoformat(),
                'label': label_info,
            }
            
            if source_param_provided:
                key = 'weather_ecowitt' if source == 'ecowitt' else 'weather_wunderground'
                return jsonify({'ok': True, 'model': 'xgboost', 'data': {key: result}}), 200
            return jsonify({'ok': True, 'model': 'xgboost', 'data': result}), 200

    if t == 'details':
        allowed = {'type', 'id', 'source', 'api_key'}
        unknown = set(request.args.keys()) - allowed
        if unknown:
            return jsonify({'ok': False, 'message': f"Unknown parameter(s) for details: {', '.join(sorted(unknown))}"}), 400

        pid = request.args.get('id')

        base_q = db.session.query(models.PredictionLog)
        if 'source' in request.args:
            if source == 'ecowitt':
                base_q = base_q.filter(models.PredictionLog.weather_log_ecowitt_id.isnot(None))
            else:
                base_q = base_q.filter(models.PredictionLog.weather_log_wunderground_id.isnot(None))
        else:
            base_q = base_q.filter(
                or_(
                    models.PredictionLog.weather_log_ecowitt_id.isnot(None),
                    models.PredictionLog.weather_log_wunderground_id.isnot(None),
                )
            )

        if pid:
            try:
                pid_int = int(pid)
            except ValueError:
                return jsonify({'ok': False, 'message': 'invalid id'}), 400
            pl = base_q.filter_by(id=pid_int).first()
            if not pl:
                return jsonify({'ok': False, 'message': 'Not found'}), 404
        else:
            pl = base_q.order_by(models.PredictionLog.created_at.desc()).first()
            if not pl:
                return jsonify({'ok': False, 'message': 'No data found'}), 404

        if 'source' in request.args:
            if source == 'ecowitt':
                wl = pl.weather_log_ecowitt
                key = 'weather_ecowitt'
            else:
                wl = pl.weather_log_wunderground
                key = 'weather_wunderground'
        else:
            if getattr(pl, 'weather_log_ecowitt', None):
                wl = pl.weather_log_ecowitt
                key = 'weather_ecowitt'
            else:
                wl = pl.weather_log_wunderground
                key = 'weather_wunderground'

        time_wib = _to_wib_iso(getattr(pl, 'created_at', None))
        if key == 'weather_ecowitt':
            data_obj = {
                'id': pl.id,
                'time': time_wib,
                'uvi': getattr(wl, 'uvi', None) if wl else None,
                'vpd_outdoor': getattr(wl, 'vpd_outdoor', None) if wl else None,
                'feels_like': getattr(wl, 'temperature_feels_like_outdoor', None) if wl else None,
                'rain_rate': getattr(wl, 'rain_rate', None) if wl else None,
                'solar_irradiance': getattr(wl, 'solar_irradiance', None) if wl else None,
                'wind_gust': getattr(wl, 'wind_gust', None) if wl else None,
                'pressure_relative': getattr(wl, 'pressure_relative', None) if wl else None,
            }
        else:
            data_obj = {
                'id': pl.id,
                'time': time_wib,
                'uvi': getattr(wl, 'ultraviolet_radiation', None) if wl else None,
                'vpd_outdoor': None,
                'feels_like': getattr(wl, 'temperature', None) if wl else None,
                'rain_rate': getattr(wl, 'precipitation_rate', None) if wl else None,
                'solar_irradiance': getattr(wl, 'solar_radiation', None) if wl else None,
                'wind_gust': getattr(wl, 'wind_gust', None) if wl else None,
                'pressure_relative': getattr(wl, 'pressure', None) if wl else None,
            }

        if 'source' in request.args:
            resp = {'ok': True, 'data': {key: data_obj}}
        else:
            resp = {'ok': True, 'data': data_obj}

        return jsonify(resp), 200

    return jsonify({'ok': False, 'message': 'unknown type'}), 400


@bp.route('/history', methods=['GET'])
def get_history():
    
    ok, rest = _require_api_key()
    if not ok: return rest[0]
    try:
        page = int(request.args.get('page', '1'))
    except: return jsonify({'ok': False, 'message': 'invalid page'}), 400
    if page < 1: page = 1

    source_arg = request.args.get('source')
    if source_arg:
        source = source_arg.lower()
        if source not in ('ecowitt', 'wunderground'):
            return jsonify({'ok': False, 'message': "invalid source"}), 400
    else:
        source = 'ecowitt'

    # Parse per_page (default: 10, max: 50)
    try:
        per_page = int(request.args.get('per_page', '10'))
    except:
        per_page = 10
    if per_page < 1:
        per_page = 10
    if per_page > 50:
        per_page = 50
    
    offset = (page - 1) * per_page

    WIB_TZ = timezone(timedelta(hours=7))

    def _parse_date(s):
        try: return datetime.strptime(s, '%Y-%m-%d').date()
        except: return None

    def _parse_time(s):
        try: return datetime.strptime(s, '%H:%M').time()
        except:
            try: return datetime.strptime(s, '%H:%M:%S').time()
            except: return None

    def _wib_time_to_utc_time(t_obj):
        if t_obj is None: return None
        wib_seconds = t_obj.hour * 3600 + t_obj.minute * 60 + t_obj.second
        utc_seconds = (wib_seconds - 25200) % 86400
        return (datetime.min + timedelta(seconds=utc_seconds)).time()

    date_str = request.args.get('date')
    time_str = request.args.get('time')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    start_time_str = request.args.get('start_time')
    end_time_str = request.args.get('end_time')

    if 'start' in request.args or 'end' in request.args:
        return jsonify({'ok': False, 'message': "Parameter 'start'/'end' tidak didukung."}), 400

    filter_date_start_utc = None
    filter_date_end_utc = None
    filter_time_start_utc = None
    filter_time_end_utc = None
    
    use_date_range = False
    use_time_filter = False

    if (start_date_str and not end_date_str) or (not start_date_str and end_date_str):
        return jsonify({'ok': False, 'message': 'Harap sertakan start_date DAN end_date.'}), 400
    if (start_time_str and not end_time_str) or (not start_time_str and end_time_str):
        return jsonify({'ok': False, 'message': 'Harap sertakan start_time DAN end_time.'}), 400

    if date_str:
        d = _parse_date(date_str)
        if not d: return jsonify({'ok': False, 'message': 'Format date salah'}), 400
        
        dt_start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=WIB_TZ)
        dt_end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=WIB_TZ)
        
        filter_date_start_utc = dt_start.astimezone(timezone.utc)
        filter_date_end_utc = dt_end.astimezone(timezone.utc)
        use_date_range = True

    elif start_date_str and end_date_str:
        sd = _parse_date(start_date_str)
        ed = _parse_date(end_date_str)
        if not sd or not ed: return jsonify({'ok': False, 'message': 'Format start/end_date salah'}), 400
        if sd > ed: return jsonify({'ok': False, 'message': 'start_date harus <= end_date'}), 400

        dt_start = datetime(sd.year, sd.month, sd.day, 0, 0, 0, tzinfo=WIB_TZ)
        dt_end = datetime(ed.year, ed.month, ed.day, 23, 59, 59, tzinfo=WIB_TZ)
        
        filter_date_start_utc = dt_start.astimezone(timezone.utc)
        filter_date_end_utc = dt_end.astimezone(timezone.utc)
        use_date_range = True

    if time_str:
        t = _parse_time(time_str)
        if not t: return jsonify({'ok': False, 'message': 'Format time salah'}), 400
        
        if use_date_range and date_str:
            d = _parse_date(date_str)
            spec_dt = datetime(d.year, d.month, d.day, t.hour, t.minute, t.second, tzinfo=WIB_TZ)
            spec_utc = spec_dt.astimezone(timezone.utc)
             
            filter_date_start_utc = spec_utc
            filter_date_end_utc = spec_utc 
            use_time_filter = False 
        else:
            utc_t = _wib_time_to_utc_time(t)
            filter_time_start_utc = utc_t
            filter_time_end_utc = utc_t 
            use_time_filter = True

    elif start_time_str and end_time_str:
        st = _parse_time(start_time_str)
        et = _parse_time(end_time_str)
        if not st or not et: return jsonify({'ok': False, 'message': 'Format start/end_time salah'}), 400
        
        if date_str and st > et:
            return jsonify({'ok': False, 'message': 'start_time harus <= end_time jika menggunakan parameter date (satu hari)'}), 400

        filter_time_start_utc = _wib_time_to_utc_time(st)
        filter_time_end_utc = _wib_time_to_utc_time(et)
        use_time_filter = True

    base_q = db.session.query(models.PredictionLog)

    if source == 'ecowitt':
        base_q = base_q.filter(models.PredictionLog.weather_log_ecowitt_id.isnot(None))
    elif source == 'wunderground':
        base_q = base_q.filter(models.PredictionLog.weather_log_wunderground_id.isnot(None))
    else:
        base_q = base_q.filter(
            or_(
                models.PredictionLog.weather_log_ecowitt_id.isnot(None),
                models.PredictionLog.weather_log_wunderground_id.isnot(None),
            )
        )

    if use_date_range:
        if filter_date_start_utc == filter_date_end_utc:
             base_q = base_q.filter(models.PredictionLog.created_at == filter_date_start_utc)
        else:
             base_q = base_q.filter(
                 models.PredictionLog.created_at >= filter_date_start_utc,
                 models.PredictionLog.created_at <= filter_date_end_utc
             )

    if use_time_filter:
        db_time = func.time(models.PredictionLog.created_at)
        
        if filter_time_start_utc == filter_time_end_utc:
            base_q = base_q.filter(db_time == filter_time_start_utc)
        else:
            if filter_time_start_utc <= filter_time_end_utc:
                base_q = base_q.filter(db_time.between(filter_time_start_utc, filter_time_end_utc))
            else:
                base_q = base_q.filter(
                    or_(db_time >= filter_time_start_utc, db_time <= filter_time_end_utc)
                )

    total = base_q.count()

    pls = (
        base_q.order_by(models.PredictionLog.created_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    data_list = []
    source_param_provided = 'source' in request.args

    for p in pls:
        if source == 'ecowitt':
            wl = p.weather_log_ecowitt
        elif source == 'wunderground':
            wl = p.weather_log_wunderground
        else:
            wl = p.weather_log_ecowitt if getattr(p, 'weather_log_ecowitt', None) else p.weather_log_wunderground
        time_wib = _to_wib_iso(getattr(p, 'created_at', None))

        if source == 'ecowitt':
            temp = getattr(wl, 'temperature_main_outdoor', None) if wl else None
            feels_like = getattr(wl, 'temperature_feels_like_outdoor', None) if wl else None
            UVI = getattr(wl, 'uvi', None) if wl else None
            humidity = getattr(wl, 'humidity_outdoor', None) if wl else None
            pressure = getattr(wl, 'pressure_absolute', None) if wl else None
            pressure_relative = getattr(wl, 'pressure_relative', None) if wl else None
            vpd = getattr(wl, 'vpd_outdoor', None) if wl else None
            wind_speed = getattr(wl, 'wind_speed', None) if wl else None
            wind_gust = getattr(wl, 'wind_gust', None) if wl else None
            rain_rate = getattr(wl, 'rain_rate', None) if wl else None
            solar_irradiance = getattr(wl, 'solar_irradiance', None) if wl else None
            deg = getattr(wl, 'wind_direction', None) if wl else None
            compass = _deg_to_compass(deg)
            dew_point = getattr(wl, 'dew_point_outdoor', None) if wl else None
        else:
            temp = getattr(wl, 'temperature', None) if wl else None
            feels_like = None
            UVI = getattr(wl, 'ultraviolet_radiation', None) if wl else None
            humidity = getattr(wl, 'humidity', None) if wl else None
            pressure = getattr(wl, 'pressure', None) if wl else None
            pressure_relative = None
            vpd = None
            wind_speed = getattr(wl, 'wind_speed', None) if wl else None
            wind_gust = getattr(wl, 'wind_gust', None) if wl else None
            rain_rate = getattr(wl, 'precipitation_rate', None) if wl else None
            solar_irradiance = getattr(wl, 'solar_radiation', None) if wl else None
            deg = getattr(wl, 'wind_direction', None) if wl else None
            compass = _deg_to_compass(deg)
            dew_point = None

        item = {
            'UVI': UVI, 'compass': compass, 'degree': deg, 'dew_point': dew_point,
            'feels_like': feels_like, 'humidity': humidity, 'id': p.id,
            'pressure': pressure, 'pressure_relative': pressure_relative,
            'rain_rate': rain_rate, 'solar_irradiance': solar_irradiance,
            'temp': temp, 'time': time_wib, 'vpd': vpd,
            'wind_gust': wind_gust, 'wind_speed': wind_speed,
        }

        if wl and source_param_provided:
            key = 'weather_ecowitt' if source == 'ecowitt' else 'weather_wunderground'
            data_list.append({key: item})
        else:
            data_list.append(item)

    resp = {'ok': True, 'page': page, 'per_page': per_page, 'total': total, 'data': data_list}
    return jsonify(resp), 200

@bp.route('/health', methods=['GET'])
def health():
    ok = True
    details = {}
    try:
        db.session.execute(text('SELECT 1'))
        details['db'] = 'ok'
    except Exception as e:
        ok = False
        details['db'] = f'error: {e}'

    try:
        sched = current_app.extensions.get('apscheduler')
        if sched is None:
            details['scheduler'] = 'absent'
        else:
            state = getattr(sched, 'state', None)
            jobs = getattr(sched, 'get_jobs', lambda: [])()
            job_ids = [j.id for j in jobs] if jobs else []
            fetch_job = next((j for j in jobs if j.id == 'fetch-weather'), None)
            if state == 1:
                if fetch_job:
                    details['scheduler'] = 'running'
                else:
                    details['scheduler'] = 'running_no_job'
            elif state == 0:
                details['scheduler'] = 'stopped'
            else:
                details['scheduler'] = f'unknown_state_{state}'
            details['scheduler_jobs'] = job_ids
            if fetch_job:
                details['fetch_weather_next_run'] = str(fetch_job.next_run_time)
    except Exception as e:
        details['scheduler'] = f'error: {e}'

    status = 200 if ok else 500
    return jsonify({'ok': ok, 'details': details}), status


@bp.route('/graph', methods=['GET'])
def graph():
    ok, rest = _require_api_key()
    if not ok:
        return rest[0]

    # Required parameters
    range_param = request.args.get('range')
    if not range_param:
        return jsonify({'ok': False, 'message': "Parameter 'range' is required (weekly or monthly)"}), 400
    
    datatype = request.args.get('datatype')
    if not datatype:
        return jsonify({'ok': False, 'message': "Parameter 'datatype' is required (temperature, humidity, rainfall, wind_speed, uvi, solar_radiation, relative_pressure)"}), 400
    
    # Optional parameters
    month = request.args.get('month')
    source = request.args.get('source', 'ecowitt')

    payload = serializers.get_graph_payload(range_param, month=month, source=source, datatype=datatype)
    if not payload.get('ok'):
        return jsonify(payload), 400
    return jsonify(payload), 200