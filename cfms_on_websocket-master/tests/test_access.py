"""
Tests for access management operations.
"""

import pytest
import time
from tests.test_client import CFMSTestClient


class TestAccessManagement:
    """Test access grant and revoke operations."""
    
    @pytest.mark.asyncio
    async def test_grant_and_revoke_access(self, authenticated_client: CFMSTestClient):
        """Test granting and revoking access to a document."""
        # Create a test user
        test_username = f"test_user_access_{int(time.time() * 1000)}"
        test_password = "TestPassword123!"
        
        user_response = await authenticated_client.create_user(
            username=test_username,
            password=test_password
        )
        assert user_response["code"] == 200, f"Failed to create user: {user_response}"
        
        # Create a test document
        doc_response = await authenticated_client.create_document(
            title=f"Test Document {int(time.time() * 1000)}"
        )
        assert doc_response["code"] == 200, f"Failed to create document: {doc_response}"
        document_id = doc_response["data"]["document_id"]
        
        # Grant access to the user for the document
        grant_response = await authenticated_client.grant_access(
            entity_type="user",
            entity_identifier=test_username,
            target_type="document",
            target_identifier=document_id,
            access_types=["read"],
            start_time=time.time()
        )
        assert grant_response["code"] == 200, f"Failed to grant access: {grant_response}"
        
        # View access entries for the user
        view_response = await authenticated_client.view_access_entries(
            object_type="user",
            object_identifier=test_username
        )
        assert view_response["code"] == 200, f"Failed to view access entries: {view_response}"
        assert "result" in view_response["data"], "Response missing 'result'"
        
        entries = view_response["data"]["result"]
        assert len(entries) == 1, f"Expected 1 access entry, got {len(entries)}"
        
        entry = entries[0]
        assert "id" in entry, "Access entry missing 'id' field"
        assert entry["entity_type"] == "user"
        assert entry["entity_identifier"] == test_username
        assert entry["target_type"] == "document"
        assert entry["target_identifier"] == document_id
        assert entry["access_type"] == "read"
        
        entry_id = entry["id"]
        
        # Revoke the access
        revoke_response = await authenticated_client.revoke_access(entry_id)
        assert revoke_response["code"] == 200, f"Failed to revoke access: {revoke_response}"
        
        # Verify the access was revoked
        view_after_revoke = await authenticated_client.view_access_entries(
            object_type="user",
            object_identifier=test_username
        )
        assert view_after_revoke["code"] == 200
        entries_after = view_after_revoke["data"]["result"]
        assert len(entries_after) == 0, f"Expected 0 access entries after revoke, got {len(entries_after)}"
        
        # Clean up
        await authenticated_client.delete_document(document_id)
        await authenticated_client.delete_user(test_username)
    
    @pytest.mark.asyncio
    async def test_revoke_nonexistent_entry(self, authenticated_client: CFMSTestClient):
        """Test revoking a non-existent access entry."""
        # Try to revoke an entry that doesn't exist
        revoke_response = await authenticated_client.revoke_access(999999)
        assert revoke_response["code"] == 404, "Should return 404 for non-existent entry"
    
    @pytest.mark.asyncio
    async def test_grant_multiple_access_types(self, authenticated_client: CFMSTestClient):
        """Test granting multiple access types and revoking them individually."""
        # Create a test user
        test_username = f"test_user_multi_{int(time.time() * 1000)}"
        test_password = "TestPassword123!"
        
        user_response = await authenticated_client.create_user(
            username=test_username,
            password=test_password
        )
        assert user_response["code"] == 200
        
        # Create a test document
        doc_response = await authenticated_client.create_document(
            title=f"Test Document Multi {int(time.time() * 1000)}"
        )
        assert doc_response["code"] == 200
        document_id = doc_response["data"]["document_id"]
        
        # Grant multiple access types
        grant_response = await authenticated_client.grant_access(
            entity_type="user",
            entity_identifier=test_username,
            target_type="document",
            target_identifier=document_id,
            access_types=["read", "write"],
            start_time=time.time()
        )
        assert grant_response["code"] == 200
        
        # View access entries - should have 2 entries
        view_response = await authenticated_client.view_access_entries(
            object_type="user",
            object_identifier=test_username
        )
        assert view_response["code"] == 200
        entries = view_response["data"]["result"]
        assert len(entries) == 2, f"Expected 2 access entries, got {len(entries)}"
        
        # Revoke one access type
        first_entry_id = entries[0]["id"]
        revoke_response = await authenticated_client.revoke_access(first_entry_id)
        assert revoke_response["code"] == 200
        
        # Verify only one entry remains
        view_after_revoke = await authenticated_client.view_access_entries(
            object_type="user",
            object_identifier=test_username
        )
        assert view_after_revoke["code"] == 200
        entries_after = view_after_revoke["data"]["result"]
        assert len(entries_after) == 1, f"Expected 1 access entry after revoke, got {len(entries_after)}"
        
        # Clean up - revoke the remaining entry
        remaining_entry_id = entries_after[0]["id"]
        await authenticated_client.revoke_access(remaining_entry_id)
        
        await authenticated_client.delete_document(document_id)
        await authenticated_client.delete_user(test_username)
    
    @pytest.mark.asyncio
    async def test_grant_access_to_group(self, authenticated_client: CFMSTestClient):
        """Test granting and revoking access for a group."""
        # Create a test group
        test_group_name = f"test_group_{int(time.time() * 1000)}"
        
        group_response = await authenticated_client.create_group(
            group_name=test_group_name
        )
        assert group_response["code"] == 200
        
        # Create a test document
        doc_response = await authenticated_client.create_document(
            title=f"Test Document Group {int(time.time() * 1000)}"
        )
        assert doc_response["code"] == 200
        document_id = doc_response["data"]["document_id"]
        
        # Grant access to the group for the document
        grant_response = await authenticated_client.grant_access(
            entity_type="group",
            entity_identifier=test_group_name,
            target_type="document",
            target_identifier=document_id,
            access_types=["read"],
            start_time=time.time()
        )
        assert grant_response["code"] == 200
        
        # View access entries for the group
        view_response = await authenticated_client.view_access_entries(
            object_type="group",
            object_identifier=test_group_name
        )
        assert view_response["code"] == 200
        entries = view_response["data"]["result"]
        assert len(entries) == 1
        
        entry_id = entries[0]["id"]
        
        # Revoke the access
        revoke_response = await authenticated_client.revoke_access(entry_id)
        assert revoke_response["code"] == 200
        
        # Verify the access was revoked
        view_after_revoke = await authenticated_client.view_access_entries(
            object_type="group",
            object_identifier=test_group_name
        )
        assert view_after_revoke["code"] == 200
        entries_after = view_after_revoke["data"]["result"]
        assert len(entries_after) == 0
        
        # Clean up
        await authenticated_client.delete_document(document_id)
        await authenticated_client.send_request("delete_group", {"group_name": test_group_name})
    
    @pytest.mark.asyncio
    async def test_grant_access_to_directory(self, authenticated_client: CFMSTestClient):
        """Test granting and revoking access for a directory."""
        # Create a test user
        test_username = f"test_user_dir_{int(time.time() * 1000)}"
        test_password = "TestPassword123!"
        
        user_response = await authenticated_client.create_user(
            username=test_username,
            password=test_password
        )
        assert user_response["code"] == 200
        
        # Create a test directory
        dir_response = await authenticated_client.create_directory(
            name=f"Test Directory {int(time.time() * 1000)}"
        )
        assert dir_response["code"] == 200
        directory_id = dir_response["data"]["id"]
        
        # Grant access to the user for the directory
        grant_response = await authenticated_client.grant_access(
            entity_type="user",
            entity_identifier=test_username,
            target_type="directory",
            target_identifier=directory_id,
            access_types=["read"],
            start_time=time.time()
        )
        assert grant_response["code"] == 200
        
        # View access entries for the directory
        view_response = await authenticated_client.view_access_entries(
            object_type="directory",
            object_identifier=directory_id
        )
        assert view_response["code"] == 200
        entries = view_response["data"]["result"]
        assert len(entries) == 1
        
        entry_id = entries[0]["id"]
        
        # Revoke the access
        revoke_response = await authenticated_client.revoke_access(entry_id)
        assert revoke_response["code"] == 200
        
        # Verify the access was revoked
        view_after_revoke = await authenticated_client.view_access_entries(
            object_type="directory",
            object_identifier=directory_id
        )
        assert view_after_revoke["code"] == 200
        entries_after = view_after_revoke["data"]["result"]
        assert len(entries_after) == 0
        
        # Clean up
        await authenticated_client.delete_directory(directory_id)
        await authenticated_client.delete_user(test_username)
