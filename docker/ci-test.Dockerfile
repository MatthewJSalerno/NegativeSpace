# Isolated Git fixtures for CI routing/gate tests; not an application image.
FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir PyYAML==6.0.2
WORKDIR /app
ENTRYPOINT ["python3"]
