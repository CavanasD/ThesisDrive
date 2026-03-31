# CFMS WebSocket Server - Test Suite

This directory contains the automated test suite for the CFMS (Confidential File Management System) WebSocket server.

## Overview

The test suite provides comprehensive coverage of the server's functionality, including:

- **Basic Server Functionality**: Connection handling, server info, and error handling
- **Authentication**: Login, token management, and session handling
- **Document Management**: Create, read, update, delete operations for documents
- **Directory Management**: Directory listing, creation, and deletion
- **User Management**: User CRUD operations and permissions
- **Group Management**: Group CRUD operations and permission management

## Prerequisites

Before running the tests, ensure you have:

1. Python 3.8 or higher installed
2. All project dependencies installed:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-test.txt
   ```

## Running Tests

### Run All Tests

```bash
pytest
```

### Run Specific Test Files

```bash
# Test basic functionality
pytest tests/test_basic.py

# Test document operations
pytest tests/test_documents.py

# Test directory operations
pytest tests/test_directories.py

# Test user management
pytest tests/test_users.py

# Test group management
pytest tests/test_groups.py
```

### Run Specific Test Classes or Functions

```bash
# Run a specific test class
pytest tests/test_basic.py::TestAuthentication

# Run a specific test function
pytest tests/test_basic.py::TestAuthentication::test_login_success
```

### Run Tests with Verbose Output

```bash
pytest -v
```

### Run Tests and Show Print Statements

```bash
pytest -s
```

## Test Structure

### Test Client (`test_client.py`)

The `CFMSTestClient` class provides a convenient interface for interacting with the server during tests. It handles:

- WebSocket connection management
- Request/response formatting
- Authentication token management
- Common API operations

Example usage:

```python
from tests.test_client import CFMSTestClient

# Create and connect client
with CFMSTestClient() as client:
    # Login
    response = client.login("admin", "password")
    
    # Create a document
    response = client.create_document("My Document")
```

### Fixtures (`conftest.py`)

The test suite uses pytest fixtures for common setup:

- `server_process`: Starts the server for testing
- `admin_credentials`: Provides admin login credentials
- `client`: Provides a connected test client
- `authenticated_client`: Provides an authenticated client
- `test_document`: Creates a test document (with cleanup)
- `test_user`: Creates a test user (with cleanup)
- `test_group`: Creates a test group (with cleanup)

### Test Files

Each test file focuses on a specific area of functionality:

- `test_basic.py`: Server basics and authentication
- `test_documents.py`: Document operations
- `test_directories.py`: Directory operations
- `test_users.py`: User management
- `test_groups.py`: Group management

## Test Coverage

The test suite covers:

✅ Server connection and basic info  
✅ Authentication (login, token refresh, invalid credentials)  
✅ Document CRUD operations  
✅ Directory operations  
✅ User management (create, read, delete)  
✅ Group management (create, read, delete)  
✅ Authorization checks (operations without authentication)  
✅ Input validation (empty fields, invalid data)  
✅ Error handling (nonexistent resources, duplicate entries)  

## Writing New Tests

When adding new tests:

1. Place them in the appropriate test file (or create a new one)
2. Use descriptive test names that explain what is being tested
3. Use fixtures for common setup and teardown
4. Clean up any resources created during tests
5. Assert on both success and failure cases
6. Document complex test scenarios

Example:

```python
def test_my_new_feature(authenticated_client: CFMSTestClient):
    """Test description explaining what this test verifies."""
    # Arrange
    data = {"key": "value"}
    
    # Act
    response = authenticated_client.some_operation(data)
    
    # Assert
    assert response["code"] == 200
    assert "expected_field" in response["data"]
```

## Continuous Integration

These tests are designed to run in CI/CD pipelines. The test suite:

- Automatically starts and stops the server
- Cleans up resources after each test
- Provides clear error messages for debugging
- Can run in isolation or as a full suite

## Troubleshooting

### Server Won't Start

If tests fail because the server won't start:

1. Check that `config.toml` exists (it will be created from `config.toml.sample`)
2. Ensure the SSL certificate directory exists: `mkdir -p content/ssl`
3. Check for port conflicts (default: 5104)

### Tests Fail Intermittently

If tests fail randomly:

1. Increase the server startup wait time in `conftest.py`
2. Check for resource cleanup issues
3. Ensure tests are properly isolated

### Authentication Errors

If authentication tests fail:

1. Verify `admin_password.txt` is being created
2. Check that the database is being initialized properly
3. Ensure the token is being properly stored and passed

## Contributing

When contributing tests:

1. Follow the existing test structure and naming conventions
2. Ensure tests are independent and can run in any order
3. Add appropriate assertions for both success and error cases
4. Document any special setup or requirements
5. Run the full test suite before submitting changes

## License

These tests are part of the CFMS project and follow the same license as the main project.
