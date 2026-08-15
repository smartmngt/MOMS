# N자 백테스트 웹앱 — Cloud Run 배포용
# (키움 수집기는 여기 포함 안 됨: 윈도우 PC 전용)
FROM python:3.11-slim

WORKDIR /app

# 의존성 먼저 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 소스
COPY app.py .
COPY nja/ ./nja/
COPY templates/ ./templates/
# 수집된 15분봉 데이터를 이미지에 함께 넣는 경우 (선택):
# COPY data/ ./data/

# Cloud Run은 PORT 환경변수를 준다
ENV PORT=8080
EXPOSE 8080

CMD exec gunicorn --bind :$PORT --workers 2 --threads 4 --timeout 120 app:app
