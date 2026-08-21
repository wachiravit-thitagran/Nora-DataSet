# Nora dataset web service.
#
# The image carries only the application and the catalogue files — never the
# dataset bundles themselves. Bundles live on a volume mounted at DATA_DIR,
# so a code deploy stays small and fast regardless of how large the dataset
# grows.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY scripts ./scripts

# Run unprivileged. The data volume is mounted read-only, so this user needs
# write access only to the database directory.
RUN useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin nora \
    && chown -R nora:nora /srv/app
USER nora

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Four workers because this process also streams the bundle bytes. Downloads
# run on the event loop, so slow clients do not block it, but concurrent
# transfers do compete for CPU with the page and API requests.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--workers", "4"]
