import os
import sys

# Add project to path
sys.path.insert(0, os.path.dirname(__file__))

# Set Django settings
os.environ['DJANGO_SETTINGS_MODULE'] = 'mylinebot.settings'

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Import Django WSGI application
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
