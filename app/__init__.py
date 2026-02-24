import os
import sys
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_migrate import upgrade as _flask_migrate_upgrade
from flask_apscheduler import APScheduler
from flask_cors import CORS
from dotenv import load_dotenv
import logging
from .logging_config import configure_logging
import atexit



# Auto-load .env jika file ada di project root (standard Python practice)
# Tidak perlu set LOAD_DOTENV=true secara manual
_dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.isfile(_dotenv_path):
    load_dotenv(_dotenv_path)
else:
    logging.info('.env file tidak ditemukan, menggunakan environment variables saja.')

db = SQLAlchemy()
migrate = Migrate()
scheduler = APScheduler()

def _is_management_command() -> bool:
    try:
        argv = ' '.join(sys.argv).lower()
    except Exception:
        argv = ''
    mg_cmds = ('db', 'migrate', 'upgrade', 'init', 'revision', 'alembic')
    return any(cmd in argv for cmd in mg_cmds)

def create_app(test_config=None):

    is_mgmt = _is_management_command()
    argv = ' '.join(sys.argv).lower()

    log_level = os.environ.get('LOG_LEVEL', None)
    try:
        # Jika menjalankan perintah manajemen (migrate/upgrade/init), kurangi noise logging
        if is_mgmt:
            # Kurangi pesan TF / oneDNN di environment saat manajemen
            os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
            # Jika tidak ada override LOG_LEVEL, set ke WARNING agar hanya pesan penting tampil
            if not log_level:
                configure_logging(level=logging.WARNING)
            else:
                configure_logging(level=getattr(logging, log_level.upper(), logging.WARNING))
            # Pastikan logger db_seed tetap INFO agar seeding terlihat
            try:
                logging.getLogger('db_seed').setLevel(logging.INFO)
            except Exception:
                pass
        else:
            configure_logging(level=getattr(logging, (log_level or 'INFO').upper(), logging.INFO))
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
    
    # =====================================================
    # SECURITY WARNING: WEAK SECRET_KEY
    # =====================================================
    if secret_key and len(secret_key) < 32:
        logging.warning(
            f"[SECURITY] SECRET_KEY is weak ({len(secret_key)} chars). "
            "Recommended: Use 32+ character random token for production."
        )

    if test_config:
        # Load config for testing
        app.config.from_mapping(test_config)
    else:
        # Load default config
        default_db = "postgresql://postgres@localhost:5432/tuws_pws"
        app.config.from_mapping(
            SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", default_db),
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SQLALCHEMY_ENGINE_OPTIONS={
                "pool_size": 10,            # Jumlah koneksi tetap di pool
                "max_overflow": 20,         # Koneksi tambahan saat pool penuh
                "pool_timeout": 30,         # Timeout menunggu koneksi dari pool (detik)
                "pool_recycle": 1800,       # Recycle koneksi setiap 30 menit (hindari stale)
                "pool_pre_ping": True,      # Cek koneksi masih hidup sebelum dipakai
            },
            SCHEDULER_API_ENABLED=False,  # Disabled for security
            
            # =====================================================
            # STRICT API CONFIGURATION
            # =====================================================
            MAX_CONTENT_LENGTH=1 * 1024 * 1024,  # 1MB max request size
            JSON_SORT_KEYS=False,
            TRAP_HTTP_EXCEPTIONS=True,
        )
    
    # =====================================================
    # REVERSE PROXY SUPPORT
    # =====================================================
    # Trust X-Forwarded-For headers from reverse proxy
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)

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
            # Jobs TIDAK didaftarkan di sini — hanya di run.py via init_scheduler(start=True)
            # Ini mencegah double-registration yang menyebabkan job fire 2x
            
            logging.info('Scheduler initialized (jobs will be registered from run.py).')
        except Exception as e:
            logging.warning(f"Gagal meng-inisialisasi APScheduler: {e}")

    if not is_mgmt:
        with app.app_context():
            from . import models
        
        # =====================================================
        # CORS CONFIGURATION
        # =====================================================
        # Konfigurasi CORS untuk API v3
        # CORS_ORIGINS default "*" untuk semua domain
        # Untuk IP spesifik: "http://192.168.1.100:3000,http://localhost:3000"
        cors_origins = os.environ.get('CORS_ORIGINS', '*')
        if cors_origins == '*':
            cors_allowed = '*'
        else:
            cors_allowed = [o.strip() for o in cors_origins.split(',') if o.strip()]
        
        CORS(app, resources={
            r"/api/v3/*": {
                "origins": cors_allowed,
                "methods": ["GET", "POST", "OPTIONS"],
                "allow_headers": ["X-APP-KEY", "Content-Type"],
                "expose_headers": ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"]
            }
        })
        logging.info(f"CORS enabled for API v3 (origins: {cors_origins})")
        
        # =====================================================
        # SECURITY WARNING: WEAK API KEY
        # =====================================================
        appkey = os.environ.get('APPKEY', '')
        if appkey and len(appkey) < 32:
            logging.warning(
                f"[SECURITY] APPKEY is weak ({len(appkey)} chars). "
                "Recommended: Use 32+ character random token for production."
            )

        try:
            # Register API v3 blueprint
            from .api_v3 import bp_v3 as api_v3_bp
            app.register_blueprint(api_v3_bp, url_prefix='/api/v3')
            
            logging.info('Registered API blueprint: /api/v3')
            
            # =====================================================
            # SWAGGER UI - OpenAPI Documentation  
            # =====================================================
            try:
                import flask_swagger_ui
                _swagger_dist = os.path.join(os.path.dirname(flask_swagger_ui.__file__), 'dist')
                
                @app.route('/api/docs/')
                @app.route('/api/docs')
                def swagger_ui():
                    """Serve Swagger UI HTML."""
                    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>TUWS Weather API v3</title>
  <link rel="stylesheet" type="text/css" href="/api/docs/dist/swagger-ui.css">
  <link rel="icon" type="image/png" href="/api/docs/dist/favicon-32x32.png" sizes="32x32"/>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="/api/docs/dist/swagger-ui-bundle.js"></script>
  <script src="/api/docs/dist/swagger-ui-standalone-preset.js"></script>
  <script>
    SwaggerUIBundle({{
      url: "/api/v3/openapi.yaml",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
      layout: "StandaloneLayout",
      validatorUrl: null
    }});
  </script>
</body>
</html>'''
                
                @app.route('/api/docs/dist/<path:filename>')
                def swagger_dist(filename):
                    """Serve Swagger UI static assets."""
                    from flask import send_from_directory
                    return send_from_directory(_swagger_dist, filename)
                
                logging.info('Swagger UI available at: /api/docs')
            except ImportError:
                logging.warning('flask-swagger-ui not installed. Swagger UI disabled.')
            except Exception as e:
                logging.warning(f'Failed to register Swagger UI: {e}')
            
            try:
                from . import serializers as _serializers
                _serializers._CURRENT_CACHE = {}  # Reset cache (keyed by app_key at runtime)
            except Exception:
                pass
        except Exception as e:
            logging.warning(f"Gagal mendaftarkan blueprint API: {e}")
        
        # =====================================================
        # GLOBAL ERROR HANDLERS
        # =====================================================
        
        def _json_error(code, message):
            return jsonify({
                "meta": {
                    "status": "error",
                    "code": code,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                },
                "error": {"code": f"HTTP_{code}", "message": message},
                "data": None
            }), code
        
        @app.errorhandler(400)
        def bad_request(e):
            return _json_error(400, "Bad Request")
        
        @app.errorhandler(401)
        def unauthorized(e):
            return _json_error(401, "Unauthorized")
        
        @app.errorhandler(403)
        def forbidden(e):
            return _json_error(403, "Forbidden")
        
        @app.errorhandler(404)
        def not_found(e):
            return _json_error(404, "Endpoint not found")
        
        @app.errorhandler(405)
        def method_not_allowed(e):
            return _json_error(405, "Method not allowed")
        
        @app.errorhandler(413)
        def request_entity_too_large(e):
            return _json_error(413, "Request too large (max 1MB)")
        
        @app.errorhandler(429)
        def too_many_requests(e):
            return _json_error(429, "Too many requests")
        
        @app.errorhandler(500)
        def internal_error(e):
            import traceback
            logging.error(f"Internal Error: {e}\n{traceback.format_exc()}")
            return _json_error(500, "Internal server error")
        
        # =====================================================
        # SECURITY HEADERS (after_request)
        # =====================================================
        
        @app.after_request
        def add_security_headers(response):
            # Security headers
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['X-XSS-Protection'] = '1; mode=block'
            response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            
            # Content Security Policy
            # Swagger UI butuh izin untuk load script, style, img, dan fetch
            if request.path.startswith('/api/docs'):
                response.headers['Content-Security-Policy'] = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; "
                    "connect-src 'self'"
                )
            else:
                # API endpoints - strict CSP
                response.headers['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'"
            
            # Permissions Policy - disable browser features
            response.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=(), payment=()'
            
            # HSTS - enforce HTTPS (only when served over HTTPS)
            if request.is_secure:
                response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
            
            # Remove server header
            response.headers.pop('Server', None)
            
            return response
        
        # =====================================================
        # STRICT URL VALIDATION (before_request)
        # =====================================================
        
        @app.before_request
        def strict_url_validation():
            # Block suspicious URL patterns
            path = request.path
            
            # Reject paths with double slashes, null bytes, or traversal
            if '//' in path or '\x00' in path or '..' in path:
                logging.warning(f"Blocked suspicious path: {path}")
                return _json_error(400, "Invalid URL path")
            
            # Reject very long URLs
            if len(path) > 500:
                logging.warning(f"Blocked long URL: {len(path)} chars")
                return _json_error(414, "URL too long")
            
            # Only allow /api/v3/* and /api/docs/* paths
            if not (path.startswith('/api/v3/') or path.startswith('/api/docs')):
                return _json_error(404, "Endpoint not found")
        
    else:
        logging.debug('create_app in management mode: skipping cache, scheduler, and blueprint registration.')

    return app

