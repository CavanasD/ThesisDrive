#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "generate-env.sh must run as root" >&2
    exit 1
fi

target="/opt/thesis-drive/.env"
if [ -e "$target" ]; then
    echo "$target already exists; refusing to replace deployment secrets" >&2
    exit 1
fi

umask 077
mysql_root_password="$(openssl rand -hex 32)"
mysql_password="$(openssl rand -hex 32)"
redis_password="$(openssl rand -hex 32)"
minio_password="$(openssl rand -hex 32)"
carapace_token="$(openssl rand -hex 32)"
grafana_password="$(openssl rand -hex 32)"

cat > "$target" <<EOF
BIND_ADDRESS=127.0.0.1
HTTP_PORT=8080
HTTPS_PORT=8443
TLS_SAN=DNS:localhost,IP:127.0.0.1,DNS:thesis.n1n3bird.top
MYSQL_ROOT_PASSWORD=$mysql_root_password
MYSQL_PASSWORD=$mysql_password
REDIS_PASSWORD=$redis_password
MINIO_ROOT_USER=thesis-minio
MINIO_ROOT_PASSWORD=$minio_password
CARAPACE_ADMIN_TOKEN=$carapace_token
GRAFANA_ADMIN_PASSWORD=$grafana_password
GRAFANA_ROOT_URL=https://thesis.n1n3bird.top/grafana/
PUBLIC_ORIGINS=https://thesis.n1n3bird.top
LAB_MODE=false
CFMS_VULN_SQLI_ENABLED=false
CFMS_VULN_RCE_ENABLED=false
CFMS_VULN_AUTH_BYPASS_ENABLED=false
CFMS_VULN_PATH_TRAVERSAL_ENABLED=false
CFMS_VULN_IDOR_ENABLED=false
VULN_SSRF_ENABLED=false
VULN_JWT_ALG_NONE_ENABLED=false
VULN_CORS_ENABLED=false
VULN_LOG4SHELL_ENABLED=false
WAF_SQLI_ENABLED=true
WAF_XSS_ENABLED=true
WAF_PATH_TRAVERSAL_ENABLED=true
WAF_CMD_INJECTION_ENABLED=true
WAF_FILE_TYPE_ENABLED=true
EOF
chmod 0600 "$target"
