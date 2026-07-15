package com.thesis.transfer.security;

import com.thesis.transfer.web.TransferException;
import org.springframework.http.HttpStatus;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtClaimNames;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.Locale;

@Service
public class TransferTicketService {

    public TransferTicket require(
            Jwt jwt,
            String pathTaskId,
            TransferOperation requiredOperation
    ) {
        String taskId = claim(jwt, "task_id");
        // Core uses jti as a random per-ticket identifier; it is deliberately
        // different from task_id, which is the URL/session binding.
        claim(jwt, JwtClaimNames.JTI);
        String username = claim(jwt, "username", "sub");
        String operationValue = claim(jwt, "operation");
        String objectKey = claim(jwt, "object_key");
        long maxSize = longClaim(jwt, "max_size");
        String expectedSha256 = optionalClaim(jwt, "expected_sha256");

        if (!taskId.equals(pathTaskId)) {
            throw forbidden("Ticket task_id does not match the requested transfer");
        }

        TransferOperation operation = TransferOperation.parse(operationValue);
        if (operation != requiredOperation) {
            throw forbidden("Ticket does not permit this transfer operation");
        }
        if (!StringUtils.hasText(username)) {
            throw forbidden("Ticket username is missing");
        }
        if (!StringUtils.hasText(objectKey) || objectKey.length() > 1024) {
            throw forbidden("Ticket object_key is invalid");
        }
        if (maxSize < 0) {
            throw forbidden("Ticket max_size must not be negative");
        }
        if (StringUtils.hasText(expectedSha256)
                && !expectedSha256.toLowerCase(Locale.ROOT).matches("[0-9a-f]{64}")) {
            throw forbidden("Ticket expected_sha256 is invalid");
        }

        return new TransferTicket(
                taskId,
                username,
                operation,
                objectKey,
                maxSize,
                StringUtils.hasText(expectedSha256)
                        ? expectedSha256.toLowerCase(Locale.ROOT)
                        : null,
                jwt.getExpiresAt()
        );
    }

    private static String claim(Jwt jwt, String... names) {
        String value = optionalClaim(jwt, names);
        if (!StringUtils.hasText(value)) {
            throw forbidden("Required ticket claim is missing: " + names[0]);
        }
        return value;
    }

    private static String optionalClaim(Jwt jwt, String... names) {
        for (String name : names) {
            Object value = jwt.getClaims().get(name);
            if (value != null && StringUtils.hasText(value.toString())) {
                return value.toString();
            }
        }
        return null;
    }

    private static long longClaim(Jwt jwt, String name) {
        Object value = jwt.getClaims().get(name);
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value != null) {
            try {
                return Long.parseLong(value.toString());
            } catch (NumberFormatException ignored) {
                // handled below
            }
        }
        throw forbidden("Required numeric ticket claim is invalid: " + name);
    }

    private static TransferException forbidden(String message) {
        return new TransferException(HttpStatus.FORBIDDEN, "invalid_ticket", message);
    }
}
