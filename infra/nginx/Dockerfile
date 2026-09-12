FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS frontend-build
WORKDIR /frontend
COPY thesis_frontend/package.json thesis_frontend/package-lock.json ./
RUN npm ci
COPY thesis_frontend/ ./
RUN npm run build

FROM nginx:stable-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46
ARG TLS_SAN=DNS:localhost,IP:127.0.0.1
RUN apk add --no-cache openssl \
    && mkdir -p /etc/nginx/certs /tmp/nginx \
    && openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
       -subj "/CN=localhost" \
       -addext "subjectAltName=${TLS_SAN}" \
       -keyout /etc/nginx/certs/tls.key \
       -out /etc/nginx/certs/tls.crt \
    && chown -R nginx:nginx /etc/nginx/certs /tmp/nginx /usr/share/nginx/html
COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=frontend-build --chown=nginx:nginx /frontend/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080 8443
