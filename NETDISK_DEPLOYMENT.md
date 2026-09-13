# `thesis.n1n3bird.top` test deployment

This profile deploys the Thesis Drive stack inside `netdisk-server`. Caddy and
FRPC also run in that LXC. The Aliyun FRPS host remains an unchanged public
router and stores no application data.

## Local listeners

- Docker/Nginx HTTP: `127.0.0.1:8080`
- Docker/Nginx HTTPS: `127.0.0.1:8443`
- Caddy HTTP/HTTPS: `127.0.0.1:80` and `127.0.0.1:443`
- FRPC forwards only `thesis.n1n3bird.top` to those Caddy listeners.

The Docker daemon data root is `/srv/netdisk-data/docker`, so MySQL, Redis,
MinIO, application state, attachment blobs, certificates, and image layers all
remain below `/srv/netdisk-data`. On the current host this is a directory on the
40 GiB root filesystem and is suitable only for the requested 200 MiB-per-user
test. Move `/srv/netdisk-data` to a dedicated PVE mount and establish backups
before storing formal data.

The target network blocks Docker Hub's registry and authentication endpoints.
Docker is therefore configured with `https://docker.m.daocloud.io` as a pull
cache. Image tags remain fixed in Compose; MinIO images are pulled directly from
their official Quay repository. Remove the `registry-mirrors` entry when direct
Docker Hub access becomes available.

## Secrets

The deployment `.env` is generated directly on the LXC with mode `0600`.
`/etc/frp/aliserver_token` must be copied from an already authorized node and
also kept at mode `0600`. Neither file belongs in Git, chat, terminal output, or
deployment logs.

## Public routes

- `/` — Thesis Drive
- `/security` — reporter submission and personal report status
- `/admin/src` — sysop-only review and workflow orchestration

The drive navigation intentionally contains no link to the SRC portal.

## Rollback

Stop and disable `frpc`, `caddy`, and `thesis-drive` on `netdisk-server`, then
remove only the `thesis.n1n3bird.top` A record. Do not restart or reconfigure
the shared FRPS service.
