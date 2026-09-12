FROM eclipse-temurin:21-jdk-alpine@sha256:6ea5548706b60ac0a602eaf48af74792cbab012d90e811ca8db6184b16b5c3d6 AS build
WORKDIR /workspace

COPY gradle gradle
COPY gradlew settings.gradle build.gradle ./
RUN chmod +x gradlew
COPY src src
RUN ./gradlew bootJar --no-daemon

FROM eclipse-temurin:21-jre-alpine@sha256:974b08960c5d96694c780e65b2d5705268ab1e1ca1a0dd0caf4ba6c3fe34d699
RUN apk add --no-cache curl \
    && addgroup -S transfer && adduser -S transfer -G transfer \
    && mkdir -p /app /var/lib/transfer-data-plane/uploads \
    && chown -R transfer:transfer /app /var/lib/transfer-data-plane
WORKDIR /app
COPY --from=build --chown=transfer:transfer /workspace/build/libs/*.jar app.jar

USER transfer
EXPOSE 8082
ENV TRANSFER_TEMP_DIRECTORY=/var/lib/transfer-data-plane/uploads
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent --show-error http://127.0.0.1:8082/actuator/health >/dev/null || exit 1
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75.0", "-jar", "/app/app.jar"]
