import os
import json
from datetime import datetime, timedelta, timezone

# ensure test-friendly env BEFORE importing app
os.environ['DISABLE_SCHEDULER_FOR_TESTS'] = '1'
os.environ['DATABASE_URL'] = os.environ.get('DATABASE_URL', 'sqlite:///:memory:')

from app import create_app


def prepare_and_seed():
    app = create_app()
    with app.app_context():
        from app import db
        db.create_all()
        try:
            from app.models import Model, Label, WeatherLogEcowitt, WeatherLogWunderground, PredictionLog
            now_utc = datetime.now(timezone.utc)

            m = db.session.query(Model).filter_by(name='default_xgboost').first()
            if not m:
                m = Model(name='default_xgboost', range_prediction=60)
                db.session.add(m)
                db.session.commit()

            lab = db.session.query(Label).first()
            if not lab:
                lab = Label(name='Cerah / Berawan')
                db.session.add(lab)
                db.session.commit()

            wl_e = db.session.query(WeatherLogEcowitt).first()
            if not wl_e:
                wl_e = WeatherLogEcowitt(
                    vpd_outdoor=0.082,
                    temperature_main_outdoor=21.3,
                    temperature_feels_like_outdoor=21.3,
                    dew_point_outdoor=19.4,
                    humidity_outdoor=89.0,
                    solar_irradiance=20.2,
                    uvi=0.0,
                    rain_rate=0.0,
                    wind_speed=0.0,
                    wind_gust=0.0,
                    wind_direction=288.0,
                    pressure_relative=1009.9,
                    pressure_absolute=932.2,
                    request_time=now_utc,
                )
                db.session.add(wl_e)
                db.session.commit()

            wl_w = db.session.query(WeatherLogWunderground).first()
            if not wl_w:
                wl_w = WeatherLogWunderground(
                    solar_radiation=20.2,
                    ultraviolet_radiation=0.0,
                    humidity=78.0,
                    temperature=21.0,
                    pressure=1010.0,
                    wind_direction=170.0,
                    wind_speed=3.1,
                    wind_gust=4.1,
                    precipitation_rate=0.0,
                    precipitation_total=1.0,
                    request_time=now_utc,
                )
                db.session.add(wl_w)
                db.session.commit()

            pl = db.session.query(PredictionLog).first()
            if not pl:
                pl = PredictionLog(
                    weather_log_ecowitt_id=wl_e.id if wl_e else None,
                    weather_log_wunderground_id=wl_w.id if wl_w else None,
                    model_id=m.id,
                    ecowitt_prediction_result=lab.id,
                    wunderground_prediction_result=lab.id,
                )
                # ensure created_at is set to now_utc explicitly
                try:
                    pl.created_at = now_utc
                except Exception:
                    pass
                db.session.add(pl)
                db.session.commit()

            return app
        except Exception as e:
            print('Seeding failed:', e)
            return app


def short_print(label, res):
    status = res.get('status')
    body = res.get('body')
    print(f"== {label} => {status}")
    if body is None:
        print('   <no-json-body>')
    else:
        s = json.dumps(body, ensure_ascii=False)
        print('   ', s[:1000])
    print()


if __name__ == '__main__':
    app = prepare_and_seed()
    client = app.test_client()

    # prepare WIB date/time strings for queries (server expects WIB input)
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc.astimezone(timezone(timedelta(hours=7)))
    date_wib = now_wib.strftime('%Y-%m-%d')
    time_wib = now_wib.strftime('%H:%M:%S')
    time_short = now_wib.strftime('%H:%M')

    start_wib = (now_wib - timedelta(hours=1)).isoformat()
    end_wib = (now_wib + timedelta(hours=1)).isoformat()

    checks = []

    # /api/data?type=general for both sources
    for src in ['ecowitt', 'wunderground']:
        checks.append((f"/api/data?type=general&source={src}", client.get('/api/data', query_string={'type': 'general', 'source': src})))

    # /api/history combinations
    # default (no source) - should return flat items
    checks.append((f"/api/history (default page) ", client.get('/api/history')))
    checks.append((f"/api/history?page=1", client.get('/api/history', query_string={'page': 1})))
    checks.append((f"/api/history?date={date_wib}", client.get('/api/history', query_string={'date': date_wib})))
    checks.append((f"/api/history?date={date_wib}&time={time_short}", client.get('/api/history', query_string={'date': date_wib, 'time': time_short})))
    checks.append((f"/api/history?start={start_wib}&end={end_wib}", client.get('/api/history', query_string={'start': start_wib, 'end': end_wib})))
    checks.append((f"/api/history?start_date={date_wib}&start_time={time_short}", client.get('/api/history', query_string={'start_date': date_wib, 'start_time': time_short})))
    checks.append((f"/api/history?end_date={date_wib}&end_time={time_short}", client.get('/api/history', query_string={'end_date': date_wib, 'end_time': time_short})))

    # with explicit source param (wrapped)
    checks.append((f"/api/history?source=ecowitt&date={date_wib}", client.get('/api/history', query_string={'source': 'ecowitt', 'date': date_wib})))
    checks.append((f"/api/history?source=wunderground&date={date_wib}", client.get('/api/history', query_string={'source': 'wunderground', 'date': date_wib})))

    # run and print
    results = []
    for label, r in checks:
        try:
            body = r.get_json()
        except Exception:
            body = None
        results.append({'label': label, 'status': r.status_code, 'body': body})

    for r in results:
        short_print(r['label'], r)

    # Exit non-zero if any non-2xx
    failed = [r for r in results if not (200 <= (r['status'] or 0) < 300)]
    if failed:
        print('Some checks failed')
        raise SystemExit(2)
    print('All checks OK')
