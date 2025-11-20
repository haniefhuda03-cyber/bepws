import os
import json
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

        # seed minimal data: two PredictionLog entries at distinct times
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        earlier_utc = now_utc - timedelta(hours=2)

        # create dummy weather logs (ecowitt and wunderground)
        eco = models.WeatherLogEcowitt()
        eco.request_time = earlier_utc
        eco.created_at = earlier_utc
        # set a few fields referenced by API
        eco.temperature_main_outdoor = 25.5
        eco.humidity_outdoor = 80
        db.session.add(eco)

        wu = models.WeatherLogWunderground()
        wu.request_time = now_utc
        wu.created_at = now_utc
        wu.temperature = 24.0
        wu.humidity = 78
        db.session.add(wu)
        db.session.commit()

        # create a Model record because PredictionLog.model_id is NOT NULL
        m = models.Model()
        m.name = 'test-model'
        m.range_prediction = 1
        db.session.add(m)
        db.session.flush()

        # prediction logs referencing weather logs
        p1 = models.PredictionLog()
        p1.created_at = earlier_utc
        p1.weather_log_ecowitt_id = eco.id
        p1.ecowitt_label_id = None
        p1.model_id = m.id
        db.session.add(p1)

        p2 = models.PredictionLog()
        p2.created_at = now_utc
        p2.weather_log_wunderground_id = wu.id
        p2.wunderground_label_id = None
        p2.model_id = m.id
        db.session.add(p2)

        db.session.commit()

        yield app.test_client()


def test_history_iso_start_end(client):
    # Use allowed start_date/start_time + end_date/end_time pattern
    with client.application.app_context():
        pls = db.session.query(models.PredictionLog).order_by(models.PredictionLog.created_at).all()
        assert len(pls) >= 2
        start_utc = pls[0].created_at
        end_utc = pls[-1].created_at

    start_wib = start_utc.astimezone(timezone(timedelta(hours=7)))
    end_wib = end_utc.astimezone(timezone(timedelta(hours=7)))
    sd = start_wib.strftime('%Y-%m-%d')
    st = start_wib.strftime('%H:%M')
    ed = end_wib.strftime('%Y-%m-%d')
    et = end_wib.strftime('%H:%M')

    resp = client.get(f"/api/history?start_date={sd}&end_date={ed}&start_time={st}&end_time={et}&source=ecowitt")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert 'data' in body


def test_history_date_and_time(client):
    # Query by date and time
    with client.application.app_context():
        p = db.session.query(models.PredictionLog).order_by(models.PredictionLog.created_at.desc()).first()
        ts = p.created_at.astimezone(timezone(timedelta(hours=7)))
        date = ts.strftime('%Y-%m-%d')
        time = ts.strftime('%H:%M')

    # use date+time query to avoid exact-second mismatches
    resp = client.get(f"/api/history?date={date}&time={time}&source=wunderground")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert isinstance(body.get('data'), list)


def test_history_startdate_starttime_enddate_endtime(client):
    # Use start_date + start_time and end_date + end_time
    with client.application.app_context():
        pls = db.session.query(models.PredictionLog).order_by(models.PredictionLog.created_at).all()
        s = pls[0].created_at.astimezone(timezone(timedelta(hours=7)))
        e = pls[-1].created_at.astimezone(timezone(timedelta(hours=7)))
        sd = s.strftime('%Y-%m-%d')
        st = s.strftime('%H:%M')
        ed = e.strftime('%Y-%m-%d')
        et = e.strftime('%H:%M')

    # use date-range query with explicit start_time and end_time for the date range
    resp = client.get(f"/api/history?start_date={sd}&end_date={ed}&start_time={st}&end_time={et}&source=ecowitt")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert isinstance(body.get('total'), int)


def test_history_invalid_combination_returns_400(client):
    # Combining ISO start with other params should return 400 per validation
    now = datetime.now()
    iso = now.isoformat()
    resp = client.get(f"/api/history?start={iso}&date=2020-01-01")
    assert resp.status_code == 400
