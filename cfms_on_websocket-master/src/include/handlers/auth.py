import time
from typing import Any, Optional

from include.classes.enum.status import UserStatus
from include.classes.exceptions import (
    UserNotActiveError,
    UserTOTPFailedError,
    UserTOTPRequiredError,
)
from include.classes.handler import ConnectionHandler
from include.classes.misc.guard import LoginGuard
from include.classes.request import RequestHandler
from include.conf_loader import global_config
from include.database.handler import Session
from include.database.models.keyring import UserKey
from include.database.models.classic import User
from include.util.address import get_client_ip
from include.util.audit import log_audit
from include.util.pwd import check_passwd_requirements


class RequestLoginHandler(RequestHandler):
    """
    Handles user login requests.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "username": {"type": "string", "minLength": 1},
            "password": {"type": "string", "minLength": 1},
            "2fa_token": {"type": "string", "minLength": 1},
        },
        "required": ["username", "password"],
        "additionalProperties": False,
    }

    def handle(self, handler: ConnectionHandler):
        username: str = handler.data["username"]
        password: str = handler.data["password"]
        totp_token: str = handler.data.get("2fa_token", "")

        ip = get_client_ip(handler.stream.connection._ws)
        ip_id = f"ip_limit|{ip}"
        user_id = f"user_limit|{ip}|{username}"

        def respond(code: int, message: str, data: Optional[dict[str, Any]] = None):
            handler.conclude_request(code=code, data=data or {}, message=message)
            return code, username

        def fail(code: int, message: str):
            LoginGuard.report_failure(user_id, max_attempts=5)
            LoginGuard.report_failure(ip_id, max_attempts=20)
            return respond(code, message)

        if not LoginGuard.check_access(user_id):
            return respond(429, "Too many login attempts. Please try again later.")

        cfg = global_config["security"]

        with Session() as session:
            user = session.get(User, username)

            if not user:
                return fail(401, "Invalid credentials")

            try:
                token = user.authenticate_and_create_token(
                    password, totp_token=totp_token
                )
            except UserTOTPRequiredError:
                return respond(
                    202, "Two-factor authentication required", {"method": "totp"}
                )
            except UserTOTPFailedError:
                return fail(401, "Invalid two-factor authentication token")
            except UserNotActiveError:
                return fail(4003, "User account is not active")

            if not token:
                return fail(401, "Invalid credentials")

            LoginGuard.report_success(user_id)
            LoginGuard.report_success(ip_id)

            try:
                check_passwd_requirements(
                    password,
                    cfg["passwd_min_length"],
                    cfg["passwd_max_length"],
                    cfg["passwd_must_contain"],
                )
            except ValueError:
                return respond(4001, "Password must be changed before you can log in")

            if cfg["enable_passwd_force_expiration"]:
                expiration_seconds = 3600 * 24 * cfg["passwd_expire_after_days"]
                if time.time() - user.passwd_last_modified > expiration_seconds:
                    return respond(
                        4002, "Password should be changed because it's expired"
                    )

            success_data = {
                "token": token.raw,
                "exp": token.exp,
                "nickname": user.nickname,
                "avatar_id": user.avatar_id,
                "permissions": list(user.all_permissions),
                "groups": list(user.all_groups),
            }

            if user.preference_dek_id:
                preference_dek = session.get(UserKey, user.preference_dek_id)
                if preference_dek:
                    success_data["preference_dek"] = {
                        "key_id": preference_dek.id,
                        "key_content": preference_dek.content,
                        "label": preference_dek.label,
                    }

            return respond(200, "Login successful", success_data)


class RequestRefreshTokenHandler(RequestHandler):
    """
    Handles token refresh requests.
    This util processes a token refresh request by validating the existing token and generating a new one if valid.
    It sends an appropriate response back to the client, indicating success or failure.
    Args:
        handler (ConnectionHandler): The connection handler containing request data and methods for responding.
    Response Codes:
        200   - Token refreshed successfully, returns a new token in the response data.
        400 - Missing or invalid token in the request.
        500 - Internal server error, with the exception message.
    """

    data_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def handle(self, handler: ConnectionHandler):

        # Parse the refresh token request
        old_token = handler.token

        # Validate the token
        if not old_token or not isinstance(old_token, str):
            response = {
                "code": 400,
                "message": "missing or invalid token",
                "data": {},
            }
        else:
            with Session() as session:
                user = session.get(User, handler.username)

                if user and user.is_token_valid(old_token):
                    new_token = user.renew_token()
                    response = {
                        "code": 200,
                        "message": "Token refreshed successfully",
                        "data": {"token": new_token.raw, "exp": new_token.exp},
                    }
                    log_audit(
                        "refresh_token",
                        target=handler.username,
                        result=0,
                        remote_address=handler.remote_address,
                    )
                else:
                    response = {
                        "code": 400,
                        "message": "Invalid or expired token",
                        "data": {},
                    }
                    log_audit(
                        "refresh_token",
                        target=handler.username,
                        result=1,
                        remote_address=handler.remote_address,
                    )

        # Send the response back to the client
        handler.conclude_request(**response)
