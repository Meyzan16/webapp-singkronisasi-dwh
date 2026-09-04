FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps (context = repo root)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend app + agents (agents/ is imported by main.py)
COPY backend/app ./app
COPY agents      ./agents

# --timeout-keep-alive 75 (default 5): proxy Next memakai ulang koneksi keep-alive
# sementara poller FE berjeda 30-60 detik. Dengan 5 detik, soket sudah ditutup server
# saat dipakai lagi → "socket hang up" (ECONNRESET) di sisi FE. Lihat frontend/src/lib/api.ts.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "75"]
