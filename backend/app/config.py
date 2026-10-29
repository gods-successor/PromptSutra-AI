"""Environment configuration for PromptSutra AI."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')

class Settings:
    environment = os.getenv('ENVIRONMENT', 'development').lower()
    app_secret = os.getenv('APP_SECRET', '')
    database_url = os.getenv('DATABASE_URL', f'sqlite:///{ROOT / "promptsutra.db"}')
    gemini_api_key = os.getenv('GEMINI_API_KEY', '')
    gemini_model = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
    smtp_host = os.getenv('SMTP_HOST', '')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', '')
    smtp_password = os.getenv('SMTP_PASSWORD', '')
    email_from = os.getenv('EMAIL_FROM', '')
    secure_cookies = os.getenv('SECURE_COOKIES', 'false').lower() == 'true'
    session_days = 7
    firebase_service_account = os.getenv('FIREBASE_SERVICE_ACCOUNT', '')
    firebase_web_config = {
        'apiKey': os.getenv('FIREBASE_API_KEY', ''),
        'authDomain': os.getenv('FIREBASE_AUTH_DOMAIN', ''),
        'projectId': os.getenv('FIREBASE_PROJECT_ID', ''),
        'appId': os.getenv('FIREBASE_APP_ID', ''),
    }

settings = Settings()
