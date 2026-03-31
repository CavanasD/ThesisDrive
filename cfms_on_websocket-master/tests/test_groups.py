"""
Tests for group management operations - Rewritten with improved robustness.
"""

import pytest
import time
from tests.test_client import CFMSTestClient


class TestGroupOperations:
    """Test group management operations with comprehensive validation."""
    
    @pytest.mark.asyncio
    async def test_list_groups(self, authenticated_client: CFMSTestClient):
        """Test listing all groups with proper structure validation."""
        try:
            response = await authenticated_client.list_groups()
        except Exception as e:
            pytest.fail(f"list_groups() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to list groups: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert "groups" in response["data"], "Response missing 'groups'"
        assert isinstance(response["data"]["groups"], list), "'groups' should be a list"
        
        # Should have at least the default groups
        group_names = [group.get("name") for group in response["data"]["groups"]]
        assert "sysop" in group_names, "Default 'sysop' group should exist"
        assert "user" in group_names, "Default 'user' group should exist"
    
    @pytest.mark.asyncio
    async def test_create_group(self, authenticated_client: CFMSTestClient):
        """Test creating a new group with unique name."""
        group_name = f"test_group_{int(time.time() * 1000)}"
        
        try:
            response = await authenticated_client.create_group(
                group_name=group_name,
                permissions=[]
            )
        except Exception as e:
            pytest.fail(f"create_group() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to create group: {response.get('message', '')}"
        
        # Cleanup
        try:
            await authenticated_client.send_request("delete_group", {"group_name": group_name})
        except Exception:
            pass
    
    @pytest.mark.asyncio
    async def test_get_group_info(self, authenticated_client: CFMSTestClient, test_group: dict):
        """Test retrieving group information."""
        try:
            response = await authenticated_client.get_group_info(test_group["group_name"])
        except Exception as e:
            pytest.fail(f"get_group_info() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to get group info: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert response["data"]["name"] == test_group["group_name"], \
            f"Group name mismatch: expected {test_group['group_name']}, got {response['data'].get('name')}"
    
    @pytest.mark.asyncio
    async def test_get_sysop_group_info(self, authenticated_client: CFMSTestClient):
        """Test retrieving information for the default sysop group."""
        try:
            response = await authenticated_client.get_group_info("sysop")
        except Exception as e:
            pytest.fail(f"get_group_info() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 200, \
            f"Failed to get sysop group info: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert response["data"]["name"] == "sysop", \
            f"Expected group name 'sysop', got '{response['data'].get('name')}'"
        assert "permissions" in response["data"], "Group info should include permissions"
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_group_info(self, authenticated_client: CFMSTestClient):
        """Test retrieving info for non-existent group returns error."""
        try:
            response = await authenticated_client.get_group_info("nonexistent_group_xyz_12345")
        except Exception as e:
            pytest.fail(f"get_group_info() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] != 200, \
            "Getting nonexistent group should not return 200"
        assert response["code"] in [400, 404], \
            f"Expected 400 or 404 for nonexistent group, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_create_group_with_empty_name(self, authenticated_client: CFMSTestClient):
        """Test that creating a group with empty name fails validation."""
        try:
            response = await authenticated_client.create_group("")
        except Exception as e:
            pytest.fail(f"create_group() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 400, \
            f"Expected 400 for empty group name, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_create_duplicate_group(self, authenticated_client: CFMSTestClient, test_group: dict):
        """Test that creating a group with duplicate name fails."""
        try:
            response = await authenticated_client.create_group(test_group["group_name"])
        except Exception as e:
            pytest.fail(f"create_group() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] != 200, \
            "Creating duplicate group should not succeed"
        assert response["code"] in [400, 409], \
            f"Expected 400 or 409 for duplicate group name, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_delete_group(self, authenticated_client: CFMSTestClient):
        """Test deleting a group and verify removal."""
        # Create a group to delete
        group_name = f"group_to_delete_{int(time.time() * 1000)}"
        
        try:
            create_response = await authenticated_client.create_group(group_name)
        except Exception as e:
            pytest.fail(f"Failed to create group for deletion test: {e}")
        
        assert create_response.get("code") == 200, "Failed to create test group"
        
        # Delete it
        try:
            delete_response = await authenticated_client.send_request(
                "delete_group",
                {"group_name": group_name}
            )
        except Exception as e:
            pytest.fail(f"delete_group request raised an exception: {e}")
        
        assert isinstance(delete_response, dict), "Response should be a dictionary"
        assert "code" in delete_response, "Response missing 'code'"
        assert delete_response["code"] == 200, \
            f"Failed to delete group: {delete_response.get('message', '')}"
        
        # Verify it's gone
        try:
            info_response = await authenticated_client.get_group_info(group_name)
        except Exception as e:
            pytest.fail(f"get_group_info() raised an exception during verification: {e}")
        
        assert info_response.get("code") != 200, \
            "Group should not be retrievable after deletion"


class TestGroupWithoutAuth:
    """Test that group operations properly require authentication."""
    
    @pytest.mark.asyncio
    async def test_list_groups_without_auth(self, client: CFMSTestClient):
        """Test that listing groups requires authentication."""
        try:
            response = await client.send_request(
                "list_groups",
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
    async def test_create_group_without_auth(self, client: CFMSTestClient):
        """Test that creating a group requires authentication."""
        try:
            response = await client.send_request(
                "create_group",
                {"group_name": "testgroup"},
                include_auth=False
            )
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 401, \
            f"Expected 401 for unauthenticated request, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_get_group_info_without_auth(self, client: CFMSTestClient):
        """Test that getting group info requires authentication."""
        try:
            response = await client.send_request(
                "get_group_info",
                {"group_name": "sysop"},
                include_auth=False
            )
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 401, \
            f"Expected 401 for unauthenticated request, got {response.get('code')}"
