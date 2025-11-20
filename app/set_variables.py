import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

SECRET_KEY = os.environ.get('SECRET_KEY')

FLASK_APP = os.environ.get('FLASK_APP')
FLASK_ENV = os.environ.get('FLASK_ENV')
FLASK_DEBUG = os.environ.get('FLASK_DEBUG')

ECO_APP_KEY = os.environ.get('ECO_APP_KEY')
ECO_API_KEY = os.environ.get('ECO_API_KEY')
ECO_MAC = os.environ.get('ECO_MAC')

WUNDERGROUND_URL = os.environ.get('WUNDERGROUND_URL')

API_READ_KEY = os.environ.get('API_READ_KEY')