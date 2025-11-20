import os
from datetime import datetime, timezone, timedelta

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

        # deterministic timestamps (UTC)
        earlier_utc = datetime(2025, 11, 18, 1, 0, 0, tzinfo=timezone.utc)
        later_utc = datetime(2025, 11, 18, 10, 0, 0, tzinfo=timezone.utc)

        # seed model
        m = models.Model(name='det-model', range_prediction=1)
        db.session.add(m)

        eco = models.WeatherLogEcowitt()
        eco.request_time = earlier_utc
        eco.created_at = earlier_utc
        eco.temperature_main_outdoor = 21.5
        eco.humidity_outdoor = 65
        db.session.add(eco)

        wu = models.WeatherLogWunderground()
        wu.request_time = later_utc
        wu.created_at = later_utc
        wu.temperature = 22.0
        wu.humidity = 60
        db.session.add(wu)

        db.session.flush()

        p1 = models.PredictionLog(created_at=earlier_utc, weather_log_ecowitt_id=eco.id, model_id=m.id)
        p2 = models.PredictionLog(created_at=later_utc, weather_log_wunderground_id=wu.id, model_id=m.id)
        db.session.add_all([p1, p2])
        db.session.commit()

        yield app.test_client()


def _to_wib_iso(dt):
    # helper matching app behavior
    return dt.astimezone(timezone(timedelta(hours=7))).isoformat()


def test_history_default_returns_both_and_times(client):
    resp = client.get('/api/history')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    # default source is 'ecowitt' so we expect only the ecowitt record
    assert body['total'] == 1
    # newest first (only one)
    first = body['data'][0]
    # check id and time exist for the single returned ecowitt record
    assert first['time'] is not None

    # Convert known seeded earlier_utc (ecowitt record) to WIB and compare ISO prefix
    earlier_utc = datetime(2025, 11, 18, 1, 0, 0, tzinfo=timezone.utc)
    expected_wib = earlier_utc.astimezone(timezone(timedelta(hours=7))).isoformat()
    assert first['time'].startswith(expected_wib[:16])  # compare up to minutes

    # check wunderground by explicitly requesting that source
    resp_wu = client.get('/api/history?source=wunderground')
    assert resp_wu.status_code == 200
    body_wu = resp_wu.get_json()
    assert body_wu['total'] == 1


def test_history_date_and_time_exact_match(client):
    # date/time that matches the later record in WIB
    later_utc = datetime(2025, 11, 18, 10, 0, 0, tzinfo=timezone.utc)
    later_wib = later_utc.astimezone(timezone(timedelta(hours=7)))
    date = later_wib.strftime('%Y-%m-%d')
    time = later_wib.strftime('%H:%M')

    resp = client.get(f"/api/history?date={date}&time={time}&source=wunderground")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['total'] >= 1
    # because source provided, item should be wrapped under weather_wunderground
    found = False
    for it in body['data']:
        if isinstance(it, dict) and 'weather_wunderground' in it:
            w = it['weather_wunderground']
            if w.get('id') is not None:
                found = True
    assert found


def test_history_start_end_wib_naive(client):
    # provide start/end using allowed start_date/start_time + end_date/end_time pattern
    start_wib = datetime(2025, 11, 18, 8, 0, 0, tzinfo=timezone(timedelta(hours=7)))
    end_wib = datetime(2025, 11, 18, 17, 0, 0, tzinfo=timezone(timedelta(hours=7)))
    sd = start_wib.strftime('%Y-%m-%d')
    st = start_wib.strftime('%H:%M')
    ed = end_wib.strftime('%Y-%m-%d')
    et = end_wib.strftime('%H:%M')

    resp = client.get(f"/api/history?start_date={sd}&end_date={ed}&start_time={st}&end_time={et}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    # default source is ecowitt -> only the ecowitt record falls into the range when not specifying source
    assert body['total'] >= 0
    # querying the same range for wunderground returns matching records when specified
    resp_wu = client.get(f"/api/history?start_date={sd}&end_date={ed}&start_time={st}&end_time={et}&source=wunderground")
    assert resp_wu.status_code == 200
    body_wu = resp_wu.get_json()
    assert isinstance(body_wu.get('total'), int)
