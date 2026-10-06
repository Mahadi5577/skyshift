# SkyShift server image. Works on any Docker host; the defaults suit a Hugging Face Docker Space
# (port 7860, user id 1000, persistent storage, if any, mounted at /data). See docs/DEPLOY.md.
#
#   docker build -t skyshift .
#   docker run -p 7860:7860 skyshift          then open http://localhost:7860
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=7860 \
    SKYSHIFT_CACHE=/data/cache \
    SKYSHIFT_DATA=/data \
    SKYSHIFT_PRECACHE=1
# Trust X-Forwarded-For from the hosting proxy so rate limits see real client addresses.
# Only safe behind a proxy: on a bare host, set it to the proxy's address instead.
ENV FORWARDED_ALLOW_IPS=*

RUN useradd --create-home --uid 1000 user && mkdir /data && chown user /data
WORKDIR /app
COPY requirements.txt requirements-server.txt ./
RUN pip install -r requirements-server.txt
COPY --chown=user backend backend
COPY --chown=user web web
COPY --chown=user scripts scripts
USER user

EXPOSE 7860
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"
CMD ["sh", "-c", "exec uvicorn backend.app:app --host 0.0.0.0 --port ${PORT}"]
