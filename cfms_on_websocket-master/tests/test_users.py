"""
Tests for user management operations - Rewritten with improved robustness.
"""

import pytest
import time
from tests.test_client import CFMSTestClient


class TestUserOperations:
    """Test user management operations with comprehensive validation."""
    
    @pytest.mark.asyncio
    async def test_list_users(self, authenticated_client: CFMSTestClient):
        """Test listing all users with proper structure validation."""
        try:
            response = await authenticated_client.list_users()
        except Exception as e:
            pytest.fail(f"list_users() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to list users: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert "users" in response["data"], "Response missing 'users'"
        assert isinstance(response["data"]["users"], list), "'users' should be a list"
        
        # Should have at least the admin user
        usernames = [user.get("username") for user in response["data"]["users"]]
        assert "admin" in usernames, "Admin user should be in users list"
    
    @pytest.mark.asyncio
    async def test_create_user(self, authenticated_client: CFMSTestClient):
        """Test creating a new user with unique username."""
        username = f"test_user_{int(time.time() * 1000)}"
        password = "TestPassword123!"
        
        try:
            response = await authenticated_client.create_user(
                username=username,
                password=password,
                nickname="Test User"
            )
        except Exception as e:
            pytest.fail(f"create_user() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to create user: {response.get('message', '')}"
        
        # Cleanup
        try:
            await authenticated_client.delete_user(username)
        except Exception:
            pass
    
    @pytest.mark.asyncio
    async def test_get_user_info(self, authenticated_client: CFMSTestClient, test_user: dict):
        """Test retrieving user information."""
        try:
            response = await authenticated_client.get_user_info(test_user["username"])
        except Exception as e:
            pytest.fail(f"get_user_info() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to get user info: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert response["data"]["username"] == test_user["username"], \
            f"Username mismatch: expected {test_user['username']}, got {response['data'].get('username')}"
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_user_info(self, authenticated_client: CFMSTestClient):
        """Test retrieving info for non-existent user returns error."""
        try:
            response = await authenticated_client.get_user_info("nonexistent_user_xyz_12345")
        except Exception as e:
            pytest.fail(f"get_user_info() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] != 200, \
            "Getting nonexistent user should not return 200"
        assert response["code"] in [400, 404], \
            f"Expected 400 or 404 for nonexistent user, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_delete_user(self, authenticated_client: CFMSTestClient):
        """Test deleting a user and verify removal."""
        # Create a user to delete
        username = f"user_to_delete_{int(time.time() * 1000)}"
        
        try:
            create_response = await authenticated_client.create_user(
                username=username,
                password="TestPassword123!"
            )
        except Exception as e:
            pytest.fail(f"Failed to create user for deletion test: {e}")
        
        assert create_response.get("code") == 200, "Failed to create test user"
        
        # Delete it
        try:
            delete_response = await authenticated_client.delete_user(username)
        except Exception as e:
            pytest.fail(f"delete_user() raised an exception: {e}")
        
        assert isinstance(delete_response, dict), "Response should be a dictionary"
        assert "code" in delete_response, "Response missing 'code'"
        assert delete_response["code"] == 200, \
            f"Failed to delete user: {delete_response.get('message', '')}"
        
        # Verify it's gone
        try:
            info_response = await authenticated_client.get_user_info(username)
        except Exception as e:
            pytest.fail(f"get_user_info() raised an exception during verification: {e}")
        
        assert info_response.get("code") != 200, \
            "User should not be retrievable after deletion"
    
    @pytest.mark.asyncio
    async def test_create_user_with_duplicate_username(self, authenticated_client: CFMSTestClient, test_user: dict):
        """Test that creating a user with duplicate username fails."""
        try:
            response = await authenticated_client.create_user(
                username=test_user["username"],
                password="AnotherPassword123!"
            )
        except Exception as e:
            pytest.fail(f"create_user() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] != 200, \
            "Creating duplicate user should not succeed"
        assert response["code"] in [400, 409], \
            f"Expected 400 or 409 for duplicate username, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_create_user_with_empty_username(self, authenticated_client: CFMSTestClient):
        """Test that creating a user with empty username fails validation."""
        try:
            response = await authenticated_client.create_user(
                username="",
                password="TestPassword123!"
            )
        except Exception as e:
            pytest.fail(f"create_user() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 400, \
            f"Expected 400 for empty username, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_get_admin_user_info(self, authenticated_client: CFMSTestClient):
        """Test retrieving admin user information."""
        try:
            response = await authenticated_client.get_user_info("admin")
        except Exception as e:
            pytest.fail(f"get_user_info() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to get admin user info: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert response["data"]["username"] == "admin", \
            f"Expected username 'admin', got '{response['data'].get('username')}'"


class TestUserWithoutAuth:
    """Test that user operations properly require authentication."""
    
    @pytest.mark.asyncio
    async def test_list_users_without_auth(self, client: CFMSTestClient):
        """Test that listing users requires authentication."""
        try:
            response = await client.send_request(
                "list_users",
                {},
                include_auth=False
            )
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 401, \
            f"Expected 401 for unauthenticated request, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_create_user_without_auth(self, client: CFMSTestClient):
        """Test that creating a user requires authentication."""
        try:
            response = await client.send_request(
                "create_user",
                {
                    "username": "testuser",
                    "password": "TestPassword123!"
                },
                include_auth=False
            )
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 401, \
            f"Expected 401 for unauthenticated request, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_get_user_info_without_auth(self, client: CFMSTestClient):
        """Test that getting user info requires authentication."""
        try:
            response = await client.send_request(
                "get_user_info",
                {"username": "admin"},
                include_auth=False
            )
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 401, \
            f"Expected 401 for unauthenticated request, got {response.get('code')}"
