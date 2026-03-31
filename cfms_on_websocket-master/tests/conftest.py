"""
Pytest configuration and fixtures for CFMS test suite - Rewritten for robustness.
"""

import os
import pytest
import pytest_asyncio
import subprocess
import time
import threading
import sys
import asyncio
from typing import Generator, AsyncGenerator
from tests.test_client import CFMSTestClient


def log_server_output(process: subprocess.Popen, log_dir: str = "test_logs"):
    """
    Continuously read and log server output to individual files.
    
    This function runs in separate threads to capture the server's
    stdout and stderr and save them to individual files for clarity.
    
    Args:
        process: The subprocess.Popen object for the server
        log_dir: Directory to save log files (default: "test_logs")
    
    Returns:
        Tuple of (stdout_thread, stderr_thread, stdout_file, stderr_file, stop_event)
    """
    # Create log directory if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)
    
    # Create timestamped log files
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    stdout_path = os.path.join(log_dir, f"server_stdout_{timestamp}.log")
    stderr_path = os.path.join(log_dir, f"server_stderr_{timestamp}.log")
    
    # Open log files
    stdout_file = open(stdout_path, 'w', encoding='utf-8', buffering=1)
    stderr_file = open(stderr_path, 'w', encoding='utf-8', buffering=1)
    
    print(f"\n[TEST SETUP] Server stdout logging to: {stdout_path}", file=sys.stderr)
    print(f"[TEST SETUP] Server stderr logging to: {stderr_path}", file=sys.stderr)
    
    # Create a stop event for graceful shutdown
    stop_event = threading.Event()
    
    def read_stream(stream, output_file, stream_name):
        try:
            while not stop_event.is_set():
                line = stream.readline()
                if not line:
                    break
                try:
                    output_file.write(line)
                    output_file.flush()
                except (ValueError, OSError):
                    # File was closed, exit gracefully
                    break
        except Exception as e:
            # Only log if file is still open
            try:
                error_msg = f"Error reading {stream_name}: {e}\n"
                output_file.write(error_msg)
                output_file.flush()
            except:
                pass
            print(f"[SERVER LOG] Error in {stream_name}: {e}", file=sys.stderr)
    
    # Start threads as daemon so they cannot block Python exit
    stdout_thread = threading.Thread(
        target=read_stream, 
        args=(process.stdout, stdout_file, "STDOUT"),
        daemon=True
    )
    stderr_thread = threading.Thread(
        target=read_stream,
        args=(process.stderr, stderr_file, "STDERR"),
        daemon=True
    )
    
    stdout_thread.start()
    stderr_thread.start()
    
    return stdout_thread, stderr_thread, stdout_file, stderr_file, stop_event


@pytest.fixture(scope="session")
def server_process() -> Generator[subprocess.Popen, None, None]:
    """
    Start the CFMS server for testing and tear it down after tests complete.
    
    This fixture starts the server in a subprocess with improved error handling
    and continuous logging of server output.
    """
    # Ensure config file exists
    src_config_file = "src/config.toml"
    if not os.path.exists(src_config_file):
        import shutil
        if not os.path.exists("src/config.toml.sample"):
            pytest.fail("Config sample file not found: src/config.toml.sample")
        shutil.copy("src/config.toml.sample", src_config_file)
    
    # Read and modify config for testing
    try:
        with open(src_config_file, "r", encoding='utf-8') as f:
            config_content = f.read()
    except Exception as e:
        pytest.fail(f"Failed to read config file: {e}")
    
    # Apply test-specific config changes
    config_changes = {
        "debug = false": "debug = true",
        "enable_passwd_force_expiration = true": "enable_passwd_force_expiration = false",
        "require_passwd_enforcement_changes = true": "require_passwd_enforcement_changes = false",
        "dualstack_ipv6 = true": "dualstack_ipv6 = false",
    }
    
    for old, new in config_changes.items():
        config_content = config_content.replace(old, new)
    
    try:
        with open(src_config_file, "w", encoding='utf-8') as f:
            f.write(config_content)
    except Exception as e:
        pytest.fail(f"Failed to write config file: {e}")
    
    # Clean up previous test artifacts
    artifacts = ["init", "app.db", "admin_password.txt"]
    for artifact in artifacts:
        artifact_path = os.path.join("src", artifact)
        if os.path.exists(artifact_path):
            try:
                os.remove(artifact_path)
            except Exception as e:
                pytest.fail(f"Failed to remove artifact {artifact}: {e}")
    
    # Ensure necessary directories exist
    directories = ["src/content/ssl", "src/content/logs"]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
    
    # Start the server
    print("\n[TEST SETUP] Starting CFMS server...", file=sys.stderr)
    try:
        process = subprocess.Popen(
            ["uv", "run", "python", "main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
            cwd=os.path.join(os.getcwd(), "src")
        )
    except Exception as e:
        pytest.fail(f"Failed to start server process: {e}")
    
    # Start logging server output in background threads
    stdout_thread, stderr_thread, stdout_file, stderr_file, stop_event = log_server_output(process, "test_logs")
    
    # Wait for server to be ready
    max_wait = 20  # Increased timeout
    wait_interval = 0.5
    waited = 0
    
    print(f"[TEST SETUP] Waiting up to {max_wait} seconds for server to initialize...", file=sys.stderr)
    while waited < max_wait:
        time.sleep(wait_interval)
        waited += wait_interval
        
        # Check if process crashed
        if process.poll() is not None:
            stop_event.set()  # Signal threads to stop
            time.sleep(0.5)  # Give logging threads time to catch up
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            stdout_file.close()
            stderr_file.close()
            pytest.fail(
                f"Server failed to start (exit code: {process.returncode}).\n"
                f"Check the server log files in test_logs/ directory for details."
            )
        
        # Check if initialization is complete
        if os.path.exists("src/admin_password.txt"):
            # Give server additional time to fully start
            print("[TEST SETUP] Server initialization detected, waiting for full startup...", file=sys.stderr)
            time.sleep(2)
            break
    
    # Verify server started successfully
    if not os.path.exists("src/admin_password.txt"):
        try:
            process.terminate()
            process.wait(timeout=5)
        except:
            process.kill()
        stop_event.set()  # Signal threads to stop
        time.sleep(0.5)  # Give logging threads time to catch up
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        stdout_file.close()
        stderr_file.close()
        pytest.fail(
            f"Server initialization timed out after {max_wait} seconds.\n"
            f"Check the server log files in test_logs/ directory for details."
        )
    
    print("[TEST SETUP] Server started successfully!", file=sys.stderr)
    
    # Store log files and threads in process object for cleanup
    process._log_threads = (stdout_thread, stderr_thread, stop_event)
    process._log_files = (stdout_file, stderr_file)
    
    yield process
    
    # Cleanup: terminate the server
    print("\n[TEST CLEANUP] Shutting down server...", file=sys.stderr)
    try:
        process.terminate()
        process.wait(timeout=5)
        print("[TEST CLEANUP] Server terminated gracefully.", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("[TEST CLEANUP] Server did not terminate gracefully, forcing kill...", file=sys.stderr)
        process.kill()
        try:
            process.wait(timeout=2)
        except:
            pass
    
    # Close process pipes first so readline() in log threads returns EOF
    try:
        stdout_thread, stderr_thread, stop_event = process._log_threads
        stdout_file, stderr_file = process._log_files
        
        stop_event.set()
        for pipe in (process.stdout, process.stderr):
            try:
                if pipe: pipe.close()
            except Exception:
                pass
        
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        
        stdout_file.close()
        stderr_file.close()
        print("[TEST CLEANUP] Log threads and files closed.", file=sys.stderr)
    except Exception as e:
        print(f"[TEST CLEANUP] Error during log cleanup: {e}", file=sys.stderr)
    
    print("[TEST CLEANUP] Server cleanup complete.", file=sys.stderr)


@pytest.fixture(scope="session")
def admin_credentials(server_process) -> dict:
    """
    Get admin credentials from the generated password file.
    """
    password_file = "src/admin_password.txt"
    
    if not os.path.exists(password_file):
        pytest.fail("Admin password file not found after server started")
    
    try:
        with open(password_file, "r", encoding="utf-8") as f:
            password = f.read().strip()
    except Exception as e:
        pytest.fail(f"Failed to read admin password: {e}")
    
    if not password:
        pytest.fail("Admin password file is empty")
    
    return {
        "username": "admin",
        "password": password
    }


@pytest_asyncio.fixture
async def client(server_process) -> AsyncGenerator[CFMSTestClient, None]:
    """
    Provide a connected test client for each test.
    """
    test_client = CFMSTestClient()
    
    # Try to connect with retries
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            await test_client.connect()
            break
        except (ConnectionRefusedError, TimeoutError, OSError) as e:
            if attempt == max_attempts - 1:
                pytest.fail(f"Failed to connect to server after {max_attempts} attempts: {e}")
            await asyncio.sleep(1)
    
    yield test_client
    
    # Cleanup
    try:
        await test_client.disconnect()
    except:
        pass


@pytest_asyncio.fixture
async def authenticated_client(client: CFMSTestClient, admin_credentials: dict) -> CFMSTestClient:
    """
    Provide an authenticated test client with admin credentials.
    """
    try:
        response = await client.login(
            admin_credentials["username"],
            admin_credentials["password"]
        )
    except Exception as e:
        pytest.fail(f"Login request failed with exception: {e}")
    
    if response.get("code") != 200:
        pytest.fail(f"Login failed: {response}")
    
    return client


@pytest_asyncio.fixture
async def unauthenticated_client(server_process) -> AsyncGenerator[CFMSTestClient, None]:
    """
    Provide an unauthenticated test client (just connected, not logged in).
    """
    test_client = CFMSTestClient()
    
    # Try to connect with retries
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            await test_client.connect()
            break
        except (ConnectionRefusedError, TimeoutError, OSError) as e:
            if attempt == max_attempts - 1:
                pytest.fail(f"Failed to connect to server after {max_attempts} attempts: {e}")
            await asyncio.sleep(1)
    
    yield test_client
    
    # Cleanup
    try:
        await test_client.disconnect()
    except:
        pass


@pytest_asyncio.fixture
async def test_document(authenticated_client: CFMSTestClient) -> AsyncGenerator[dict, None]:
    """
    Create a test document and clean it up after the test.
    """
    try:
        response = await authenticated_client.create_document("Test Document")
    except Exception as e:
        pytest.fail(f"Failed to create test document: {e}")
    
    if response.get("code") != 200:
        pytest.fail(f"Failed to create test document: {response}")
    
    document_id = response["data"]["document_id"]
    task_id = response["data"]["task_data"]["task_id"]
    
    # Upload file to activate the document
    try:
        await authenticated_client.upload_file_to_server(task_id, "./pyproject.toml")
    except Exception as e:
        # Try to cleanup before failing
        try:
            await authenticated_client.delete_document(document_id)
        except:
            pass
        pytest.fail(f"Failed to upload file to document: {e}")
    
    yield {
        "document_id": document_id,
        "title": "Test Document"
    }
    
    # Cleanup
    try:
        await authenticated_client.delete_document(document_id)
    except Exception:
        pass  # Ignore cleanup errors


@pytest_asyncio.fixture
async def test_user(authenticated_client: CFMSTestClient) -> AsyncGenerator[dict, None]:
    """
    Create a test user and clean it up after the test.
    """
    username = f"test_user_{int(time.time() * 1000)}"
    password = "TestPassword123!"
    
    try:
        response = await authenticated_client.create_user(
            username=username,
            password=password,
            nickname="Test User"
        )
    except Exception as e:
        pytest.fail(f"Failed to create test user: {e}")
    
    if response.get("code") != 200:
        pytest.fail(f"Failed to create test user: {response}")
    
    yield {
        "username": username,
        "password": password,
        "nickname": "Test User"
    }
    
    # Cleanup
    try:
        await authenticated_client.delete_user(username)
    except Exception:
        pass


@pytest_asyncio.fixture
async def test_group(authenticated_client: CFMSTestClient) -> AsyncGenerator[dict, None]:
    """
    Create a test group and clean it up after the test.
    """
    group_name = f"test_group_{int(time.time() * 1000)}"
    
    try:
        response = await authenticated_client.create_group(
            group_name=group_name,
            permissions=[]
        )
    except Exception as e:
        pytest.fail(f"Failed to create test group: {e}")
    
    if response.get("code") != 200:
        pytest.fail(f"Failed to create test group: {response}")
    
    yield {
        "group_name": group_name
    }
    
    # Cleanup
    try:
        await authenticated_client.send_request("delete_group", {"group_name": group_name})
    except Exception:
        pass
