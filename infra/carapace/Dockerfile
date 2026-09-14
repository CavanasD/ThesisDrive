FROM eclipse-temurin:21-jdk-jammy@sha256:ce5767b7222312d42395f5bab033cd91f09e44032a2f21bdfd7b5b912dbe1e77 AS build
WORKDIR /workspace
COPY carapace/gradle ./gradle
COPY carapace/gradlew carapace/build.gradle carapace/settings.gradle ./
RUN chmod +x gradlew
COPY carapace/src ./src
RUN ./gradlew --no-daemon clean bootJar

FROM eclipse-temurin:21-jre-jammy@sha256:eebd356ad7358b7094758e5787a6726f332917cfd56feab6457c56dab895cdbf
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 carapace \
    && useradd --uid 10001 --gid carapace --create-home carapace
WORKDIR /app
COPY --from=build /workspace/build/libs/*.jar /app/carapace.jar
RUN mkdir -p /app/waf-logs && chown -R carapace:carapace /app
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/carapace.jar"]
