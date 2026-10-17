#!/bin/sh
set -e
mkdir -p instance
if [ ! -f instance/secret_key ]; then
  python -c "import secrets; open('instance/secret_key','w').write(secrets.token_urlsafe(48))"
fi
export SECRET_KEY="${SECRET_KEY:-$(cat instance/secret_key)}"
export PRIVATE_MODE="${PRIVATE_MODE:-false}"
export USAGE_LIMITS_ENABLED="${USAGE_LIMITS_ENABLED:-false}"
exec gunicorn app:app --bind "0.0.0.0:${PORT:-7860}" --timeout 180 --workers 1 --threads 4
