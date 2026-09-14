#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "bootstrap.sh must run as root" >&2
    exit 1
fi

architecture="$(dpkg --print-architecture)"
if [ "$architecture" != "amd64" ]; then
    echo "This deployment bundle currently expects amd64, got: $architecture" >&2
    exit 1
fi

apt-get -o Acquire::ForceIPv4=true update
DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::ForceIPv4=true install -y \
    apt-transport-https ca-certificates curl debian-archive-keyring \
    debian-keyring gnupg openssl

install -m 0755 -d /etc/apt/keyrings
if [ ! -s /etc/apt/keyrings/docker.asc ]; then
    curl -4 --retry 5 --retry-all-errors --connect-timeout 15 -fsSL \
        https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc
fi
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $architecture
Signed-By: /etc/apt/keyrings/docker.asc
EOF

if [ ! -s /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]; then
    curl -4 --retry 5 --retry-all-errors --connect-timeout 15 -1sLf \
        https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
fi
if [ ! -s /etc/apt/sources.list.d/caddy-stable.list ]; then
    curl -4 --retry 5 --retry-all-errors --connect-timeout 15 -1sLf \
        https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        -o /etc/apt/sources.list.d/caddy-stable.list
fi
chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
chmod o+r /etc/apt/sources.list.d/caddy-stable.list

apt-get -o Acquire::ForceIPv4=true update
DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::ForceIPv4=true install -y \
    caddy docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
    docker-compose-plugin

install -m 0750 -d /srv/netdisk-data /srv/netdisk-data/docker
if [ -e /etc/docker/daemon.json ]; then
    echo "/etc/docker/daemon.json already exists; refusing to overwrite it" >&2
    exit 1
fi
cat > /etc/docker/daemon.json <<'EOF'
{
  "data-root": "/srv/netdisk-data/docker",
  "registry-mirrors": [
    "https://docker.m.daocloud.io"
  ],
  "log-driver": "local",
  "log-opts": {
    "max-size": "20m",
    "max-file": "3"
  }
}
EOF
systemctl enable docker
systemctl restart docker

frp_version="0.70.1"
frp_sha256="333da23d1b9009d7c01638e9ba38cf4600f7d37d393f854e96ee1396adefa9a6"
frp_archive="frp_${frp_version}_linux_amd64.tar.gz"
frp_url="https://github.com/fatedier/frp/releases/download/v${frp_version}/${frp_archive}"
frp_temp="$(mktemp -d)"
curl -4 --retry 5 --retry-all-errors --connect-timeout 15 -fsSL \
    "$frp_url" -o "$frp_temp/$frp_archive"
printf '%s  %s\n' "$frp_sha256" "$frp_temp/$frp_archive" | sha256sum -c -
tar -xzf "$frp_temp/$frp_archive" -C "$frp_temp"
install -m 0755 "$frp_temp/frp_${frp_version}_linux_amd64/frpc" /usr/local/bin/frpc
rm -r -- "$frp_temp"

install -m 0750 -d /etc/frp /opt/thesis-drive

docker --version
docker compose version
caddy version
frpc --version
