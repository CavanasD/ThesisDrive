FROM python:3.14.3-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 cfms \
    && useradd --uid 10001 --gid cfms --create-home cfms

WORKDIR /app
COPY cfms_on_websocket-master/pyproject.toml cfms_on_websocket-master/README.md ./
COPY cfms_on_websocket-master/src ./src
RUN pip install ".[cluster,mysql,ext_oidc_sso]"

COPY infra/core/render_config.py /opt/thesis/render_config.py
COPY infra/core/entrypoint.sh /usr/local/bin/thesis-core-entrypoint
RUN chmod 0755 /usr/local/bin/thesis-core-entrypoint \
    && mkdir -p /app/state /app/src/content/files /app/src/content/logs /app/src/content/ssl \
    && chown -R cfms:cfms /app /opt/thesis

WORKDIR /app/src
EXPOSE 5104
ENTRYPOINT ["thesis-core-entrypoint"]
CMD ["python", "main.py"]
