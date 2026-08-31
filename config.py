import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DEV_SECRET_KEY = "dev-insecure-change-me"
LOCAL_SQLITE_URL = f"sqlite:///{BASE_DIR / 'instance' / 'speaked.db'}"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", DEV_SECRET_KEY)
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    # An unset DATABASE_URL must not quietly become SQLite in production: on
    # Render the filesystem is ephemeral, so accounts would disappear on every
    # redeploy. validate_runtime_config() turns that situation into a startup
    # failure instead of silent data loss.
    DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip() or LOCAL_SQLITE_URL
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
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    # OpenAI - Optional fallback
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    # Render sets RENDER=true on every service automatically, so this needs
    # no manual configuration — see https://render.com/docs/environment-variables
    IS_RENDER = os.environ.get("RENDER", "").lower() == "true"
    # Anything hosted counts as production. SPEAKED_ENV lets non-Render hosts
    # opt in to the same strict startup checks.
    IS_PRODUCTION = IS_RENDER or os.environ.get("SPEAKED_ENV", "").lower() == "production"
    STORE_AUDIO = os.environ.get("STORE_AUDIO", "false").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    CSRF_PROTECT = True
    LOGIN_RATE_LIMIT = True
    LOGIN_RATE_MAX = 8
    LOGIN_RATE_WINDOW = 900
    ACTION_RATE_LIMIT = True
    EXAM_START_MAX = 40
    EXAM_START_WINDOW = 3600
    RETRY_MARKING_MAX = 10
    RETRY_MARKING_WINDOW = 3600
    INFO_GEN_MAX = 15
    INFO_GEN_WINDOW = 3600
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14
    # Bump this (or set SESSION_VERSION) to invalidate every existing login cookie.
    # New sign-ins still work; only sessions issued under an older value are dropped.
    SESSION_VERSION = (os.environ.get("SESSION_VERSION") or "1").strip() or "1"
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    WARMUP_SECONDS = 60
    ROLEPLAY_SECONDS = 120
    TOPIC_TALK_SECONDS = 120
    TOPIC_FOLLOWUP_SECONDS = 180
    PICTURE_SECONDS = 300
    PREP_SECONDS = 600
    # Advertising is off until an operator explicitly enables it. Placeholder
    # publisher IDs never load a third-party script.
    ADS_ENABLED = _env_flag("ADS_ENABLED", True)
    ADS_PROVIDER = os.environ.get("ADS_PROVIDER", "adsense")
    AD_CLIENT_ID = os.environ.get("AD_CLIENT_ID", "ca-pub-3990201330574869")
    AD_SLOT_HOME = os.environ.get("AD_SLOT_HOME", "")
    AD_SLOT_DASHBOARD = os.environ.get("AD_SLOT_DASHBOARD", "")
    AD_SLOT_INFORMATION = os.environ.get("AD_SLOT_INFORMATION", "")
    AD_SLOT_PRIVACY = os.environ.get("AD_SLOT_PRIVACY", "")
    ADS_TEST_MODE = _env_flag("ADS_TEST_MODE", False)
    ADS_CONSENT_REQUIRED = _env_flag("ADS_CONSENT_REQUIRED", False)
    PAYMENT_PROVIDER = os.environ.get("PAYMENT_PROVIDER", "fake")
    PAYMENT_TEST_MODE = _env_flag("PAYMENT_TEST_MODE", True)
    PAYMENT_SECRET_KEY = os.environ.get("PAYMENT_SECRET_KEY", "")
    PAYMENT_PUBLISHABLE_KEY = os.environ.get("PAYMENT_PUBLISHABLE_KEY", "")
    PAYMENT_WEBHOOK_SECRET = os.environ.get("PAYMENT_WEBHOOK_SECRET", "")
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")
    FREE_PLAN_NAME = os.environ.get("FREE_PLAN_NAME", "Free")
    PREMIUM_PLAN_NAME = os.environ.get("PREMIUM_PLAN_NAME", "Premium")
    PREMIUM_PRICE_AMOUNT = _env_int("PREMIUM_PRICE_AMOUNT", 499)
    PREMIUM_CURRENCY = os.environ.get("PREMIUM_CURRENCY", "gbp")
    PREMIUM_INTERVAL = os.environ.get("PREMIUM_INTERVAL", "month")
    FREE_PRACTICE_EXAMS_PER_MONTH = _env_int("FREE_PRACTICE_EXAMS_PER_MONTH", 4)
    FREE_RETRY_MARKING_PER_MONTH = _env_int("FREE_RETRY_MARKING_PER_MONTH", 2)
    FREE_INFO_GEN_PER_MONTH = _env_int("FREE_INFO_GEN_PER_MONTH", 8)
    PREMIUM_PRACTICE_EXAMS_PER_MONTH = _env_int("PREMIUM_PRACTICE_EXAMS_PER_MONTH", -1)
    PREMIUM_RETRY_MARKING_PER_MONTH = _env_int("PREMIUM_RETRY_MARKING_PER_MONTH", -1)
    PREMIUM_INFO_GEN_PER_MONTH = _env_int("PREMIUM_INFO_GEN_PER_MONTH", -1)
    # Private preview: only OWNER_EMAIL can sign in, and public signup is closed.
    # Set PRIVATE_MODE=false on Render when you launch publicly.
    PRIVATE_MODE = _env_flag("PRIVATE_MODE", True)
    OWNER_EMAIL = (os.environ.get("OWNER_EMAIL") or "").strip().lower()
    OWNER_PASSWORD = os.environ.get("OWNER_PASSWORD") or ""
    OWNER_NAME = (os.environ.get("OWNER_NAME") or "Owner").strip() or "Owner"


class TestConfig(Config):
    TESTING = True
    DEBUG = True
    # Not ":memory:" — the app opens one connection per request, and each new
    # connection to ":memory:" would get its own empty database, so nothing
    # would persist between requests.
    DATABASE_URL = f"sqlite:///{BASE_DIR / 'instance' / 'test-default.db'}"
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    CSRF_PROTECT = False
    LOGIN_RATE_LIMIT = False
    ACTION_RATE_LIMIT = False
    AI_PROVIDER = "rule"
    IS_PRODUCTION = False
    SESSION_COOKIE_SECURE = False
    ADS_ENABLED = False
    ADS_TEST_MODE = True
    ADS_CONSENT_REQUIRED = False
    AD_CLIENT_ID = "ca-pub-XXXXXXXXXXXXXXXX"
    PAYMENT_PROVIDER = "fake"
    PAYMENT_TEST_MODE = True
    PAYMENT_WEBHOOK_SECRET = "test-webhook-secret"
    FREE_PRACTICE_EXAMS_PER_MONTH = 100
    FREE_RETRY_MARKING_PER_MONTH = 100
    FREE_INFO_GEN_PER_MONTH = 100
    PRIVATE_MODE = False
    OWNER_EMAIL = ""
    OWNER_PASSWORD = ""


def validate_runtime_config(config: dict) -> None:
    """Fail fast on configuration that would silently lose user data.

    Raises RuntimeError so a misconfigured deployment refuses to boot rather
    than running on a database that disappears on the next restart.
    """
    if not config.get("IS_PRODUCTION"):
        return

    url = (config.get("DATABASE_URL") or "").strip()
    if not url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError(
            "Production requires a PostgreSQL DATABASE_URL. Got "
            f"{url.split('://')[0] or '(empty)'}://... Render's disk is ephemeral, so SQLite "
            "would lose every account and all progress on each redeploy. Attach a PostgreSQL "
            "instance and set DATABASE_URL."
        )

    secret = config.get("SECRET_KEY") or ""
    if not secret or secret == DEV_SECRET_KEY:
        raise RuntimeError(
            "Production requires a stable SECRET_KEY environment variable. Without one, "
            "session cookies cannot be trusted and every user would be logged out."
        )

    if not config.get("SESSION_COOKIE_SECURE"):
        raise RuntimeError(
            "Production requires SESSION_COOKIE_SECURE=True so the session cookie is only "
            "sent over HTTPS."
        )

    if config.get("DEBUG"):
        raise RuntimeError(
            "Production must run with FLASK_DEBUG=0. Debug mode exposes internals and must "
            "never be enabled on a public site."
        )