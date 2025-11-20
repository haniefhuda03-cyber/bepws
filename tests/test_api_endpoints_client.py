import os
import sys
import json
import time

# Ensure test-friendly env BEFORE importing the app
os.environ['DISABLE_SCHEDULER_FOR_TESTS'] = '1'
os.environ['DATABASE_URL'] = os.environ.get('DATABASE_URL', 'sqlite:///:memory:')

from app import create_app
def run_client_tests():
    app = create_app()
    # create tables for test DB if missing and seed minimal data for deterministic runs
    with app.app_context():
        from app import db
        db.create_all()
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
        except Exception:
            pass

    client = app.test_client()

    def req(path, params=None):
        url = '/api' + path
        r = client.get(url, query_string=params)
        text = None
        try:
            body = r.get_json()
        except Exception:
            body = None
            try:
                text = r.get_data(as_text=True)
            except Exception:
                text = None
        return {'status': r.status_code, 'body': body, 'text': text}

    results = []

    # /data tests
    for source in ['ecowitt', 'wunderground']:
        results.append(('GET /data general', source, req('/data', {'type': 'general', 'source': source})))
        for limit in [5, 24]:
            results.append((f'GET /data hourly limit={limit}', source, req('/data', {'type': 'hourly', 'limit': limit, 'source': source})))
        for pid in [1]:
            results.append((f'GET /data details id={pid}', source, req('/data', {'type': 'details', 'id': pid, 'source': source})))

    # /history
    for source in ['ecowitt', 'wunderground']:
        for page in [1, 2]:
            results.append((f'GET /history page={page}', source, req('/history', {'source': source, 'page': page})))

    # /graph
    metrics = ['suhu', 'temperature', 'tekanan_udara_relatif', 'kelembapan', 'kecepatan_angin', 'uvi', 'curah_hujan', 'radiasi_matahari']
    ranges = ['harian', 'pekanan']
    for source in ['ecowitt', 'wunderground']:
        for metric in metrics:
            for rp in ranges:
                results.append((f'GET /graph {source} metric={metric} range={rp}', source, req('/graph', {'source': source, 'metric': metric, 'range': rp})))

    # health
    results.append(('GET /health', None, req('/health')))

    return results


def print_summary(results):
    ok = 0
    print('\nClient API Test Summary')
    print('=======================')
    for name, source, r in results:
        status = r.get('status')
        if 200 <= (status or 0) < 300:
            outcome = f'OK {status}'
            ok += 1
        else:
            outcome = f'FAIL {status}'
        print(f'- {name} (source={source}) => {outcome}')
        if r.get('body') is not None:
            print('  body sample:', json.dumps(r['body'], ensure_ascii=False)[:300])
        elif r.get('text'):
            print('  text sample:', (r.get('text') or '')[:200])

    print(f'\nPassed {ok}/{len(results)} checks')


if __name__ == '__main__':
    print('Running in-process client tests (scheduler disabled).')
    time.sleep(0.5)
    results = run_client_tests()
    print_summary(results)
    failed = [r for _, _, r in results if not (200 <= (r.get('status') or 0) < 300)]
    if failed:
        print('\nSome checks failed or returned non-2xx statuses.')
        sys.exit(2)
    print('\nAll checks returned 2xx statuses.')
    sys.exit(0)


def test_client_endpoints_all_routes():
    """Pytest-compatible wrapper for client tests; asserts all checks return 2xx."""
    results = run_client_tests()
    failed = []
    for name, source, r in results:
        status = r.get('status') or 0
        if not (200 <= status < 300):
            failed.append((name, source, status))
    assert not failed, f"Client checks failed: {failed}"
