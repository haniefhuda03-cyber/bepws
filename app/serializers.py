from datetime import datetime, timezone, timedelta
import calendar
from collections import defaultdict
from typing import Optional, List, Dict, Any

from . import db
from . import models

_CURRENT_CACHE = {}


def _serialize_prediction_log(pl: models.PredictionLog, source: Optional[str] = None) -> Dict[str, Any]:
    base = {
        "id": pl.id,
        "model": pl.model.to_dict() if pl.model else None,
        "created_at": pl.created_at.isoformat() if pl.created_at else None,
    }

    if source == 'wunderground':
        base.update({
            "weather_wunderground": pl.weather_log_wunderground.to_dict() if pl.weather_log_wunderground else None,
            "wunderground_prediction": pl.wunderground_label.to_dict() if pl.wunderground_label else None,
        })
    elif source == 'ecowitt':
        base.update({
            "weather_ecowitt": pl.weather_log_ecowitt.to_dict() if pl.weather_log_ecowitt else None,
            "ecowitt_prediction": pl.ecowitt_label.to_dict() if pl.ecowitt_label else None,
        })
    else:
        base.update({
            "weather_wunderground": pl.weather_log_wunderground.to_dict() if pl.weather_log_wunderground else None,
            "weather_ecowitt": pl.weather_log_ecowitt.to_dict() if pl.weather_log_ecowitt else None,
            "wunderground_prediction": pl.wunderground_label.to_dict() if pl.wunderground_label else None,
            "ecowitt_prediction": pl.ecowitt_label.to_dict() if pl.ecowitt_label else None,
        })

    return base


def get_current_payload(source: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    try:
        from flask import current_app
        app_key = getattr(current_app, 'import_name', None) or id(current_app)
    except Exception:
        app_key = 'global'
    try:
        from flask import current_app
        app_key = getattr(current_app, 'import_name', None) or id(current_app)
    except Exception:
        app_key = 'global'

    try:
        from . import cache as _cache
        cache_key = f"serializers_current_payload:{app_key}"
        try:
            cached = _cache.get(cache_key)
        except Exception:
            cached = None
        if cached is not None:
            return cached
    except Exception:
        cached = None

    entry = _CURRENT_CACHE.get(app_key)
    if entry and entry.get('ts') and (now - entry['ts']).total_seconds() < entry.get('ttl', 30) and entry.get('data') is not None:
        return entry['data']

    pl = db.session.query(models.PredictionLog).order_by(models.PredictionLog.created_at.desc()).first()
    if not pl:
        payload = {"ok": False, "message": "No prediction logs found"}
        _CURRENT_CACHE[app_key] = {'ts': now, 'data': payload, 'ttl': 30}
        return payload

    payload = {"ok": True, "data": _serialize_prediction_log(pl, source)}
    try:
        from . import cache as _cache
        try:
            _cache.set(f"serializers_current_payload:{app_key}", payload, timeout=30)
        except Exception:
            _CURRENT_CACHE[app_key] = {'ts': now, 'data': payload, 'ttl': 30}
    except Exception:
        _CURRENT_CACHE[app_key] = {'ts': now, 'data': payload, 'ttl': 30}
    return payload


def get_latest5_payload(source: Optional[str] = None) -> Dict[str, Any]:
    pls = db.session.query(models.PredictionLog).order_by(models.PredictionLog.created_at.desc()).limit(5).all()
    if source:
        if source.lower() == 'wunderground':
            pls = [p for p in pls if p.wunderground_prediction_result is not None]
        elif source.lower() == 'ecowitt':
            pls = [p for p in pls if p.ecowitt_prediction_result is not None]
    payload = {"ok": True, "count": len(pls), "data": [_serialize_prediction_log(p, source) for p in pls]}
    return payload


def get_history_payload(page: int = 1, start_date: Optional[str] = None, end_date: Optional[str] = None, data_source: Optional[str] = None, model_id: Optional[int] = None, per_page: int = 5) -> Dict[str, Any]:
    if page < 1:
        page = 1

    q = db.session.query(models.PredictionLog)

    df = None
    dt = None
    if start_date:
        try:
            df = datetime.fromisoformat(start_date)
            q = q.filter(models.PredictionLog.created_at >= df)
        except ValueError:
            return {"ok": False, "message": "Invalid start_date/start_time format; gunakan ISO8601"}
    if end_date:
        try:
            dt = datetime.fromisoformat(end_date)
            q = q.filter(models.PredictionLog.created_at <= dt)
        except ValueError:
            return {"ok": False, "message": "Invalid end_date/end_time format; gunakan ISO8601"}
    if df and dt and df > dt:
        return {"ok": False, "message": "start_date harus <= end_date"}

    if model_id:
        try:
            q = q.filter(models.PredictionLog.model_id == int(model_id))
        except (ValueError, TypeError):
            return {"ok": False, "message": "model_id harus berupa integer"}

    if data_source:
        ds = data_source.lower()
        if ds == 'wunderground':
            q = q.filter(models.PredictionLog.wunderground_prediction_result.isnot(None))
        elif ds == 'ecowitt':
            q = q.filter(models.PredictionLog.ecowitt_prediction_result.isnot(None))
        else:
            return {"ok": False, "message": "data_source harus 'wunderground' atau 'ecowitt'"}

    total = q.count()

    pls = (
        q.order_by(models.PredictionLog.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    payload = {
        "ok": True,
        "page": page,
        "per_page": per_page,
        "total": total,
        "data": [_serialize_prediction_log(p, data_source) for p in pls],
    }
    return payload


def get_source_current_payload(source: str) -> Dict[str, Any]:
    if source not in ('wunderground', 'ecowitt'):
        return {"ok": False, "message": "invalid source"}

    if source == 'wunderground':
        pl = db.session.query(models.PredictionLog).filter(models.PredictionLog.wunderground_prediction_result.isnot(None)).order_by(models.PredictionLog.created_at.desc()).first()
    else:
        pl = db.session.query(models.PredictionLog).filter(models.PredictionLog.ecowitt_prediction_result.isnot(None)).order_by(models.PredictionLog.created_at.desc()).first()

    if not pl:
        return {"ok": False, "message": f"No {source} prediction logs found"}
    return {"ok": True, "data": _serialize_prediction_log(pl, source)}

def get_graph_payload(range_param: Optional[str], month: Optional[str] = None, source: Optional[str] = None, datatype: Optional[str] = None) -> Dict[str, Any]:
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
        rows = (
            db.session.query(table)
            .filter(table.created_at >= start_dt_utc, table.created_at <= end_dt_utc)
            .order_by(table.created_at.asc())
            .all()
        )
    except Exception as e:
        return {"ok": False, "message": f"database error: {e}"}

    per_day = defaultdict(list)
    for r in rows:
        created = getattr(r, 'created_at', None)
        if not created:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        created_wib = created.astimezone(WIB)
        if created_wib.year != year_now:
            continue
        d_iso = created_wib.date().isoformat()
        val = getattr(r, col_name, None)
        if val is None:
            continue
        per_day[d_iso].append((created_wib, float(val)))

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
            vals = [v for _, v in per_day.get(d_iso, [])]
            if vals:
                y = sum(vals) / len(vals)
                status = 'complete'
            else:
                y = None
                status = 'no_data'
        else:
            recs = per_day.get(d_iso, [])
            vals = [v for (ts, v) in recs if ts <= now_wib]
            if vals:
                y = sum(vals) / len(vals)
                status = 'partial'
            else:
                if recs:
                    y = None
                    status = 'no_data'
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