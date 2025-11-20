from datetime import datetime, timezone
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


def get_history_payload(page: int = 1, start_date: Optional[str] = None, end_date: Optional[str] = None,
                        data_source: Optional[str] = None, model_id: Optional[int] = None,
                        per_page: int = 5) -> Dict[str, Any]:
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


def _build_series(rows: List[models.PredictionLog], metric_key: str, is_ecowitt: bool = False) -> List[Dict[str, Any]]:
    series = []
    for r in rows:
        wl = r.weather_log_ecowitt if is_ecowitt else r.weather_log_wunderground
        if not wl:
            continue
        val = wl.to_dict().get(metric_key)
        if val is None:
            continue
        series.append({"ts": wl.created_at.isoformat() if wl.created_at else None, "value": val})
    return series


def get_graph_payload(source: str, metric: str = 'wind_speed', start: Optional[str] = None, end: Optional[str] = None) -> Dict[str, Any]:
    q = db.session.query(models.PredictionLog)
    if start:
        try:
            q = q.filter(models.PredictionLog.created_at >= datetime.fromisoformat(start))
        except ValueError:
            return {"ok": False, "message": "Invalid start_date format"}
    if end:
        try:
            q = q.filter(models.PredictionLog.created_at <= datetime.fromisoformat(end))
        except ValueError:
            return {"ok": False, "message": "Invalid end_date format"}

    rows = q.order_by(models.PredictionLog.created_at.desc()).all()
    is_ecowitt = source == 'ecowitt'
    series = _build_series(rows, metric, is_ecowitt=is_ecowitt)
    return {"ok": True, "metric": metric, "data": series}
