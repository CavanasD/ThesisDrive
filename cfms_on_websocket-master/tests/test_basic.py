"""
Tests for basic server functionality and authentication - Rewritten.
"""

import pytest
from tests.test_client import CFMSTestClient


class TestServerBasics:
    """Test basic server functionality with improved assertions."""
    
    @pytest.mark.asyncio
    async def test_server_connection(self, client: CFMSTestClient):
        """Test that we can establish and maintain a WebSocket connection."""
        assert client.websocket is not None, "WebSocket connection was not established"
        assert hasattr(client.websocket, 'id'), "WebSocket missing id attribute"
    
    @pytest.mark.asyncio
    async def test_server_info(self, client: CFMSTestClient):
        """Test getting server information without authentication."""
        try:
            response = await client.server_info()
        except Exception as e:
            pytest.fail(f"server_info() raised an exception: {e}")
        
        assert isinstance(response, dict), f"Response should be dict, got {type(response)}"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 200, \
            f"Expected status code 200, got {response.get('code')}: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data' field"
        assert isinstance(response["data"], dict), "'data' should be a dictionary"
        
        required_fields = ["server_name", "version", "protocol_version"]
        for field in required_fields:
            assert field in response["data"], \
                f"Server info missing required field '{field}'"
    
    @pytest.mark.asyncio
    async def test_unknown_action(self, client: CFMSTestClient):
        """Test that server properly rejects unknown action types."""
        try:
            response = await client.send_request("nonexistent_action_xyz_123", include_auth=False)
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 400, \
            f"Expected 400 for unknown action, got {response.get('code')}"
        
        assert "message" in response, "Error response should include 'message'"
        message = response["message"].lower()
        assert any(keyword in message for keyword in ["unknown", "invalid", "action"]), \
            f"Error message doesn't indicate unknown action: {response['message']}"


class TestAuthentication:
    """Test authentication functionality with comprehensive scenarios."""
    
    @pytest.mark.asyncio
    async def test_login_success(self, client: CFMSTestClient, admin_credentials: dict):
        """Test successful login with valid admin credentials."""
        try:
            response = await client.login(
                admin_credentials["username"],
                admin_credentials["password"]
            )
        except Exception as e:
            pytest.fail(f"login() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        
        if response["code"] != 200:
            pytest.fail(f"Login failed unexpectedly: {response}")
        
        assert "data" in response, "Successful login response missing 'data'"
        assert "token" in response["data"], "Login response missing 'token'"
        assert isinstance(response["data"]["token"], str), "Token should be a string"
        assert len(response["data"]["token"]) > 0, "Token should not be empty"
        
        assert client.token is not None, "Client token not set after login"
        assert client.username == admin_credentials["username"], \
            f"Client username mismatch: expected {admin_credentials['username']}, got {client.username}"
    
    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: CFMSTestClient):
        """Test login fails with invalid credentials."""
        try:
            response = await client.login("invalid_user_xyz", "invalid_password_xyz")
        except Exception as e:
            pytest.fail(f"login() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 401, \
            f"Expected 401 for invalid credentials, got {response.get('code')}"
        
        assert "message" in response, "Error response should include 'message'"
        message = response["message"].lower()
        assert any(keyword in message for keyword in ["invalid", "credentials", "authentication"]), \
            f"Error message doesn't indicate auth failure: {response['message']}"
    
    @pytest.mark.asyncio
    async def test_login_missing_username(self, client: CFMSTestClient):
        """Test login fails when username is missing."""
        try:
            response = await client.send_request(
                "login",
                {"password": "test_password"},
                include_auth=False
            )
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 400, \
            f"Expected 400 for missing username, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_login_missing_password(self, client: CFMSTestClient):
        """Test login fails when password is missing."""
        try:
            response = await client.send_request(
                "login",
                {"username": "test_user"},
                include_auth=False
            )
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 400, \
            f"Expected 400 for missing password, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_refresh_token(self, authenticated_client: CFMSTestClient):
        """Test token refresh functionality."""
        old_token = authenticated_client.token
        assert old_token is not None, "Client should have a token before refresh"
        
        try:
            response = await authenticated_client.refresh_token()
        except Exception as e:
            pytest.fail(f"refresh_token() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 200, \
            f"Token refresh failed: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert "token" in response["data"], "Response missing new token"
        
        new_token = authenticated_client.token
        assert new_token is not None, "Token should still be set after refresh"
        assert new_token != old_token, "Token should change after refresh"
    
    @pytest.mark.asyncio
    async def test_authentication_required(self, client: CFMSTestClient):
        """Test that protected endpoints require authentication."""
        try:
            response = await client.send_request("list_users", include_auth=False)
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 401, \
            f"Expected 401 for unauthenticated request, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_invalid_token(self, client: CFMSTestClient, admin_credentials: dict):
        """Test request with an invalid authentication token."""
        # Login first to set up proper session structure
        login_response = await client.login(
            admin_credentials["username"],
            admin_credentials["password"]
        )
        assert login_response["code"] == 200, f"Setup login failed: {login_response}"
        
        # Now send request with invalid token
        try:
            response = await client.send_request(
                "list_users",
                username=admin_credentials["username"],
                token="invalid_token_xyz_12345"
            )
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 401, \
            f"Expected 401 for invalid token, got {response.get('code')}"
