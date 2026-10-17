FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    PRIVATE_MODE=false \
    USAGE_LIMITS_ENABLED=false \
    PICTURE_SOURCE=getty \
    AI_PROVIDER=auto

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p instance && chmod +x start.sh

EXPOSE 7860
CMD ["./start.sh"]
