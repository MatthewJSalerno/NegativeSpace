# Test-only image. Keep the Python package and bundled browser versions matched.
# Each driver still starts a fresh container and an isolated generated catalog.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
RUN pip install --no-cache-dir --root-user-action=ignore playwright==1.63.0
