import os
import sys
import json
import time

# Ensure test-friendly env BEFORE importing the app
os.environ['DISABLE_SCHEDULER_FOR_TESTS'] = '1'
os.environ['DATABASE_URL'] = os.environ.get('DATABASE_URL', 'sqlite:///:memory:')

from app import create_app


def prepare_app_and_seed():
    app = create_app()
    with app.app_context():
        from app import db
        db.create_all()
        # seed minimal data
        try:
            from app.models import Model, Label, WeatherLogEcowitt, WeatherLogWunderground, PredictionLog
            from datetime import datetime

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

            # ecowitt
            wl_e = db.session.query(WeatherLogEcowitt).first()
            if not wl_e:
                wl_e = WeatherLogEcowitt(
                    vpd_outdoor=0.1,
                    temperature_main_outdoor=22.5,
                    temperature_feels_like_outdoor=22.0,
                    dew_point_outdoor=18.0,
                    humidity_outdoor=80.0,
                    solar_irradiance=40.0,
                    uvi=0.0,
                    rain_rate=0.0,
                    wind_speed=3.2,
                    wind_gust=4.0,
                    wind_direction=180.0,
                    pressure_relative=1010.0,
                    pressure_absolute=1000.0,
                    request_time=datetime.now(),
                )
                db.session.add(wl_e)
                db.session.commit()

            # wunderground
            wl_w = db.session.query(WeatherLogWunderground).first()
            if not wl_w:
                wl_w = WeatherLogWunderground(
                    solar_radiation=40.0,
                    ultraviolet_radiation=0.0,
                    humidity=78.0,
                    temperature=22.0,
                    pressure=1010.0,
                    wind_direction=170.0,
                    wind_speed=3.1,
                    wind_gust=4.1,
                    precipitation_rate=0.0,
                    precipitation_total=1.0,
                    request_time=datetime.now(),
                )
                db.session.add(wl_w)
                db.session.commit()

            # prediction log
            pl = db.session.query(PredictionLog).first()
            if not pl:
                pl = PredictionLog(
                    weather_log_ecowitt_id=wl_e.id if wl_e else None,
                    weather_log_wunderground_id=wl_w.id if wl_w else None,
                    model_id=m.id,
                    ecowitt_prediction_result=lab.id,
                    wunderground_prediction_result=lab.id,
                )
                db.session.add(pl)
                db.session.commit()

            return app, pl.id
        except Exception:
            # if seeding fails, still return app and None id
            return app, None


def run_tests():
    app, pl_id = prepare_app_and_seed()
    client = app.test_client()

    def call(path, params=None):
        r = client.get('/api' + path, query_string=params)
        try:
            body = r.get_json()
        except Exception:
            body = None
        return {'status': r.status_code, 'body': body}

    results = []

    # /data: general, hourly, details
    for source in ['ecowitt', 'wunderground']:
        results.append((f"/data general source={source}", call('/data', {'type': 'general', 'source': source})))
        results.append((f"/data hourly source={source}", call('/data', {'type': 'hourly', 'limit': 5, 'source': source})))
        if pl_id:
            results.append((f"/data details source={source} id={pl_id}", call('/data', {'type': 'details', 'id': pl_id, 'source': source})))
        else:
            results.append((f"/data details source={source} id=NONE", {'status': None, 'body': None}))

    # /graph: all metrics and ranges
    metrics = ['suhu', 'temperature', 'tekanan_udara_relatif', 'kelembapan', 'kecepatan_angin', 'uvi', 'curah_hujan', 'radiasi_matahari']
    ranges = ['harian', 'pekanan']
    for source in ['ecowitt', 'wunderground']:
        for metric in metrics:
            for rp in ranges:
                results.append((f"/graph source={source} metric={metric} range={rp}", call('/graph', {'source': source, 'metric': metric, 'range': rp})))

    # /history pages
    for source in ['ecowitt', 'wunderground']:
        for page in [1, 2]:
            results.append((f"/history source={source} page={page}", call('/history', {'source': source, 'page': page})))

    # /health
    results.append(('/health', call('/health')))

    return results


def print_summary(results):
    ok = 0
    total = len(results)
    print('\nAPI 4-endpoints Test Summary')
    print('===========================')
    for name, res in results:
        status = res.get('status')
        if status and 200 <= status < 300:
            state = f'OK {status}'
            ok += 1
        else:
            state = f'FAIL {status}'
        print(f'- {name} => {state}')
        if res.get('body') is not None:
            try:
                print('  body sample:', json.dumps(res['body'], ensure_ascii=False)[:300])
            except Exception:
                pass

    print(f'\nPassed {ok}/{total} checks')
    if ok != total:
        sys.exit(2)


def test_api_4endpoints_all_routes():
    """Pytest-compatible wrapper: run the scripted checks and assert all endpoints returned 2xx."""
    results = run_tests()
    failing = []
    for name, res in results:
        status = res.get('status') or 0
        if not (200 <= status < 300):
            failing.append((name, status))
    assert not failing, f"Some endpoints failed: {failing}"


if __name__ == '__main__':
    print('Running API 4-endpoints tests (in-process, seeded DB)')
    time.sleep(0.2)
    results = run_tests()
    print_summary(results)
