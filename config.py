import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY') or 'change-me-in-prod'
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

    # Azure Document Intelligence
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = os.environ.get('AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT')

    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT = os.environ.get('AZURE_OPENAI_ENDPOINT')
    AZURE_OPENAI_API_VERSION = os.environ.get('AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
    AZURE_OPENAI_CHAT_DEPLOYMENT = os.environ.get('AZURE_OPENAI_CHAT_DEPLOYMENT')
    AZURE_OPENAI_MAX_TOKENS = int(os.environ.get('AZURE_OPENAI_MAX_TOKENS', '1500'))
    AZURE_OPENAI_TEMPERATURE = float(os.environ.get('AZURE_OPENAI_TEMPERATURE', '0.7'))

    # SQLite (on-prem simulation)
    SQLITE_DB_PATH = os.environ.get('SQLITE_DB_PATH', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'banking.db'))

    MAX_CHAT_HISTORY = int(os.environ.get('MAX_CHAT_HISTORY', '50'))
    CHAT_SESSION_TIMEOUT = int(os.environ.get('CHAT_SESSION_TIMEOUT', '3600'))
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

    @classmethod
    def validate_config(cls):
        missing = []
        required = [
            'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT',
            'AZURE_OPENAI_ENDPOINT',
            'AZURE_OPENAI_CHAT_DEPLOYMENT',
        ]
        for key in required:
            if not os.environ.get(key):
                missing.append(key)
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        return True