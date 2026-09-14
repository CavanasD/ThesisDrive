package com.thesis.transfer.security;

import org.springframework.core.io.ResourceLoader;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyFactory;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;

public final class PemPublicKeyLoader {
    private PemPublicKeyLoader() {}

    public static RSAPublicKey load(ResourceLoader resourceLoader, String location) {
        try (var input = resourceLoader.getResource(location).getInputStream()) {
            String pem = new String(input.readAllBytes(), StandardCharsets.US_ASCII);
            String encoded = pem
                    .replace("-----BEGIN PUBLIC KEY-----", "")
                    .replace("-----END PUBLIC KEY-----", "")
                    .replaceAll("\\s", "");
            byte[] der = Base64.getDecoder().decode(encoded);
            return (RSAPublicKey) KeyFactory.getInstance("RSA")
                    .generatePublic(new X509EncodedKeySpec(der));
        } catch (IOException | GeneralSecurityException | IllegalArgumentException exception) {
            throw new IllegalStateException(
                    "Unable to load RS256 public key from " + location,
                    exception
            );
        }
    }
}
