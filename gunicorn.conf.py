import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
timeout = 180
graceful_timeout = 30
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
