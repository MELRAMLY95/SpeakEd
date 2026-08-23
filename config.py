import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'speaked.db'}")
    AI_PROVIDER = os.environ.get("AI_PROVIDER", "auto")
    # Z.AI (GLM) - Primary AI provider
    ZAI_API_KEY = os.environ.get("ZAI_API_KEY", "")
    ZAI_MODEL = os.environ.get("ZAI_MODEL", "glm-4")
    ZAI_BASE_URL = os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
    # Ollama - Local development fallback
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
    # Gemini - Fallback provider (has free tier: https://ai.google.dev/pricing)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    # OpenAI - Optional fallback
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    # Render sets RENDER=true on every service automatically, so this needs
    # no manual configuration — see https://render.com/docs/environment-variables
    IS_RENDER = os.environ.get("RENDER", "").lower() == "true"
    STORE_AUDIO = os.environ.get("STORE_AUDIO", "false").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    WARMUP_SECONDS = 60
    ROLEPLAY_SECONDS = 120
    TOPIC_TALK_SECONDS = 120
    TOPIC_FOLLOWUP_SECONDS = 180
    PICTURE_SECONDS = 300
    PREP_SECONDS = 600


class TestConfig(Config):
    TESTING = True
    DEBUG = True
    DATABASE_URL = "sqlite:///:memory:"
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    AI_PROVIDER = "rule"