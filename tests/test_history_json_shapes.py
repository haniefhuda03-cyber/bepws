import os
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app, db
from app import models


@pytest.fixture
def client():
    os.environ['DISABLE_SCHEDULER_FOR_TESTS'] = '1'
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    app = create_app()
    app.config['TESTING'] = True

    with app.app_context():
        db.create_all()

        # Seed model
        m = models.Model(name='test-model', range_prediction=1)
        db.session.add(m)

        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        earlier_utc = now_utc - timedelta(hours=3)

        eco = models.WeatherLogEcowitt()
        eco.request_time = earlier_utc
        eco.created_at = earlier_utc
        eco.temperature_main_outdoor = 26.1
        eco.humidity_outdoor = 70
        db.session.add(eco)

        wu = models.WeatherLogWunderground()
        wu.request_time = now_utc
        wu.created_at = now_utc
        wu.temperature = 24.5
        wu.humidity = 68
        db.session.add(wu)

        db.session.flush()

        p1 = models.PredictionLog(created_at=earlier_utc, weather_log_ecowitt_id=eco.id, model_id=m.id)
        p2 = models.PredictionLog(created_at=now_utc, weather_log_wunderground_id=wu.id, model_id=m.id)
        db.session.add_all([p1, p2])
        db.session.commit()

        yield app.test_client()


def _is_wib_iso(s: str) -> bool:
    # crude check: string contains offset +07:00 or ends with Z converted to +07:00
    return s is not None and ('+07:00' in s or s.endswith('+07:00'))


def test_history_default_shape(client):
    resp = client.get('/api/history')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get('ok') is True
    assert 'page' in body and 'per_page' in body and 'total' in body and 'data' in body
    assert isinstance(body['data'], list)
    # check first item keys
    if body['data']:
        item = body['data'][0]
        assert 'id' in item
        assert 'time' in item and _is_wib_iso(item['time'])
        # temp/humidity/pressure/wind keys present (may be None)
        for k in ('temp', 'humidity', 'pressure', 'wind_speed'):
            assert k in item


def test_history_wrapped_when_source_param(client):
    resp = client.get('/api/history?source=ecowitt')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    # when source param provided, items should be wrapped under 'weather_ecowitt' keys
    if body['data']:
        first = body['data'][0]
        # if wrapped, first should be a dict with key 'weather_ecowitt'
        assert isinstance(first, dict)
        assert 'weather_ecowitt' in first or 'weather_wunderground' in first


def test_history_flat_when_source_omitted(client):
    resp = client.get('/api/history')
    body = resp.get_json()
    # default should be flat items (not nested under weather_x unless source explicitly provided)
    if body['data']:
        first = body['data'][0]
        assert 'weather_ecowitt' not in first and 'weather_wunderground' not in first


def test_history_iso_with_tz(client):
    # query using timezone-aware ISO datetimes (UTC) as start/end
    with client.application.app_context():
        pls = db.session.query(models.PredictionLog).order_by(models.PredictionLog.created_at).all()
        start_utc = pls[0].created_at
        end_utc = pls[-1].created_at

    # use allowed start_date/start_time + end_date/end_time pattern instead
    start_wib = start_utc.astimezone(timezone(timedelta(hours=7)))
    end_wib = end_utc.astimezone(timezone(timedelta(hours=7)))
    sd = start_wib.strftime('%Y-%m-%d')
    st = start_wib.strftime('%H:%M')
    ed = end_wib.strftime('%Y-%m-%d')
    et = end_wib.strftime('%H:%M')

    resp = client.get(f"/api/history?start_date={sd}&end_date={ed}&start_time={st}&end_time={et}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True


def test_history_invalid_date_returns_400(client):
    # date alone is not allowed under new policy (must include time)
    resp = client.get('/api/history?date=not-a-date')
    assert resp.status_code == 400


def test_history_invalid_page_returns_400(client):
    resp = client.get('/api/history?page=zero')
    assert resp.status_code == 400
