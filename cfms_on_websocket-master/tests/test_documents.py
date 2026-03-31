"""
Tests for document management operations - Rewritten with improved robustness.
"""

import pytest
from tests.test_client import CFMSTestClient


class TestDocumentOperations:
    """Test document CRUD operations with comprehensive validation."""
    
    @pytest.mark.asyncio
    async def test_create_document(self, authenticated_client: CFMSTestClient):
        """Test creating a new document and verify response structure."""
        try:
            response = await authenticated_client.create_document("Test Document")
        except Exception as e:
            pytest.fail(f"create_document() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 200, \
            f"Document creation failed: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert "document_id" in response["data"], "Response missing 'document_id'"
        assert isinstance(response["data"]["document_id"], str), "document_id should be a string"
        assert len(response["data"]["document_id"]) > 0, "document_id should not be empty"
        
        # Cleanup
        document_id = response["data"]["document_id"]
        try:
            await authenticated_client.delete_document(document_id)
        except Exception:
            pass
    
    @pytest.mark.asyncio
    async def test_get_document(self, authenticated_client: CFMSTestClient, test_document: dict):
        """Test retrieving a document by ID."""
        try:
            response = await authenticated_client.get_document(test_document["document_id"])
        except Exception as e:
            pytest.fail(f"get_document() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 200, \
            f"Failed to get document: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_document(self, authenticated_client: CFMSTestClient):
        """Test retrieving a document that doesn't exist returns appropriate error."""
        try:
            response = await authenticated_client.get_document("nonexistent_doc_id_xyz_123")
        except Exception as e:
            pytest.fail(f"get_document() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] != 200, \
            "Getting nonexistent document should not return 200"
        assert response["code"] in [400, 404], \
            f"Expected 400 or 404 for nonexistent document, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_get_document_info(self, authenticated_client: CFMSTestClient, test_document: dict):
        """Test getting document metadata."""
        try:
            response = await authenticated_client.get_document_info(test_document["document_id"])
        except Exception as e:
            pytest.fail(f"get_document_info() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 200, \
            f"Failed to get document info: {response.get('message', '')}"
        
        assert "data" in response, "Response missing 'data'"
        assert isinstance(response["data"], dict), "'data' should be a dictionary"
    
    @pytest.mark.asyncio
    async def test_rename_document(self, authenticated_client: CFMSTestClient, test_document: dict):
        """Test renaming a document and verifying the change."""
        new_title = "Renamed Test Document XYZ"
        
        try:
            response = await authenticated_client.rename_document(
                test_document["document_id"],
                new_title
            )
        except Exception as e:
            pytest.fail(f"rename_document() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code' field"
        assert response["code"] == 200, \
            f"Failed to rename document: {response.get('message', '')}"
        
        # Verify the rename
        try:
            info_response = await authenticated_client.get_document_info(test_document["document_id"])
        except Exception as e:
            pytest.fail(f"get_document_info() raised an exception: {e}")
        
        assert info_response.get("code") == 200, "Failed to verify document rename"
        assert info_response["data"]["title"] == new_title, \
            f"Document title not updated: expected '{new_title}', got '{info_response['data'].get('title')}'"
    
    @pytest.mark.asyncio
    async def test_delete_document(self, authenticated_client: CFMSTestClient):
        """Test deleting a document and verify it's removed."""
        # Create a document to delete
        try:
            create_response = await authenticated_client.create_document("Document to Delete")
        except Exception as e:
            pytest.fail(f"Failed to create document for deletion test: {e}")
        
        assert create_response.get("code") == 200, "Failed to create test document"
        document_id = create_response["data"]["document_id"]
        
        # Delete it
        try:
            delete_response = await authenticated_client.delete_document(document_id)
        except Exception as e:
            pytest.fail(f"delete_document() raised an exception: {e}")
        
        assert isinstance(delete_response, dict), "Response should be a dictionary"
        assert "code" in delete_response, "Response missing 'code'"
        assert delete_response["code"] == 200, \
            f"Failed to delete document: {delete_response.get('message', '')}"
        
        # Verify it's gone
        try:
            get_response = await authenticated_client.get_document(document_id)
        except Exception as e:
            pytest.fail(f"get_document() raised an exception during verification: {e}")
        
        assert get_response.get("code") != 200, \
            "Document should not be retrievable after deletion"
    
    @pytest.mark.asyncio
    async def test_create_document_with_empty_title(self, authenticated_client: CFMSTestClient):
        """Test that creating a document with empty title fails validation."""
        try:
            response = await authenticated_client.create_document("")
        except Exception as e:
            pytest.fail(f"create_document() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 400, \
            f"Expected 400 for empty title, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_create_multiple_documents(self, authenticated_client: CFMSTestClient):
        """Test creating multiple documents successfully."""
        document_ids = []
        num_documents = 3
        
        try:
            for i in range(num_documents):
                response = await authenticated_client.create_document(f"Test Document {i}")
                assert response.get("code") == 200, \
                    f"Failed to create document {i}: {response}"
                
                # Upload file to activate the document
                task_id = response["data"]["task_data"]["task_id"]
                await authenticated_client.upload_file_to_server(task_id, "./pyproject.toml")
                
                document_ids.append(response["data"]["document_id"])
            
            # Verify all documents exist
            for doc_id in document_ids:
                response = await authenticated_client.get_document_info(doc_id)
                assert response.get("code") == 200, \
                    f"Document {doc_id} not found after creation"
        finally:
            # Cleanup all documents
            for doc_id in document_ids:
                try:
                    await authenticated_client.delete_document(doc_id)
                except Exception:
                    pass


class TestDocumentWithoutAuth:
    """Test that document operations properly require authentication."""
    
    @pytest.mark.asyncio
    async def test_create_document_without_auth(self, client: CFMSTestClient):
        """Test that creating a document requires authentication."""
        try:
            response = await client.send_request(
                "create_document",
                {"title": "Test Document"},
                include_auth=False
            )
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 401, \
            f"Expected 401 for unauthenticated request, got {response.get('code')}"
    
    @pytest.mark.asyncio
    async def test_get_document_without_auth(self, client: CFMSTestClient):
        """Test that getting a document requires authentication."""
        try:
            response = await client.send_request(
                "get_document",
                {"document_id": "test_doc_id"},
                include_auth=False
            )
        except Exception as e:
            pytest.fail(f"send_request() raised an exception: {e}")
        
        assert isinstance(response, dict), "Response should be a dictionary"
        assert "code" in response, "Response missing 'code'"
        assert response["code"] == 401, \
            f"Expected 401 for unauthenticated request, got {response.get('code')}"
