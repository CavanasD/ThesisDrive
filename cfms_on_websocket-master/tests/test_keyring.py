"""
Tests for keyring operations.
"""

import pytest
from tests.test_client import CFMSTestClient


class TestKeyringOperations:
    """Test keyring CRUD operations for the authenticated user."""

    @pytest.mark.asyncio
    async def test_upload_keyring(self, authenticated_client: CFMSTestClient):
        """Test uploading a new key to the keyring."""
        response = await authenticated_client.upload_keyring(
            key_content="encrypted_dek_value_abc123",
            label="test-key",
        )
        assert response.get("code") == 200, f"Expected 200, got: {response}"
        assert "id" in response.get("data", {}), "Response must include id"

        # Cleanup
        key_id = response["data"]["id"]
        await authenticated_client.delete_keyring(key_id)

    @pytest.mark.asyncio
    async def test_get_keyring(self, authenticated_client: CFMSTestClient):
        """Test retrieving a key by its id."""
        upload_resp = await authenticated_client.upload_keyring(
            key_content="get_test_content",
            label="get-test",
        )
        assert upload_resp.get("code") == 200
        key_id = upload_resp["data"]["id"]

        get_resp = await authenticated_client.get_keyring(key_id)
        assert get_resp.get("code") == 200, f"Expected 200, got: {get_resp}"
        data = get_resp.get("data", {})
        assert data["key_id"] == key_id
        assert data["key_content"] == "get_test_content"
        assert data["label"] == "get-test"

        # Cleanup
        await authenticated_client.delete_keyring(key_id)

    @pytest.mark.asyncio
    async def test_get_nonexistent_keyring(self, authenticated_client: CFMSTestClient):
        """Test that retrieving a non-existent key returns 404."""
        response = await authenticated_client.get_keyring("nonexistent_key_id_xyz")
        assert response.get("code") == 404, f"Expected 404, got: {response}"

    @pytest.mark.asyncio
    async def test_delete_keyring(self, authenticated_client: CFMSTestClient):
        """Test deleting a key from the keyring."""
        upload_resp = await authenticated_client.upload_keyring(
            key_content="delete_test_content",
        )
        assert upload_resp.get("code") == 200
        key_id = upload_resp["data"]["id"]

        del_resp = await authenticated_client.delete_keyring(key_id)
        assert del_resp.get("code") == 200, f"Expected 200, got: {del_resp}"

        # Verify deletion
        get_resp = await authenticated_client.get_keyring(key_id)
        assert get_resp.get("code") == 404, "Key should not exist after deletion"

    @pytest.mark.asyncio
    async def test_list_keyrings(self, authenticated_client: CFMSTestClient):
        """Test listing all keys in the keyring."""
        upload_resp = await authenticated_client.upload_keyring(
            key_content="list_test_content",
            label="list-test",
        )
        assert upload_resp.get("code") == 200
        key_id = upload_resp["data"]["id"]

        list_resp = await authenticated_client.list_keyrings()
        assert list_resp.get("code") == 200, f"Expected 200, got: {list_resp}"
        keys = list_resp.get("data", {}).get("keys", [])
        assert isinstance(keys, list)
        key_ids = [k["id"] for k in keys]
        assert key_id in key_ids, "Uploaded key should appear in listing"

        # key_content must NOT be exposed in listing
        for k in keys:
            assert "key_content" not in k, "key_content must not be in list response"

        # Cleanup
        await authenticated_client.delete_keyring(key_id)

    @pytest.mark.asyncio
    async def test_set_preference_dek(self, authenticated_client: CFMSTestClient):
        """Test designating a key as the preference DEK."""
        upload_resp = await authenticated_client.upload_keyring(
            key_content="preference_dek_content",
        )
        assert upload_resp.get("code") == 200
        key_id = upload_resp["data"]["id"]

        set_resp = await authenticated_client.set_preference_keyring(key_id)
        assert set_resp.get("code") == 200, f"Expected 200, got: {set_resp}"

        list_resp = await authenticated_client.list_keyrings()
        keys = {k["id"]: k for k in list_resp["data"]["keys"]}
        assert keys[key_id]["is_preference_dek"] == True, "Key should be marked as preference DEK"

        # Cleanup
        await authenticated_client.delete_keyring(key_id)

    @pytest.mark.asyncio
    async def test_set_preference_dek_replaces_previous(self, authenticated_client: CFMSTestClient):
        """Setting a new preference DEK must replace the previous one."""
        first_resp = await authenticated_client.upload_keyring(
            key_content="first_dek",
        )
        assert first_resp.get("code") == 200
        first_id = first_resp["data"]["id"]

        second_resp = await authenticated_client.upload_keyring(
            key_content="second_dek",
        )
        assert second_resp.get("code") == 200
        second_id = second_resp["data"]["id"]

        # Set first as preference DEK, then switch to second
        await authenticated_client.set_preference_keyring(first_id)
        await authenticated_client.set_preference_keyring(second_id)

        list_resp = await authenticated_client.list_keyrings()
        keys = {k["id"]: k for k in list_resp["data"]["keys"]}

        assert keys[first_id]["is_preference_dek"] == False, "Previous preference DEK should be demoted"
        assert keys[second_id]["is_preference_dek"] == True, "New preference DEK should be set"

        # Cleanup
        await authenticated_client.delete_keyring(first_id)
        await authenticated_client.delete_keyring(second_id)

    @pytest.mark.asyncio
    async def test_preference_dek_returned_on_login(
        self,
        client: CFMSTestClient,
        admin_credentials: dict,
        authenticated_client: CFMSTestClient,
    ):
        """The preference DEK should be included in the login response when set."""
        upload_resp = await authenticated_client.upload_keyring(
            key_content="login_dek_content",
        )
        assert upload_resp.get("code") == 200
        key_id = upload_resp["data"]["id"]

        set_resp = await authenticated_client.set_preference_keyring(key_id)
        assert set_resp.get("code") == 200

        # Login with a fresh client to get the login response data
        login_resp = await client.login(
            admin_credentials["username"],
            admin_credentials["password"],
        )
        assert login_resp.get("code") == 200
        data = login_resp.get("data", {})
        assert "preference_dek" in data, "Login response must include preference_dek when set"
        assert data["preference_dek"]["key_id"] == key_id
        assert data["preference_dek"]["key_content"] == "login_dek_content"

        # Cleanup
        await authenticated_client.delete_keyring(key_id)

    @pytest.mark.asyncio
    async def test_no_preference_dek_not_in_login(
        self,
        client: CFMSTestClient,
        admin_credentials: dict,
        authenticated_client: CFMSTestClient,
    ):
        """When no preference DEK is set, login response should not contain preference_dek."""
        # Delete all keys so no preference DEK is set
        list_resp = await authenticated_client.list_keyrings()
        for k in list_resp.get("data", {}).get("keys", []):
            await authenticated_client.delete_keyring(k["id"])

        login_resp = await client.login(
            admin_credentials["username"],
            admin_credentials["password"],
        )
        assert login_resp.get("code") == 200
        data = login_resp.get("data", {})
        assert "preference_dek" not in data, (
            "Login response must not include preference_dek when none is set"
        )


class TestKeyringWithoutAuth:
    """Keyring operations require authentication."""

    @pytest.mark.asyncio
    async def test_upload_keyring_without_auth(self, client: CFMSTestClient):
        response = await client.send_request(
            "upload_user_key",
            {"content": "test"},
            include_auth=False,
        )
        assert response.get("code") == 401

    @pytest.mark.asyncio
    async def test_get_keyring_without_auth(self, client: CFMSTestClient):
        response = await client.send_request(
            "get_user_key",
            {"id": "someid"},
            include_auth=False,
        )
        assert response.get("code") == 401

    @pytest.mark.asyncio
    async def test_delete_keyring_without_auth(self, client: CFMSTestClient):
        response = await client.send_request(
            "delete_user_key",
            {"id": "someid"},
            include_auth=False,
        )
        assert response.get("code") == 401

    @pytest.mark.asyncio
    async def test_list_keyrings_without_auth(self, client: CFMSTestClient):
        response = await client.send_request(
            "list_user_keys",
            {},
            include_auth=False,
        )
        assert response.get("code") == 401

    @pytest.mark.asyncio
    async def test_set_preference_keyring_without_auth(self, client: CFMSTestClient):
        response = await client.send_request(
            "set_user_preference_dek",
            {"id": "someid"},
            include_auth=False,
        )
        assert response.get("code") == 401
