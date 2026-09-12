FROM python:3.14.3-slim-bookworm@sha256:f21c0d5a44c56805654c15abccc1b2fd576c8d93aca0a3f74b4aba2dc92510e2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 cfms \
    && useradd --uid 10001 --gid cfms --create-home cfms

WORKDIR /app
COPY cfms_on_websocket-master/pyproject.toml cfms_on_websocket-master/README.md cfms_on_websocket-master/uv.lock ./
COPY cfms_on_websocket-master/src ./src
RUN pip install "uv==0.12.5" \
    && uv sync --locked --no-dev --extra cluster --extra mysql --extra ext_oidc_sso
ENV PATH="/app/.venv/bin:$PATH"

COPY infra/core/render_config.py /opt/thesis/render_config.py
COPY infra/core/entrypoint.sh /usr/local/bin/thesis-core-entrypoint
RUN chmod 0755 /usr/local/bin/thesis-core-entrypoint \
    && mkdir -p /app/state /app/src/content/files /app/src/content/logs /app/src/content/ssl \
    && chown -R cfms:cfms /app /opt/thesis

WORKDIR /app/src
EXPOSE 5104
ENTRYPOINT ["thesis-core-entrypoint"]
CMD ["python", "main.py"]
