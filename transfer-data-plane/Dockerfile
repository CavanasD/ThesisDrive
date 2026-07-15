FROM eclipse-temurin:21-jdk-alpine AS build
WORKDIR /workspace

COPY gradle gradle
COPY gradlew settings.gradle build.gradle ./
RUN chmod +x gradlew
COPY src src
RUN ./gradlew bootJar --no-daemon

FROM eclipse-temurin:21-jre-alpine
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
