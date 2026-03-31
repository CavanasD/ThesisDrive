"""
Two-Factor Authentication (TOTP) handlers for CFMS.

This module provides handlers for setting up, validating, and canceling
two-factor authentication using Time-based One-Time Passwords (TOTP).
"""

import orjson

from include.classes.enum.status import UserStatus
from include.classes.exceptions import UserNotActiveError
from include.classes.handler import ConnectionHandler
from include.classes.enum.permissions import Permissions
from include.classes.request import RequestHandler
from include.database.handler import Session
from include.database.models.classic import User


class RequestSetup2FAHandler(RequestHandler):
    """
    Handler for setting up two-factor authentication.

    This handler generates a TOTP secret and backup codes for the user.
    The TOTP secret is returned as a provisioning URI that can be used
    to generate a QR code for scanning with authenticator apps.

    Response Data:
        - secret: The TOTP secret (for manual entry)
        - provisioning_uri: URI for QR code generation
        - backup_codes: List of backup codes for account recovery
    """

    data_schema = {
        "type": "object",
        "properties": {"method": {"type": "string", "enum": ["totp"]}},
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        with Session() as session:
            user = session.get(User, handler.username)

            if not user:
                handler.conclude_request(
                    code=404,
                    message="User not found",
                    data={},
                )
                return 404, handler.username

            # Check if user already has 2FA enabled
            if user.totp_enabled:
                handler.conclude_request(
                    code=400,
                    message="Two-factor authentication is already enabled. Please cancel it first.",
                    data={
                        "method": "totp"
                    },  # will be extended if other methods are added
                )
                return

            # Setup TOTP
            secret, backup_codes = user.setup_totp()

            handler.conclude_request(
                code=200,
                message="Two-factor authentication setup initiated. Please verify with your authenticator app.",
                data={
                    "secret": secret,
                    "provisioning_uri": user.totp_provisioning_uri,
                    "backup_codes": backup_codes,
                },
            )
            return 200, handler.username


class RequestValidate2FAHandler(RequestHandler):
    """
    Handler for validating and enabling two-factor authentication.

    After setup, the user must validate their TOTP configuration by
    providing a valid code from their authenticator app. This enables 2FA.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "token": {"type": "string", "minLength": 1},
        },
        "required": ["token"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        token = handler.data["token"]
        username = handler.username

        success = False

        with Session() as session:
            user = session.get(User, username)

            if user is None:
                handler.conclude_request(
                    code=404,
                    message="User not found",
                    data={},
                )
                return

            # Check if TOTP secret exists but not enabled yet
            if not user.totp_secret:
                handler.conclude_request(
                    code=400,
                    message="Two-factor authentication has not been set up. Please set it up first.",
                    data={},
                )
                return

            if user.totp_enabled:
                handler.conclude_request(
                    code=400,
                    message="Two-factor authentication is already enabled.",
                    data={"method": "totp"},
                )
                return

            # Verify the provided TOTP token
            if user.verify_totp(token):
                user.enable_totp()
                success = True

        if success:
            handler.conclude_request(
                code=200,
                message="Two-factor authentication enabled successfully",
                data={"method": "totp"},
            )
        else:
            handler.conclude_request(401, {}, "Invalid verification code")

        return (0 if success else 401), username


class RequestDisable2FAHandler(RequestHandler):
    """
    Handler for canceling two-factor authentication.

    This handler disables and removes TOTP configuration for the user.
    The user must provide their password for verification.
    """

    # TODO: Allow sysops to disable 2FA for users who lost access

    data_schema = {
        "type": "object",
        "properties": {
            "password": {"type": "string", "minLength": 1},
        },
        "required": ["password"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        password = handler.data["password"]
        username = handler.username

        success = False

        with Session() as session:
            user = session.get(User, username)
            if not user or not user.totp_enabled:
                handler.conclude_request(400, {}, "2FA not enabled or user not found")
                return

            try:
                if user.verify_password(password):
                    if user.status != UserStatus.ACTIVE:
                        raise UserNotActiveError
                    user.disable_totp()
                    success = True
            except UserNotActiveError:
                handler.conclude_request(4003, {}, "User account is not active")
                return 4003, username

        if success:
            handler.conclude_request(200, {}, "2FA disabled successfully")
        else:
            handler.conclude_request(401, {}, "Invalid password")

        return (0 if success else 401), username


class RequestCancel2FASetupHandler(RequestHandler):
    """
    Handler for canceling two-factor authentication setup.

    This handler removes the TOTP configuration that was set up
    but not yet validated/enabled.
    """

    data_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        with Session() as session:
            user = session.get(User, handler.username)

            if not user:
                handler.conclude_request(
                    code=404,
                    message="User not found",
                    data={},
                )
                return

            # Check if TOTP setup exists but not enabled yet
            if not user.totp_secret or user.totp_enabled:
                handler.conclude_request(
                    code=400,
                    message="No pending two-factor authentication setup to cancel.",
                    data={},
                )
                return

            # Cancel TOTP setup
            user.totp_secret = None
            user.totp_backup_codes = None

            session.add(user)
            session.commit()

            handler.conclude_request(
                code=200,
                message="Two-factor authentication setup canceled successfully",
                data={},
            )


class RequestGet2FAStatusHandler(RequestHandler):
    """
    Handler for getting two-factor authentication status.

    Returns whether 2FA is enabled for the authenticated user.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        target_username = handler.data.get("target") or handler.username

        with Session() as session:
            user = session.get(User, handler.username)
            target = session.get(User, target_username)

            if not target:
                handler.conclude_request(
                    code=404,
                    message="Target user not found",
                    data={},
                )
                return

            assert user is not None

            if (
                target_username != handler.username
                and Permissions.MANAGE_2FA not in user.all_permissions
            ):
                handler.conclude_request(
                    code=403,
                    message="Forbidden: Cannot access another user's two-factor authentication status",
                    data={},
                )
                return 403, target_username, handler.username

            handler.conclude_request(
                code=200,
                message="Two-factor authentication status",
                data={
                    "enabled": target.totp_enabled,
                    "method": "totp" if target.totp_enabled else None,
                    "backup_codes_count": (
                        len(orjson.loads(target.totp_backup_codes))
                        if target.totp_backup_codes
                        else 0
                    ),
                },
            )
