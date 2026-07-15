#!/bin/sh
set -eu

mkdir -p /app/state /app/src/content/files /app/src/content/logs /app/src/content/ssl
python /opt/thesis/render_config.py

ln -sfn /app/state/config.toml /app/src/config.toml
ln -sfn /app/state/init /app/src/init
ln -sfn /app/state/admin_password.txt /app/src/admin_password.txt

chown -R cfms:cfms /app/state /app/src/content
exec gosu cfms "$@"
