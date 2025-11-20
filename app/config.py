import os
from .secrets import get_secret
from dotenv import load_dotenv
import logging
from .set_variables import *


load_dotenv()

_UNDER_PYTEST = bool(os.environ.get('PYTEST_CURRENT_TEST'))

DEMO_MODE = os.environ.get('DEMO_MODE', '').lower() in ('1', 'true', 'yes')
if not DEMO_MODE:
    no_keys = not (WUNDERGROUND_URL or ECO_APP_KEY or ECO_API_KEY or ECO_MAC)
    DEMO_MODE = (no_keys and not _UNDER_PYTEST)

API_READ_KEY = get_secret('API_READ_KEY') or os.environ.get('API_READ_KEY')

CACHE_TYPE = os.environ.get('CACHE_TYPE', 'simple')
REDIS_URL = os.environ.get('REDIS_URL')

__all__ = [
    'WUNDERGROUND_URL', 'ECO_APP_KEY', 'ECO_API_KEY', 'ECO_MAC', 'DATABASE_URL',
    'DEMO_MODE', 'API_READ_KEY', 'CACHE_TYPE', 'REDIS_URL'
]
