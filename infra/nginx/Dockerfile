FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY thesis_frontend/package.json thesis_frontend/package-lock.json ./
RUN npm ci
COPY thesis_frontend/ ./
RUN npm run build

FROM nginx:stable-alpine
RUN apk add --no-cache openssl \
    && mkdir -p /etc/nginx/certs /tmp/nginx \
    && openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
       -subj "/CN=localhost" \
       -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
       -keyout /etc/nginx/certs/tls.key \
       -out /etc/nginx/certs/tls.crt \
    && chown -R nginx:nginx /etc/nginx/certs /tmp/nginx /usr/share/nginx/html
COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=frontend-build --chown=nginx:nginx /frontend/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080 8443
