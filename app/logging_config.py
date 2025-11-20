import logging
import logging.handlers
import os


def configure_logging(app=None, level=logging.INFO):
    logger = logging.getLogger()
    if getattr(logger, '_configured_by_app', False):
        logger.setLevel(level)
        return logger

    logger.setLevel(level)

    ch = logging.StreamHandler()
    ch.setLevel(level)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs'))
    try:
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, 'app.log'), maxBytes=5 * 1024 * 1024, backupCount=3
        )
        fh.setLevel(level)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        logger.warning('Tidak dapat menginisialisasi file log, menggunakan console saja.')

    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    setattr(logger, '_configured_by_app', True)
    return logger
