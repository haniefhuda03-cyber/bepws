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
    # default source
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

        # latest PredictionLog and weather object for metadata & timestamps
        try:
            pl_db = db.session.query(models.PredictionLog).order_by(models.PredictionLog.created_at.desc()).first()
        except Exception:
            pl_db = None

        pred_id = pl_db.id if pl_db else None
        created_at_wib = _to_wib_iso(getattr(pl_db, 'created_at', None)) if pl_db else None
        weather_obj = None
        if pl_db:
            weather_obj = pl_db.weather_log_ecowitt if source == 'ecowitt' else pl_db.weather_log_wunderground

        # build the field values from payload
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
        # --- 1. Logika Waktu & Reset Harian (WIB vs UTC) ---
        # Definisikan Timezone WIB (UTC+7)
        WIB = timezone(timedelta(hours=7))
        
        # Ambil waktu sekarang (UTC) dan konversi ke WIB
        now_utc = datetime.now(timezone.utc)
        now_wib = now_utc.astimezone(WIB)
        
        # Reset jam menjadi 00:00:00 WIB (Start of Day)
        # Ini memastikan jika sekarang jam 00:05 WIB, data kemarin (jam 23:00 WIB) tidak diambil.
        start_of_day_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Konversi balik Start of Day WIB ke UTC untuk query database
        start_of_day_utc = start_of_day_wib.astimezone(timezone.utc)

        # --- 2. Query Database ---
        # Ambil data mulai dari Start of Day UTC sampai sekarang
        q = db.session.query(models.PredictionLog).filter(models.PredictionLog.created_at >= start_of_day_utc)

        # Filter Source (Wunderground vs Ecowitt)
        if source == 'ecowitt':
            q = q.filter(models.PredictionLog.weather_log_ecowitt_id.isnot(None))
        elif source == 'wunderground':
            q = q.filter(models.PredictionLog.weather_log_wunderground_id.isnot(None))
        
        # Order ASCENDING (dari pagi ke malam) penting untuk logika downsampling
        # agar kita mengambil menit pertama/awal di setiap jamnya.
        rows = q.order_by(models.PredictionLog.created_at.asc()).all()

        # --- 3. Downsampling & Formatting (Python Processing) ---
        seen_hours = set()
        hours = []

        for pl in rows:
            if not pl or not pl.created_at:
                continue
            
            # Pastikan datetime aware UTC
            created = pl.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            
            # Konversi ke WIB untuk pengecekan jam
            created_wib = created.astimezone(WIB)
            
            # Ambil jam (0-23)
            hour_key = created_wib.hour

            # LOGIKA UTAMA: Skip jika jam ini sudah ada datanya
            if hour_key in seen_hours:
                continue
            
            # Tandai jam ini sudah diambil
            seen_hours.add(hour_key)

            # Format Data Output
            date_str = created_wib.strftime('%Y-%m-%d') # YYYY-MM-DD (WIB)
            time_str = created_wib.strftime('%H:%M')    # HH:MM (WIB)

            # Ekstraksi Data Berdasarkan Source
            temp = None
            weather_predict = None

            if source == 'ecowitt':
                wl = pl.weather_log_ecowitt
                label = pl.ecowitt_label
                if wl:
                    temp = wl.temperature_main_outdoor
                if label:
                    weather_predict = label.name
            else: # wunderground
                wl = pl.weather_log_wunderground
                label = pl.wunderground_label
                if wl:
                    temp = wl.temperature
                if label:
                    weather_predict = label.name

            hours.append({
                'id': pl.id,
                'date': date_str,
                'time': time_str,
                'temp': temp,
                'weather_predict': weather_predict,
            })

        # --- 4. Output JSON ---
        return jsonify({'ok': True, 'hours': hours}), 200

    if t == 'details':
        # Validate allowed query params for details endpoint
        allowed = {'type', 'id', 'source', 'api_key'}
        unknown = set(request.args.keys()) - allowed
        if unknown:
            return jsonify({'ok': False, 'message': f"Unknown parameter(s) for details: {', '.join(sorted(unknown))}"}), 400

        pid = request.args.get('id')

        # Build base query. If client explicitly provided source, require matching weather log.
        base_q = db.session.query(models.PredictionLog)
        if 'source' in request.args:
            if source == 'ecowitt':
                base_q = base_q.filter(models.PredictionLog.weather_log_ecowitt_id.isnot(None))
            else:
                base_q = base_q.filter(models.PredictionLog.weather_log_wunderground_id.isnot(None))
        else:
            # prefer any prediction that has at least one weather log
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
            # pick latest matching prediction
            pl = base_q.order_by(models.PredictionLog.created_at.desc()).first()
            if not pl:
                return jsonify({'ok': False, 'message': 'No data found'}), 404

        # Choose the weather log object to extract fields from
        if 'source' in request.args:
            if source == 'ecowitt':
                wl = pl.weather_log_ecowitt
                key = 'weather_ecowitt'
            else:
                wl = pl.weather_log_wunderground
                key = 'weather_wunderground'
        else:
            # if client didn't state source, prefer ecowitt, otherwise wunderground
            if getattr(pl, 'weather_log_ecowitt', None):
                wl = pl.weather_log_ecowitt
                key = 'weather_ecowitt'
            else:
                wl = pl.weather_log_wunderground
                key = 'weather_wunderground'

        # Build response payload fields (always include id and translated time)
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

        # Wrap when source was explicitly provided; otherwise return flat data object
        if 'source' in request.args:
            resp = {'ok': True, 'data': {key: data_obj}}
        else:
            resp = {'ok': True, 'data': data_obj}

        return jsonify(resp), 200

    return jsonify({'ok': False, 'message': 'unknown type'}), 400


@bp.route('/history', methods=['GET'])
def get_history():
    """History endpoint with flexible WIB-based date/time filtering."""
    
    ok, rest = _require_api_key()
    if not ok: return rest[0]
    try:
        page = int(request.args.get('page', '1'))
    except: return jsonify({'ok': False, 'message': 'invalid page'}), 400
    if page < 1: page = 1

    # If client provided source, validate it. If not provided, we'll prefer ecowitt when present.
    source_arg = request.args.get('source')
    if source_arg:
        source = source_arg.lower()
        if source not in ('ecowitt', 'wunderground'):
            return jsonify({'ok': False, 'message': "invalid source"}), 400
    else:
        source = None

    per_page = 5
    offset = (page - 1) * per_page

    # Constant untuk WIB (UTC+7)
    WIB_TZ = timezone(timedelta(hours=7))

    # Helper parsing
    def _parse_date(s):
        try: return datetime.strptime(s, '%Y-%m-%d').date()
        except: return None

    def _parse_time(s):
        try: return datetime.strptime(s, '%H:%M').time()
        except:
            try: return datetime.strptime(s, '%H:%M:%S').time()
            except: return None

    # Konversi Time WIB -> UTC (Aritmatika)
    def _wib_time_to_utc_time(t_obj):
        if t_obj is None: return None
        wib_seconds = t_obj.hour * 3600 + t_obj.minute * 60 + t_obj.second
        utc_seconds = (wib_seconds - 25200) % 86400
        return (datetime.min + timedelta(seconds=utc_seconds)).time()

    # Ambil parameter
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

    # --- VALIDASI KELENGKAPAN PASANGAN ---
    if (start_date_str and not end_date_str) or (not start_date_str and end_date_str):
        return jsonify({'ok': False, 'message': 'Harap sertakan start_date DAN end_date.'}), 400
    if (start_time_str and not end_time_str) or (not start_time_str and end_time_str):
        return jsonify({'ok': False, 'message': 'Harap sertakan start_time DAN end_time.'}), 400

    # ==================================================
    # TAHAP 1: SET FILTER TANGGAL (KALENDER)
    # ==================================================
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

    # ==================================================
    # TAHAP 2: SET FILTER JAM (CLOCK)
    # ==================================================
    if time_str:
        t = _parse_time(time_str)
        if not t: return jsonify({'ok': False, 'message': 'Format time salah'}), 400
        
        if use_date_range and date_str:
             # Case Khusus: Date + Time = Point Spesifik
             d = _parse_date(date_str)
             spec_dt = datetime(d.year, d.month, d.day, t.hour, t.minute, t.second, tzinfo=WIB_TZ)
             spec_utc = spec_dt.astimezone(timezone.utc)
             
             filter_date_start_utc = spec_utc
             filter_date_end_utc = spec_utc 
             use_time_filter = False 
        else:
             # Time Only (Recurring)
             utc_t = _wib_time_to_utc_time(t)
             filter_time_start_utc = utc_t
             filter_time_end_utc = utc_t 
             use_time_filter = True

    elif start_time_str and end_time_str:
        st = _parse_time(start_time_str)
        et = _parse_time(end_time_str)
        if not st or not et: return jsonify({'ok': False, 'message': 'Format start/end_time salah'}), 400
        
        # [MODIFIKASI KHUSUS]
        # Jika 'date' (Single Day) diset, MAKA start_time TIDAK BOLEH > end_time
        # (Tidak bisa nyebrang hari dalam satu tanggal kalender yang sama)
        if date_str and st > et:
            return jsonify({'ok': False, 'message': 'start_time harus <= end_time jika menggunakan parameter date (satu hari)'}), 400

        # Jika date_str kosong (Recurring) atau Range Date, maka Cross Midnight (st > et) DIIZINKAN.

        filter_time_start_utc = _wib_time_to_utc_time(st)
        filter_time_end_utc = _wib_time_to_utc_time(et)
        use_time_filter = True

    # --- EKSEKUSI QUERY ---
    base_q = db.session.query(models.PredictionLog)

    # If client explicitly asked a source, restrict to that source. Otherwise include both
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

    # 1. Terapkan Filter Tanggal
    if use_date_range:
        if filter_date_start_utc == filter_date_end_utc:
             base_q = base_q.filter(models.PredictionLog.created_at == filter_date_start_utc)
        else:
             base_q = base_q.filter(
                 models.PredictionLog.created_at >= filter_date_start_utc,
                 models.PredictionLog.created_at <= filter_date_end_utc
             )

    # 2. Terapkan Filter Jam
    if use_time_filter:
        db_time = func.time(models.PredictionLog.created_at)
        
        if filter_time_start_utc == filter_time_end_utc:
            base_q = base_q.filter(db_time == filter_time_start_utc)
        else:
            # Cek Logic UTC: Normal vs Nyebrang
            if filter_time_start_utc <= filter_time_end_utc:
                # Range Normal
                base_q = base_q.filter(db_time.between(filter_time_start_utc, filter_time_end_utc))
            else:
                # Range Cross Midnight (UTC)
                # Logic ini berjalan jika input 'start_time > end_time' diizinkan (no single date)
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

    # Build response
    data_list = []
    source_param_provided = 'source' in request.args

    for p in pls:
        # Choose weather log per-record. If client specified source, honor it.
        if source == 'ecowitt':
            wl = p.weather_log_ecowitt
        elif source == 'wunderground':
            wl = p.weather_log_wunderground
        else:
            # prefer ecowitt when present, otherwise use wunderground
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


@bp.route('/graph', methods=['GET'])
def graph():
    ok, rest = _require_api_key()
    if not ok:
        return rest[0]
    # Aturan utama: default = ecowitt
    source = request.args.get('source') or 'ecowitt'
    source = source.lower()
    if source not in ('ecowitt', 'wunderground'):
        return jsonify({'ok': False, 'message': "invalid source; gunakan 'ecowitt' atau 'wunderground'"}), 400

    metric = request.args.get('metric')
    if not metric:
        return jsonify({'ok': False, 'message': 'metric param required'}), 400

    range_param = request.args.get('range')
    if not range_param:
        return jsonify({'ok': False, 'message': 'range param required (harian|pekanan)'}), 400
    rp = range_param.lower()
    if rp in ('harian', 'daily'):
        days = 1
    elif rp in ('pekanan', 'mingguan', 'weekly'):
        days = 7
    else:
        return jsonify({'ok': False, 'message': "range harus 'harian' atau 'pekanan'"}), 400

    # map metric strings to columns per source
    metric_key = metric.lower()
    if source == 'ecowitt':
        mapping = {
            'suhu': 'temperature_main_outdoor',
            'temperature': 'temperature_main_outdoor',
            'tekanan_udara_relatif': 'pressure_relative',
            'kelembapan': 'humidity_outdoor',
            'kecepatan_angin': 'wind_speed',
            'uvi': 'uvi',
            'curah_hujan': 'rain_rate',
            'radiasi_matahari': 'solar_irradiance',
        }
        table = models.WeatherLogEcowitt
    else:
        mapping = {
            'suhu': 'temperature',
            'temperature': 'temperature',
            'tekanan_udara_relatif': 'pressure',
            'kelembapan': 'humidity',
            'kecepatan_angin': 'wind_speed',
            'uvi': 'ultraviolet_radiation',
            'curah_hujan': 'precipitation_rate',
            'radiasi_matahari': 'solar_radiation',
        }
        table = models.WeatherLogWunderground

    col_name = mapping.get(metric_key)
    if not col_name:
        return jsonify({'ok': False, 'message': f"unknown metric '{metric}' for source {source}"}), 400

    col = getattr(table, col_name)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    q = db.session.query(func.max(col), func.min(col), func.avg(col)).filter(table.created_at >= start, table.created_at <= now)
    max_v, min_v, avg_v = q.first() or (None, None, None)

    # nilai asli: average of the previous period (day/week before)
    prev_start = start - timedelta(days=days)
    prev_end = start
    prev_avg = db.session.query(func.avg(col)).filter(table.created_at >= prev_start, table.created_at < prev_end).scalar()

    def _maybe_float(x):
        try:
            return float(x) if x is not None else None
        except Exception:
            return None

    # attach metric and latest times (from DB) for context
    latest_pl = (
        db.session.query(models.PredictionLog)
        .order_by(models.PredictionLog.created_at.desc())
        .first()
    )
    latest_weather = None
    if latest_pl:
        latest_weather = latest_pl.weather_log_ecowitt if source == 'ecowitt' else latest_pl.weather_log_wunderground

    resp = {
        'metric': metric,
        'tertinggi': _maybe_float(max_v),
        'terendah': _maybe_float(min_v),
        'rata_rata': _maybe_float(avg_v),
        'nilaiasli': _maybe_float(prev_avg),
        'meta': {
            'latest_prediction_id': latest_pl.id if latest_pl else None,
            'created_at': _to_wib_iso(getattr(latest_pl, 'created_at', None)) if latest_pl else None,
            'request_time': _to_wib_iso(getattr(latest_weather, 'request_time', None)) if latest_weather else None,
        }
    }
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