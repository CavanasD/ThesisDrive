package com.thesis.transfer.security;

import com.thesis.transfer.config.TransferProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ResourceLoader;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.web.server.ServerHttpSecurity;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.jwt.JwtIssuerValidator;
import org.springframework.security.oauth2.jwt.JwtTimestampValidator;
import org.springframework.security.oauth2.jwt.NimbusReactiveJwtDecoder;
import org.springframework.security.oauth2.jwt.ReactiveJwtDecoder;
import org.springframework.security.oauth2.server.resource.authentication.BearerTokenAuthenticationToken;
import org.springframework.security.oauth2.server.resource.web.server.authentication.ServerBearerTokenAuthenticationConverter;
import org.springframework.security.web.server.SecurityWebFilterChain;
import org.springframework.security.web.server.authentication.ServerAuthenticationConverter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.reactive.CorsWebFilter;
import org.springframework.web.cors.reactive.UrlBasedCorsConfigurationSource;
import reactor.core.publisher.Mono;

import java.util.List;

@Configuration
public class SecurityConfig {

    @Bean
    ReactiveJwtDecoder jwtDecoder(
            ResourceLoader resourceLoader,
            TransferProperties properties
    ) {
        var security = properties.security();
        var publicKey = PemPublicKeyLoader.load(resourceLoader, security.publicKeyLocation());
        var decoder = NimbusReactiveJwtDecoder.withPublicKey(publicKey).build();

        var timestamp = new JwtTimestampValidator(security.clockSkew());
        var issuer = new JwtIssuerValidator(security.issuer());
        var audience = new AudienceValidator(security.audience());
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
                timestamp,
                issuer,
                audience
        ));
        return decoder;
    }

    @Bean
    SecurityWebFilterChain securityWebFilterChain(
            ServerHttpSecurity http,
            ServerAuthenticationConverter bearerTokenConverter
    ) {
        return http
                .csrf(ServerHttpSecurity.CsrfSpec::disable)
                .httpBasic(ServerHttpSecurity.HttpBasicSpec::disable)
                .formLogin(ServerHttpSecurity.FormLoginSpec::disable)
                .cors(Customizer.withDefaults())
                .authorizeExchange(exchanges -> exchanges
                        .pathMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                        .pathMatchers("/actuator/health/**", "/actuator/info", "/actuator/prometheus").permitAll()
                        .pathMatchers("/api/v1/transfers/**").authenticated()
                        .anyExchange().denyAll())
                .oauth2ResourceServer(resourceServer -> resourceServer
                        .bearerTokenConverter(bearerTokenConverter)
                        .jwt(Customizer.withDefaults()))
                .build();
    }

    @Bean
    ServerAuthenticationConverter bearerTokenConverter() {
        var headerConverter = new ServerBearerTokenAuthenticationConverter();
        return exchange -> headerConverter.convert(exchange)
                .switchIfEmpty(Mono.defer(() -> {
                    boolean isDownload = exchange.getRequest().getMethod() == HttpMethod.GET
                            && exchange.getRequest().getPath().value()
                            .matches("/api/v1/transfers/[^/]+/content");
                    if (!isDownload) {
                        return Mono.empty();
                    }
                    List<String> tickets = exchange.getRequest().getQueryParams().get("ticket");
                    if (tickets == null || tickets.size() != 1 || tickets.getFirst().isBlank()) {
                        return Mono.empty();
                    }
                    return Mono.just(new BearerTokenAuthenticationToken(tickets.getFirst()));
                }));
    }

    @Bean
    CorsWebFilter corsWebFilter(TransferProperties properties) {
        var configuration = new CorsConfiguration();
        configuration.setAllowedOrigins(properties.cors().allowedOrigins());
        configuration.setAllowedMethods(List.of("GET", "HEAD", "PUT", "OPTIONS"));
        configuration.setAllowedHeaders(List.of(
                HttpHeaders.AUTHORIZATION,
                HttpHeaders.CONTENT_LENGTH,
                HttpHeaders.CONTENT_RANGE,
                HttpHeaders.CONTENT_TYPE,
                HttpHeaders.RANGE,
                "Idempotency-Key",
                "X-Chunk-SHA256"
        ));
        configuration.setExposedHeaders(List.of(
                HttpHeaders.ACCEPT_RANGES,
                HttpHeaders.CONTENT_LENGTH,
                HttpHeaders.CONTENT_RANGE,
                HttpHeaders.ETAG,
                "Upload-Length",
                "Upload-Offset",
                "Upload-Status"
        ));
        configuration.setAllowCredentials(false);
        configuration.setMaxAge(3600L);

        var source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", configuration);
        return new CorsWebFilter(source);
    }
}
