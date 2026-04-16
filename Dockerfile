# Multi-stage Dockerfile for OESIS runtime services.
# Build targets: ingest, parcel, shared-map
#
# Usage:
#   docker compose build
#   docker compose up -d
#
# Or individually:
#   docker build --target ingest -t oesis-ingest .
#   docker build --target parcel -t oesis-parcel .
#   docker build --target shared-map -t oesis-shared-map .

FROM python:3.11-slim AS base

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir . && \
    rm -rf /root/.cache/pip

# Create data directory for JSON stores
RUN mkdir -p /data

# ---- Ingest API ----
FROM base AS ingest
EXPOSE 8787
ENV OESIS_RUNTIME_LANE=v1.0
CMD ["python3", "-m", "oesis.ingest.serve_ingest_api", "--host", "0.0.0.0", "--port", "8787"]

# ---- Parcel Platform API ----
FROM base AS parcel
EXPOSE 8789
ENV OESIS_RUNTIME_LANE=v1.0
CMD ["python3", "-m", "oesis.parcel_platform.serve_parcel_api", "--host", "0.0.0.0", "--port", "8789", \
     "--sharing-store", "/data/sharing-store.json", \
     "--consent-store", "/data/consent-store.json", \
     "--rights-store", "/data/rights-store.json", \
     "--access-log", "/data/access-log.json", \
     "--export-dir", "/data/exports"]

# ---- Shared Map API ----
FROM base AS shared-map
EXPOSE 8791
ENV OESIS_RUNTIME_LANE=v1.0
CMD ["python3", "-m", "oesis.shared_map.serve_shared_map_api", "--host", "0.0.0.0", "--port", "8791"]
