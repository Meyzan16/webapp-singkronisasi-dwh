FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Same deps as backend (context = repo root)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend app (models, database, services — imported by agents)
COPY backend/app ./app
# Agent code
COPY agents      ./agents

CMD ["python", "-m", "agents.main"]
