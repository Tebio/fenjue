# FenJue Engine — Docker Image
# ==============================

FROM python:3.11-slim

LABEL org.opencontainers.image.title="FenJue Engine"
LABEL org.opencontainers.image.description="焚诀 — 认知差驱动的产业投资研究中台"
LABEL org.opencontainers.image.version="1.0.0"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Data & config volumes expected at runtime:
#   /app/research/data/scores   → score snapshot storage
#   /app/config                 → YAML configuration

EXPOSE 8001

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8001"]
