package com.thesis.transfer.security;

import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.source.ImmutableJWKSet;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.JwtIssuerValidator;
import org.springframework.security.oauth2.jwt.JwtTimestampValidator;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.security.oauth2.jwt.NimbusReactiveJwtDecoder;

import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.time.Instant;
import java.time.Duration;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

class TransferTicketServiceTest {
    private RSAPublicKey publicKey;
    private RSAPrivateKey privateKey;

    @BeforeEach
    void generateKey() throws Exception {
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        KeyPair keyPair = generator.generateKeyPair();
        publicKey = (RSAPublicKey) keyPair.getPublic();
        privateKey = (RSAPrivateKey) keyPair.getPrivate();
    }

    @Test
    void verifiesRs256SignatureAndParsesTicketClaims() {
        String token = signedToken("task-1", privateKey, publicKey);
        var decoder = coreContractDecoder(publicKey);
        var jwt = decoder.decode(token).block();

        TransferTicket ticket = new TransferTicketService().require(
                jwt,
                "task-1",
                TransferOperation.UPLOAD
        );

        assertEquals("task-1", ticket.taskId());
        assertEquals("alice", ticket.username());
        assertEquals("objects/a.bin", ticket.objectKey());
        assertEquals(42, ticket.maxSize());
        assertNull(ticket.expectedSha256());
    }

    @Test
    void rejectsTokenSignedByAnotherPrivateKey() throws Exception {
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA");
        generator.initialize(2048);
        KeyPair other = generator.generateKeyPair();
        String token = signedToken(
                "task-1",
                (RSAPrivateKey) other.getPrivate(),
                (RSAPublicKey) other.getPublic()
        );
        var decoder = coreContractDecoder(publicKey);

        assertThrows(RuntimeException.class, () -> decoder.decode(token).block());
    }

    @Test
    void rejectsWrongCoreIssuerOrAudience() {
        String token = signedToken(
                "task-1",
                privateKey,
                publicKey,
                "another-service"
        );

        assertThrows(
                RuntimeException.class,
                () -> coreContractDecoder(publicKey).decode(token).block()
        );
    }

    private static String signedToken(
            String taskId,
            RSAPrivateKey privateKey,
            RSAPublicKey publicKey
    ) {
        return signedToken(
                taskId,
                privateKey,
                publicKey,
                "transfer-data-plane"
        );
    }

    private static String signedToken(
            String taskId,
            RSAPrivateKey privateKey,
            RSAPublicKey publicKey,
            String audience
    ) {
        var rsaKey = new RSAKey.Builder(publicKey)
                .privateKey(privateKey)
                .keyID("test-key")
                .build();
        var encoder = new NimbusJwtEncoder(new ImmutableJWKSet<>(new JWKSet(rsaKey)));
        Instant now = Instant.now();
        var claims = JwtClaimsSet.builder()
                .issuer("thesis-drive-core")
                .audience(List.of(audience))
                .issuedAt(now)
                .expiresAt(now.plusSeconds(300))
                .id("random-ticket-id")
                .subject("alice")
                .claim("task_id", taskId)
                .claim("username", "alice")
                .claim("operation", "upload")
                .claim("object_key", "objects/a.bin")
                .claim("max_size", 42L)
                .build();
        var parameters = JwtEncoderParameters.from(
                org.springframework.security.oauth2.jwt.JwsHeader
                        .with(SignatureAlgorithm.RS256)
                        .keyId("test-key")
                        .build(),
                claims
        );
        return encoder.encode(parameters).getTokenValue();
    }

    private static NimbusReactiveJwtDecoder coreContractDecoder(RSAPublicKey key) {
        var decoder = NimbusReactiveJwtDecoder.withPublicKey(key).build();
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
                new JwtTimestampValidator(Duration.ofSeconds(30)),
                new JwtIssuerValidator("thesis-drive-core"),
                new AudienceValidator("transfer-data-plane")
        ));
        return decoder;
    }
}
