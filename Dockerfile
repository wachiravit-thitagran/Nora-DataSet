# Nora dataset web service.
#
# The image carries the application, the catalogue files, and the dataset
# bundles under data/bundles/. One artefact holds code and data together, so a
# deployed image is reproducible from its tag alone and there is no separate
# upload step that can leave the two out of step.
#
# The cost is size: roughly 77 MB of zips today, re-shipped on every build even
# when only code changed. If the dataset outgrows that, move the bundles back
# out to a mounted volume and set DATA_DIR to it — the application reads
# DATA_DIR either way and needs no change.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY docker-entrypoint.sh ./

# Last, and on its own layer: the bundles are the largest and most frequently
# replaced content, so everything above stays cached when only data changes.
COPY data ./data

# Run unprivileged. The bundles are baked in and only ever read, so this user
# needs write access only to the database directory.
#
# /var/lib/nora has to exist here, owned by nora, even though a volume is
# mounted over it at run time. Docker seeds a new named volume from whatever
# is at the mount point in the image, ownership included; if the path is
# missing it creates the volume owned by root instead, and uid 10001 then
# cannot create the database file inside it. The failure surfaces as a bare
# "sqlite3.OperationalError: unable to open database file".
RUN useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin nora \
    && mkdir -p /var/lib/nora \
    && chmod +x /srv/app/docker-entrypoint.sh \
    && chown -R nora:nora /srv/app /var/lib/nora
USER nora

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Four workers because this process also streams the bundle bytes. Downloads
# run on the event loop, so slow clients do not block it, but concurrent
# transfers do compete for CPU with the page and API requests.
# The entrypoint creates the schema in a single process before the workers
# start; CMD stays a plain uvicorn invocation so it can still be overridden.
ENTRYPOINT ["/srv/app/docker-entrypoint.sh"]

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--workers", "4"]
