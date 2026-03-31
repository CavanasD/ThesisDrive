"""
Tests for directory management operations.
"""

import pytest
from tests.test_client import CFMSTestClient


class TestDirectoryOperations:
    """Test directory operations."""
    
    @pytest.mark.asyncio
    async def test_list_directory_root(self, authenticated_client: CFMSTestClient):
        """Test listing the root directory."""
        response = await authenticated_client.list_directory()
        
        assert response["code"] == 200
        assert "data" in response
    
    @pytest.mark.asyncio
    async def test_create_directory(self, authenticated_client: CFMSTestClient):
        """Test creating a new directory."""
        dir_name = "Test Directory"
        response = await authenticated_client.create_directory(dir_name)
        
        # Directory creation might succeed or fail based on permissions
        # We just check the response is valid
        assert "code" in response
        assert "data" in response
        
        if response["code"] == 200:
            # Cleanup if created successfully
            directory_id = response["data"].get("id")
            if directory_id:
                try:
                    await authenticated_client.delete_directory(directory_id)
                except Exception:
                    pass
    
    @pytest.mark.asyncio
    async def test_create_directory_with_empty_name(self, authenticated_client: CFMSTestClient):
        """Test creating a directory with an empty name."""
        response = await authenticated_client.create_directory("")
        
        # Should fail validation
        assert response["code"] == 400
    
    @pytest.mark.asyncio
    async def test_delete_directory(self, authenticated_client: CFMSTestClient):
        """Test deleting a directory."""
        # First create a directory
        create_response = await authenticated_client.create_directory("Directory to Delete")
        
        if create_response["code"] == 200:
            directory_id = create_response["data"]["id"]
            
            # Delete it
            delete_response = await authenticated_client.delete_directory(directory_id)
            
            # Should get a response (success or failure is implementation-dependent)
            assert "code" in delete_response
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_directory(self, authenticated_client: CFMSTestClient):
        """Test deleting a directory that doesn't exist."""
        response = await authenticated_client.delete_directory("nonexistent_folder_id")
        
        assert response["code"] != 200
    
    @pytest.mark.asyncio
    async def test_list_directory_contents(self, authenticated_client: CFMSTestClient):
        """Test listing directory contents after creating items."""
        # Create a test directory
        dir_response = await authenticated_client.create_directory("Test List Dir")
        
        if dir_response["code"] == 200:
            directory_id = dir_response["data"]["id"]
            
            try:
                # Create a document in the directory
                doc_response = await authenticated_client.create_document(
                    "Test Doc in Dir",
                    folder_id=directory_id
                )
                
                if doc_response["code"] == 200:
                    # List the directory
                    list_response = await authenticated_client.list_directory(directory_id)
                    
                    assert list_response["code"] == 200
                    assert "data" in list_response
                    
                    # Cleanup document
                    try:
                        await authenticated_client.delete_document(
                            doc_response["data"]["document_id"]
                        )
                    except Exception:
                        pass
            finally:
                # Cleanup directory
                try:
                    await authenticated_client.delete_directory(directory_id)
                except Exception:
                    pass


class TestDirectoryMove:
    """Test directory move operations."""
    
    @pytest.mark.asyncio
    async def test_move_directory_to_root(self, authenticated_client: CFMSTestClient):
        """Test moving a directory to root."""
        # Create a parent and a child directory
        parent_response = await authenticated_client.create_directory("Parent Dir")
        
        if parent_response["code"] == 200:
            parent_id = parent_response["data"]["id"]
            
            try:
                child_response = await authenticated_client.create_directory(
                    "Child Dir", parent_id=parent_id
                )
                
                if child_response["code"] == 200:
                    child_id = child_response["data"]["id"]
                    
                    try:
                        # Move child to root
                        move_response = await authenticated_client.move_directory(
                            child_id, None
                        )
                        
                        # Should succeed
                        assert move_response["code"] == 200
                    finally:
                        try:
                            await authenticated_client.delete_directory(child_id)
                        except Exception:
                            pass
            finally:
                try:
                    await authenticated_client.delete_directory(parent_id)
                except Exception:
                    pass
    
    @pytest.mark.asyncio
    async def test_move_directory_into_itself(self, authenticated_client: CFMSTestClient):
        """Test that moving a directory into itself is prevented."""
        # Create a directory
        dir_response = await authenticated_client.create_directory("Test Dir")
        
        if dir_response["code"] == 200:
            dir_id = dir_response["data"]["id"]
            
            try:
                # Try to move directory into itself
                move_response = await authenticated_client.move_directory(
                    dir_id, dir_id
                )
                
                # Should fail with 400
                assert move_response["code"] == 400
                assert "subdirectory" in move_response["message"].lower()
            finally:
                try:
                    await authenticated_client.delete_directory(dir_id)
                except Exception:
                    pass
    
    @pytest.mark.asyncio
    async def test_move_directory_into_child(self, authenticated_client: CFMSTestClient):
        """Test that moving a directory into its child is prevented."""
        # Create parent and child
        parent_response = await authenticated_client.create_directory("Parent Dir")
        
        if parent_response["code"] == 200:
            parent_id = parent_response["data"]["id"]
            
            try:
                child_response = await authenticated_client.create_directory(
                    "Child Dir", parent_id=parent_id
                )
                
                if child_response["code"] == 200:
                    child_id = child_response["data"]["id"]
                    
                    try:
                        # Try to move parent into child
                        move_response = await authenticated_client.move_directory(
                            parent_id, child_id
                        )
                        
                        # Should fail with 400
                        assert move_response["code"] == 400
                        assert "subdirectory" in move_response["message"].lower()
                    finally:
                        try:
                            await authenticated_client.delete_directory(child_id)
                        except Exception:
                            pass
            finally:
                try:
                    await authenticated_client.delete_directory(parent_id)
                except Exception:
                    pass
    
    @pytest.mark.asyncio
    async def test_move_directory_into_grandchild(self, authenticated_client: CFMSTestClient):
        """Test that moving a directory into its grandchild is prevented."""
        # Create parent, child, and grandchild
        parent_response = await authenticated_client.create_directory("Parent Dir")
        
        if parent_response["code"] == 200:
            parent_id = parent_response["data"]["id"]
            
            try:
                child_response = await authenticated_client.create_directory(
                    "Child Dir", parent_id=parent_id
                )
                
                if child_response["code"] == 200:
                    child_id = child_response["data"]["id"]
                    
                    try:
                        grandchild_response = await authenticated_client.create_directory(
                            "Grandchild Dir", parent_id=child_id
                        )
                        
                        if grandchild_response["code"] == 200:
                            grandchild_id = grandchild_response["data"]["id"]
                            
                            try:
                                # Try to move parent into grandchild
                                move_response = await authenticated_client.move_directory(
                                    parent_id, grandchild_id
                                )
                                
                                # Should fail with 400
                                assert move_response["code"] == 400
                                assert "subdirectory" in move_response["message"].lower()
                            finally:
                                try:
                                    await authenticated_client.delete_directory(grandchild_id)
                                except Exception:
                                    pass
                    finally:
                        try:
                            await authenticated_client.delete_directory(child_id)
                        except Exception:
                            pass
            finally:
                try:
                    await authenticated_client.delete_directory(parent_id)
                except Exception:
                    pass
    
    @pytest.mark.asyncio
    async def test_move_directory_to_sibling(self, authenticated_client: CFMSTestClient):
        """Test moving a directory to a sibling location (should succeed)."""
        # Create parent with two children
        parent_response = await authenticated_client.create_directory("Parent Dir")
        
        if parent_response["code"] == 200:
            parent_id = parent_response["data"]["id"]
            
            try:
                child1_response = await authenticated_client.create_directory(
                    "Child Dir 1", parent_id=parent_id
                )
                child2_response = await authenticated_client.create_directory(
                    "Child Dir 2", parent_id=parent_id
                )
                
                if child1_response["code"] == 200 and child2_response["code"] == 200:
                    child1_id = child1_response["data"]["id"]
                    child2_id = child2_response["data"]["id"]
                    
                    try:
                        # Move child2 into child1 (should succeed)
                        move_response = await authenticated_client.move_directory(
                            child2_id, child1_id
                        )
                        
                        # Should succeed
                        assert move_response["code"] == 200
                    finally:
                        try:
                            await authenticated_client.delete_directory(child1_id)
                        except Exception:
                            pass
                        try:
                            await authenticated_client.delete_directory(child2_id)
                        except Exception:
                            pass
            finally:
                try:
                    await authenticated_client.delete_directory(parent_id)
                except Exception:
                    pass


class TestDirectoryWithoutAuth:
    """Test that directory operations require authentication."""
    
    @pytest.mark.asyncio
    async def test_list_directory_without_auth(self, client: CFMSTestClient):
        """Test that listing directories requires authentication."""
        response = await client.send_request(
            "list_directory",
            {"folder_id": None},
            include_auth=False
        )
        
        assert response["code"] == 401
    
    @pytest.mark.asyncio
    async def test_create_directory_without_auth(self, client: CFMSTestClient):
        """Test that creating a directory requires authentication."""
        response = await client.send_request(
            "create_directory",
            {"name": "Test"},
            include_auth=False
        )
        
        assert response["code"] == 401
