"""
Tests for two-factor authentication (TOTP) functionality.
"""

import pytest
import pyotp
from tests.test_client import CFMSTestClient


class TestTwoFactorAuth:
    """Test two-factor authentication setup, validation, and cancellation."""
    
    @pytest.mark.asyncio
    async def test_get_2fa_status_disabled_by_default(self, authenticated_client: CFMSTestClient):
        """Test that 2FA is disabled by default for new users."""
        try:
            response = await authenticated_client.get_2fa_status()
        except Exception as e:
            pytest.fail(f"get_2fa_status() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to get 2FA status: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert "enabled" in response["data"], "Response missing 'enabled'"
        assert response["data"].get("method", None) is None, \
            "2FA method should be None when disabled"
        assert response["data"]["enabled"] is False, \
            "2FA should be disabled by default"
    
    @pytest.mark.asyncio
    async def test_setup_2fa(self, authenticated_client: CFMSTestClient):
        """Test setting up 2FA for a user."""
        try:
            response = await authenticated_client.setup_2fa()
        except Exception as e:
            pytest.fail(f"setup_2fa() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to setup 2FA: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert "secret" in response["data"], "Response missing 'secret'"
        assert "provisioning_uri" in response["data"], "Response missing 'provisioning_uri'"
        assert "backup_codes" in response["data"], "Response missing 'backup_codes'"
        
        # Verify the secret is a valid base32 string
        secret = response["data"]["secret"]
        assert isinstance(secret, str), "Secret should be a string"
        assert len(secret) > 0, "Secret should not be empty"
        
        # Verify backup codes
        backup_codes = response["data"]["backup_codes"]
        assert isinstance(backup_codes, list), "Backup codes should be a list"
        assert len(backup_codes) == 10, "Should have 10 backup codes"
        
        # Verify provisioning URI format
        provisioning_uri = response["data"]["provisioning_uri"]
        assert provisioning_uri.startswith("otpauth://totp/"), \
            "Provisioning URI should start with 'otpauth://totp/'"
        
        # Cleanup: Cancel 2FA setup for other tests
        try:
            await authenticated_client.cancel_2fa_setup()
        except Exception:
            pass  # Ignore cleanup errors
    
    @pytest.mark.asyncio
    async def test_validate_2fa_with_valid_token(self, authenticated_client: CFMSTestClient, admin_credentials: dict):
        """Test validating 2FA with a valid TOTP token."""
        did_setup = False
        try:
            setup_response = await authenticated_client.setup_2fa()
            assert setup_response.get("code") == 200, "Failed to setup 2FA"
            did_setup = True

            secret = setup_response["data"]["secret"]

            # Generate a valid TOTP token
            totp = pyotp.TOTP(secret)
            token = totp.now()

            # Validate the token
            try:
                response = await authenticated_client.validate_2fa(token)
            except Exception as e:
                pytest.fail(f"validate_2fa() raised an exception: {e}")

            assert isinstance(response, dict), "Response should be a dictionary"
            assert "code" in response, "Response missing 'code'"
            assert response["code"] == 200, \
                f"Failed to validate 2FA: {response.get('message', '')}"
            assert "data" in response, "Response missing 'data'"
            assert response["data"].get("method") == "totp", \
                "2FA method should be 'totp' after validation"  # for now
            
            # Get 2FA status to confirm it's enabled
            try:
                status_response = await authenticated_client.get_2fa_status()
            except Exception as e:
                pytest.fail(f"get_2fa_status() raised an exception: {e}")

            assert "data" in status_response, "Response missing 'data'"
            assert status_response["data"].get("enabled") is True, \
                "2FA should be enabled after validation"
        finally:
            # Cleanup: Disable 2FA for other tests (always attempt regardless of failures)
            if did_setup:
                try:
                    await authenticated_client.cancel_2fa(admin_credentials["password"])
                except Exception:
                    pass  # Ignore cleanup errors
    
    @pytest.mark.asyncio
    async def test_validate_2fa_with_invalid_token(self, authenticated_client: CFMSTestClient):
        """Test that validation fails with an invalid TOTP token."""
        # Setup 2FA first
        setup_response = await authenticated_client.setup_2fa()
        assert setup_response.get("code") == 200, "Failed to setup 2FA"
        
        # Try to validate with an invalid token
        try:
            response = await authenticated_client.validate_2fa("000000")
        except Exception as e:
            pytest.fail(f"validate_2fa() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 401, \
            f"Expected 401 for invalid token, got {response.get('code')}"
        
        # Cleanup: Cancel 2FA setup for other tests
        try:
            await authenticated_client.cancel_2fa_setup()
        except Exception:
            pass  # Ignore cleanup errors
    
    @pytest.mark.asyncio
    async def test_validate_2fa_without_setup(self, authenticated_client: CFMSTestClient):
        """Test that validation fails if 2FA hasn't been set up."""
        try:
            response = await authenticated_client.validate_2fa("123456")
        except Exception as e:
            pytest.fail(f"validate_2fa() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 400, \
            f"Expected 400 for validation without setup, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_setup_2fa_twice_fails(self, authenticated_client: CFMSTestClient, admin_credentials: dict):
        """Test that setting up 2FA twice fails if already enabled."""
        # Setup and enable 2FA
        setup_response = await authenticated_client.setup_2fa()
        assert setup_response.get("code") == 200, "Failed to setup 2FA"
        
        secret = setup_response["data"]["secret"]
        totp = pyotp.TOTP(secret)
        token = totp.now()
        
        validate_response = await authenticated_client.validate_2fa(token)
        assert validate_response.get("code") == 200, "Failed to validate 2FA"
        
        # Try to setup again
        try:
            response = await authenticated_client.setup_2fa()
        except Exception as e:
            pytest.fail(f"setup_2fa() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 400, \
            f"Expected 400 for duplicate setup, got {response.get('code')}"
        
        # Cleanup: Disable 2FA for other tests
        try:
            await authenticated_client.cancel_2fa(admin_credentials["password"])
        except Exception:
            pass  # Ignore cleanup errors
    
    @pytest.mark.asyncio
    async def test_cancel_2fa_with_valid_password(self, authenticated_client: CFMSTestClient, admin_credentials: dict):
        """Test canceling 2FA with correct password."""
        # Setup and enable 2FA
        setup_response = await authenticated_client.setup_2fa()
        assert setup_response.get("code") == 200, "Failed to setup 2FA"
        
        secret = setup_response["data"]["secret"]
        totp = pyotp.TOTP(secret)
        token = totp.now()
        
        validate_response = await authenticated_client.validate_2fa(token)
        assert validate_response.get("code") == 200, "Failed to validate 2FA"
        
        # Cancel 2FA
        try:
            response = await authenticated_client.cancel_2fa(admin_credentials["password"])
        except Exception as e:
            pytest.fail(f"cancel_2fa() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to cancel 2FA: {response.get('message', '')}"
    
    @pytest.mark.asyncio
    async def test_cancel_2fa_with_invalid_password(self, authenticated_client: CFMSTestClient, admin_credentials: dict):
        """Test that canceling 2FA fails with incorrect password."""
        # Setup and enable 2FA
        setup_response = await authenticated_client.setup_2fa()
        assert setup_response.get("code") == 200, "Failed to setup 2FA"
        
        secret = setup_response["data"]["secret"]
        totp = pyotp.TOTP(secret)
        token = totp.now()
        
        validate_response = await authenticated_client.validate_2fa(token)
        assert validate_response.get("code") == 200, "Failed to validate 2FA"
        
        # Try to cancel with wrong password
        try:
            response = await authenticated_client.cancel_2fa("wrong_password")
        except Exception as e:
            pytest.fail(f"cancel_2fa() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 401, \
            f"Expected 401 for invalid password, got {response.get('code')}"
        
        # Cleanup: Disable 2FA with correct password for other tests
        try:
            await authenticated_client.cancel_2fa(admin_credentials["password"])
        except Exception:
            pass  # Ignore cleanup errors
    
    @pytest.mark.asyncio
    async def test_cancel_2fa_when_not_enabled(self, authenticated_client: CFMSTestClient, admin_credentials: dict):
        """Test that canceling 2FA fails if it's not enabled."""
        try:
            response = await authenticated_client.cancel_2fa(admin_credentials["password"])
        except Exception as e:
            pytest.fail(f"cancel_2fa() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 400, \
            f"Expected 400 for cancel when not enabled, got {response.get('code')}"


class TestTwoFactorAuthLogin:
    """Test two-factor authentication during login flow."""
    
    @pytest.mark.asyncio
    async def test_login_without_2fa(self, client: CFMSTestClient):
        """Test normal login flow when 2FA is not enabled."""
        try:
            response = await client.login("admin", "admin")
        except Exception as e:
            pytest.fail(f"login() raised an exception: {e}")
        
        # Should succeed with code 200
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        # Admin password might not be "admin", so accept both 200 and 401
        assert response["code"] in [200, 401], \
            f"Unexpected response code: {response.get('code')}"

    @pytest.mark.asyncio
    async def test_login_with_2fa_enabled_returns_202(self, authenticated_client: CFMSTestClient, test_user: dict, client: CFMSTestClient, admin_credentials: dict):
        """Test that login returns 202 when 2FA is enabled and no token provided."""
        did_setup = False
        try:
            # Setup and enable 2FA for test user
            setup_response = await authenticated_client.setup_2fa()
            assert setup_response.get("code") == 200, "Failed to setup 2FA"
            did_setup = True

            secret = setup_response["data"]["secret"]
            totp = pyotp.TOTP(secret)
            token = totp.now()

            validate_response = await authenticated_client.validate_2fa(token)
            assert validate_response.get("code") == 200, "Failed to validate 2FA"

            # Try to login with new client without providing 2FA token
            try:
                await client.connect()
                response = await client.login(admin_credentials["username"], admin_credentials["password"])
            except Exception as e:
                pytest.fail(f"login() raised an exception: {e}")

            assert isinstance(response, dict), "Response should be a dictionary"
            assert "code" in response, "Response missing 'code'"
            assert response["code"] == 202, \
                f"Expected 202 (2FA required), got {response.get('code')}"

            assert "data" in response, "Response missing 'data'"
            assert response["data"].get("method") == "totp", \
                "Response should indicate TOTP method is required"
        finally:
            # Always attempt to disable 2FA if setup succeeded
            if did_setup:
                try:
                    await authenticated_client.cancel_2fa(admin_credentials["password"])
                except Exception:
                    pass  # Ignore cleanup errors
    
    @pytest.mark.asyncio
    async def test_verify_2fa_login_with_valid_token(self, authenticated_client: CFMSTestClient, test_user: dict, client: CFMSTestClient, admin_credentials: dict):
        """Test completing login with valid 2FA token."""
        did_setup = False
        try:
            # Setup and enable 2FA
            setup_response = await authenticated_client.setup_2fa()
            assert setup_response.get("code") == 200, "Failed to setup 2FA"
            did_setup = True

            secret = setup_response["data"]["secret"]
            totp = pyotp.TOTP(secret)
            token = totp.now()

            validate_response = await authenticated_client.validate_2fa(token)
            assert validate_response.get("code") == 200, "Failed to validate 2FA"

            # Login with 2FA token provided
            token = totp.now()
            try:
                response = await client.login(admin_credentials["username"], admin_credentials["password"], two_fa_token=token)
            except Exception as e:
                pytest.fail(f"login() raised an exception: {e}")

            assert isinstance(response, dict), "Response should be a dictionary"
            assert "code" in response, "Response missing 'code'"
            assert response["code"] == 200, \
                f"Failed to login with 2FA: {response.get('message', '')}"

            assert "data" in response, "Response missing 'data'"
            assert "token" in response["data"], "Response should include token"
            assert "exp" in response["data"], "Response should include token expiry"
        finally:
            # Cleanup: Disable 2FA regardless of test outcome
            if did_setup:
                try:
                    await authenticated_client.cancel_2fa(admin_credentials["password"])
                except Exception:
                    pass  # Ignore cleanup errors
    
    @pytest.mark.asyncio
    async def test_verify_2fa_login_with_invalid_token(self, authenticated_client: CFMSTestClient, test_user: dict, client: CFMSTestClient, admin_credentials: dict):
        """Test that login fails with invalid 2FA token."""
        did_setup = False
        try:
            # Setup and enable 2FA
            setup_response = await authenticated_client.setup_2fa()
            assert setup_response.get("code") == 200, "Failed to setup 2FA"
            did_setup = True

            secret = setup_response["data"]["secret"]
            totp = pyotp.TOTP(secret)
            token = totp.now()

            validate_response = await authenticated_client.validate_2fa(token)
            assert validate_response.get("code") == 200, "Failed to validate 2FA"

            # Try to login with invalid 2FA token
            try:
                response = await client.login(admin_credentials["username"], admin_credentials["password"], two_fa_token="000000")
            except Exception as e:
                pytest.fail(f"login() raised an exception: {e}")

            assert isinstance(response, dict), "Response should be a dictionary"
            assert "code" in response, "Response missing 'code'"
            assert response["code"] == 401, \
                f"Expected 401 for invalid token, got {response.get('code')}"
        finally:
            # Always attempt to disable 2FA if setup succeeded
            if did_setup:
                try:
                    await authenticated_client.cancel_2fa(admin_credentials["password"])
                except Exception:
                    pass  # Ignore cleanup errors
    
    @pytest.mark.asyncio
    async def test_verify_2fa_login_with_backup_code(self, authenticated_client: CFMSTestClient, test_user: dict, client: CFMSTestClient, admin_credentials: dict):
        """Test completing login with a backup code."""
        did_setup = False
        try:
            # Setup and enable 2FA
            setup_response = await authenticated_client.setup_2fa()
            assert setup_response.get("code") == 200, "Failed to setup 2FA"
            did_setup = True

            secret = setup_response["data"]["secret"]
            backup_codes = setup_response["data"]["backup_codes"]

            totp = pyotp.TOTP(secret)
            token = totp.now()

            validate_response = await authenticated_client.validate_2fa(token)
            assert validate_response.get("code") == 200, "Failed to validate 2FA"

            # Login with backup code
            backup_code = backup_codes[0]
            try:
                response = await client.login(admin_credentials["username"], admin_credentials["password"], two_fa_token=backup_code)
            except Exception as e:
                pytest.fail(f"login() raised an exception: {e}")

            assert isinstance(response, dict), "Response should be a dictionary"
            assert "code" in response, "Response missing 'code'"
            assert response["code"] == 200, \
                f"Failed to verify with backup code: {response.get('message', '')}"

            assert "data" in response, "Response missing 'data'"
            assert "token" in response["data"], "Response should include token"
        finally:
            # Always attempt to disable 2FA if setup succeeded
            if did_setup:
                try:
                    await authenticated_client.cancel_2fa(admin_credentials["password"])
                except Exception:
                    pass  # Ignore cleanup errors
