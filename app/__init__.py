from flask_cors import CORS
import os
import sys
from datetime import datetime, timedelta, timezone
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_migrate import upgrade as _flask_migrate_upgrade
from flask_apscheduler import APScheduler
from dotenv import load_dotenv
import logging
from .logging_config import configure_logging
from flask_caching import Cache
import atexit


_should_load_dotenv = os.environ.get('LOAD_DOTENV', 'false').lower() in ('1', 'true', 'yes') or os.environ.get('FLASK_ENV', '').lower() == 'development'
if _should_load_dotenv:
    load_dotenv()
else:
    logging.info('.env tidak dimuat secara otomatis (LOAD_DOTENV tidak diset & FLASK_ENV bukan development).')

db = SQLAlchemy()
migrate = Migrate()
scheduler = APScheduler()
cache = Cache()

def _is_management_command() -> bool:
    try:
        argv = ' '.join(sys.argv).lower()
    except Exception:
        argv = ''
    mg_cmds = ('db', 'migrate', 'upgrade', 'init', 'revision', 'alembic')
    return any(cmd in argv for cmd in mg_cmds)

def create_app():

    is_mgmt = _is_management_command()
    argv = ' '.join(sys.argv).lower()

    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    try:
        configure_logging(level=getattr(logging, log_level, logging.INFO))
    except Exception:
        logging.warning('Gagal mengonfigurasi logging, menggunakan konfigurasi default.')

    app = Flask(__name__, instance_relative_config=False)

    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        try:
            if _is_management_command():
                secret_key = os.urandom(32).hex()
                logging.info('SECRET_KEY tidak diset dan sedang menjalankan perintah manajemen; menggunakan ephemeral SECRET_KEY tanpa menulis file.')
            else:
                os.makedirs(app.instance_path, exist_ok=True)
                secret_file = os.path.join(app.instance_path, 'secret_key')
                if os.path.exists(secret_file):
                    with open(secret_file, 'r') as f:
                        secret_key = f.read().strip()
                else:
                    secret_key = os.urandom(32).hex()
                    with open(secret_file, 'w') as f:
                        f.write(secret_key)
                    try:
                        os.chmod(secret_file, 0o600)
                    except Exception:
                        pass
                logging.info(f"SECRET_KEY tidak ditemukan di env; dibuat/diambil di {secret_file}. Jangan commit file ini ke VCS.")
        except Exception as e:
            logging.warning(f"SECRET_KEY tidak diset dan menyimpan otomatis gagal: {e}. Menggunakan key random ephemeral.")
            secret_key = os.urandom(32).hex()
    else:
        logging.info('SECRET_KEY diambil dari environment.')

    app.config['SECRET_KEY'] = secret_key

    default_db = "mysql+pymysql://root@localhost:3306/tuws_pws"
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", default_db),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SCHEDULER_API_ENABLED=True,
    )

    CORS(app, resources={r"/api/*": {"origins" : "*"}})

    db.init_app(app)

    if not is_mgmt:
        try:
            cache.init_app(app, config={'CACHE_TYPE': 'simple'})
            try:
                cache.clear()
            except Exception:
                pass
            logging.info('Cache: menggunakan simple (in-memory) cache.')
        except Exception as e:
            logging.warning(f'Gagal menginisialisasi simple cache: {e}. Melanjutkan tanpa caching.')

    migrate.init_app(app, db)

    auto_migrate_flag = os.environ.get('AUTO_MIGRATE', '').lower() in ('1', 'true', 'yes')
    if auto_migrate_flag:
        try:
            if getattr(migrate, 'db', None) is not None or 'migrate' in globals():
                logging.info('AUTO_MIGRATE=1 terdeteksi, menjalankan flask db upgrade (perlindungan otomatis).')
                try:
                    with app.app_context():
                        _flask_migrate_upgrade()
                    logging.info('flask db upgrade selesai.')
                except Exception as e:
                    logging.error(f'Gagal menjalankan migrasi otomatis: {e}')
            else:
                logging.warning('Flask-Migrate belum diinisialisasi; melewati AUTO_MIGRATE.')
        except Exception as e:
            logging.warning(f'Auto-migrate gagal karena: {e}')

    from . import models

    if is_mgmt and 'upgrade' in argv:
        def _seed_after_upgrade():
            try:
                from .db_seed import seed_labels_and_models
                logging.info('[seed-after-upgrade] invoking db_seed.seed_labels_and_models')
                seed_labels_and_models(database_url=app.config.get('SQLALCHEMY_DATABASE_URI'))
                logging.info('[seed-after-upgrade] db_seed completed')
            except Exception as e:
                logging.warning(f'Error running seed-after-upgrade: {e}')

        atexit.register(_seed_after_upgrade)

    disable_scheduler = os.environ.get('DISABLE_SCHEDULER_FOR_TESTS', '').lower() in ('1', 'true', 'yes')
    if not disable_scheduler and not is_mgmt:
        try:
            scheduler.init_app(app)
            logging.info('Scheduler initialized but not started. Start it from run.py or your process manager.')
        except Exception as e:
            logging.warning(f"Gagal meng-inisialisasi APScheduler: {e}")

    if not is_mgmt:
        with app.app_context():
            from . import models

        try:
            from .api import bp as api_bp
            app.register_blueprint(api_bp, url_prefix='/api')
            try:
                from . import serializers as _serializers
                _serializers._CURRENT_CACHE = {'ts': None, 'data': None, 'ttl': 30}
            except Exception:
                pass
        except Exception as e:
            logging.warning(f"Gagal mendaftarkan blueprint API: {e}")
    else:
        logging.debug('create_app in management mode: skipping cache, scheduler, and blueprint registration.')

    return app
