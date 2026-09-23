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
    && openssl req -x509 -nodes -newkey rsa:3072 -days 3650 -sha256 \
       -subj "/CN=Thesis Drive Lab Root CA" \
       -addext "basicConstraints=critical,CA:TRUE" \
       -addext "keyUsage=critical,keyCertSign,cRLSign" \
       -keyout /etc/nginx/certs/ca.key \
       -out /etc/nginx/certs/ca.crt \
    && openssl req -nodes -newkey rsa:2048 -sha256 \
       -subj "/CN=localhost" \
       -keyout /etc/nginx/certs/tls.key \
       -out /etc/nginx/certs/tls.csr \
    && { echo "subjectAltName=$TLS_SAN"; \
         echo "basicConstraints=CA:FALSE"; \
         echo "keyUsage=critical,digitalSignature,keyEncipherment"; \
         echo "extendedKeyUsage=serverAuth"; } > /etc/nginx/certs/tls.ext \
    && openssl x509 -req -in /etc/nginx/certs/tls.csr -days 825 -sha256 \
       -CA /etc/nginx/certs/ca.crt -CAkey /etc/nginx/certs/ca.key -CAcreateserial \
       -extfile /etc/nginx/certs/tls.ext \
       -out /etc/nginx/certs/tls.crt \
    && rm -f /etc/nginx/certs/tls.csr /etc/nginx/certs/ca.key /etc/nginx/certs/tls.ext /etc/nginx/certs/ca.srl \
    && cat /etc/nginx/certs/tls.crt /etc/nginx/certs/ca.crt > /etc/nginx/certs/chain.crt \
    && chown -R nginx:nginx /etc/nginx/certs /tmp/nginx /usr/share/nginx/html
COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=frontend-build --chown=nginx:nginx /frontend/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080 8443
