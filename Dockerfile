# N자 백테스트 웹앱 — Cloud Run 배포용
# (키움 수집기는 여기 포함 안 됨: 윈도우 PC 전용)
FROM python:3.11-slim

WORKDIR /app

# 의존성 먼저 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── 캐시 무효화 (이 숫자를 바꾸면 아래 COPY가 캐시를 안 씀) ──
ARG CACHE_BUST=20260816_2
RUN echo "cache bust: $CACHE_BUST"

# 앱 소스
COPY app.py .
COPY nja/ ./nja/
COPY templates/ ./templates/

# Cloud Run은 PORT 환경변수를 준다
ENV PORT=8080
EXPOSE 8080

CMD exec gunicorn --bind :$PORT --workers 2 --threads 4 --timeout 120 app:app
