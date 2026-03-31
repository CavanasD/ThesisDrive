"""
Test client for CFMS WebSocket Server.

This module provides a reusable WebSocket client for testing the CFMS server.
"""

import hashlib
import orjson
import mmap
import os
import secrets
import ssl
import asyncio
import time
import struct
import queue
import threading
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional
from websockets.asyncio.client import connect, ClientConnection

HEADER_FORMAT = "!IB"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def calculate_sha256(file_path: str) -> str:
    """
    Calculate SHA256 hash of a file using memory-mapped I/O for efficiency.

    Uses memory-mapped files for faster hash calculation of large files.

    Args:
        file_path: Path to the file to hash

    Returns:
        Hexadecimal SHA256 hash string
    """
    with open(file_path, "rb") as f:
        # Use memory-mapped files to map directly to memory
        mmapped_file = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        return hashlib.sha256(mmapped_file).hexdigest()


class FrameType(IntEnum):
    PROCESS = 0
    CONCLUSION = 1


@dataclass
class Frame:
    frame_id: int
    frame_type: FrameType
    data: Any


class AsyncStream:
    def __init__(self, connection: "AsyncMultiplexConnection", frame_id: int):
        self.connection = connection
        self.frame_id = frame_id
        self._queue: queue.Queue = queue.Queue(100)

    async def send(self, data: Any, frame_type: FrameType = FrameType.PROCESS):
        await self.connection._send_frame(self.frame_id, frame_type, data)

    async def recv(self, timeout: Optional[float] = None) -> Frame:
        try:
            if timeout is None:
                frame = await asyncio.get_running_loop().run_in_executor(
                    None, self._queue.get
                )
            else:
                frame = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self._queue.get(timeout=timeout)
                )
        except queue.Empty:
            raise TimeoutError("Stream recv timeout")

        if frame is None:
            raise ConnectionError("MultiplexConnection has been closed")
        return frame

    def _put_incoming_frame(self, frame: Optional[Frame]):
        self._queue.put(frame)


class AsyncMultiplexConnection:
    def __init__(self, websocket: ClientConnection):
        self._ws = websocket
        self._next_frame_id = 2
        self._id_lock = threading.Lock()
        self._streams: Dict[int, AsyncStream] = {}
        self._streams_lock = threading.Lock()
        self._new_streams: queue.Queue[Optional[AsyncStream]] = queue.Queue()
        self._is_running = True
        self._dispatcher_task = asyncio.create_task(self._recv_loop())

    def create_stream(self) -> AsyncStream:
        with self._id_lock:
            frame_id = self._next_frame_id
            self._next_frame_id += 2

        new_stream = AsyncStream(self, frame_id)
        with self._streams_lock:
            self._streams[frame_id] = new_stream

        return new_stream

    async def accept_stream(self) -> Optional[AsyncStream]:
        return await asyncio.get_running_loop().run_in_executor(
            None, self._new_streams.get
        )

    async def _recv_loop(self):
        try:
            while self._is_running:
                raw_payload = await self._ws.recv()
                if isinstance(raw_payload, str):
                    raw_payload = raw_payload.encode("utf-8")

                if len(raw_payload) < HEADER_SIZE:
                    continue

                frame_id, frame_type_val = struct.unpack_from(
                    HEADER_FORMAT, raw_payload
                )
                data_bytes = raw_payload[HEADER_SIZE:]

                try:
                    frame_type = FrameType(frame_type_val)
                except ValueError:
                    continue

                frame = Frame(frame_id=frame_id, frame_type=frame_type, data=data_bytes)

                with self._streams_lock:
                    if frame.frame_id not in self._streams:
                        new_stream = AsyncStream(self, frame.frame_id)
                        self._streams[frame.frame_id] = new_stream
                        self._new_streams.put(new_stream)

                    target_stream = self._streams[frame.frame_id]

                target_stream._put_incoming_frame(frame)

                if frame.frame_type == FrameType.CONCLUSION:
                    with self._streams_lock:
                        self._streams.pop(frame.frame_id, None)

        except Exception:
            pass
        finally:
            self._is_running = False
            self._new_streams.put(None)
            with self._streams_lock:
                for stream in self._streams.values():
                    stream._put_incoming_frame(None)

    async def _send_frame(self, frame_id: int, frame_type: FrameType, data: Any):
        if isinstance(data, str):
            data = data.encode("utf-8")
        elif isinstance(data, memoryview):
            data = data.tobytes()

        if data is None:
            data = b""

        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("Frame data must be bytes/string")

        payload = bytearray(HEADER_SIZE + len(data))
        struct.pack_into(HEADER_FORMAT, payload, 0, frame_id, frame_type.value)
        payload[HEADER_SIZE:] = data

        await self._ws.send(payload)

        if frame_type == FrameType.CONCLUSION:
            with self._streams_lock:
                self._streams.pop(frame_id, None)

    async def close(self):
        self._is_running = False
        try:
            await self._ws.close()
        except Exception:
            pass


class CFMSTestClient:
    """
    A test client for the CFMS WebSocket server.

    This client provides convenient methods for connecting to the server,
    sending requests, and receiving responses. It handles authentication
    and connection management automatically.
    """

    def __init__(self, host: str = "localhost", port: int = 5104, use_ssl: bool = True):
        """
        Initialize the test client.

        Args:
            host: Server hostname
            port: Server port
            use_ssl: Whether to use SSL/TLS connection
        """
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.websocket: Optional[ClientConnection] = None
        self.multiplexer: Optional[AsyncMultiplexConnection] = None
        self.username: Optional[str] = None
        self.token: Optional[str] = None

    async def connect(self) -> None:
        """
        Establish a WebSocket connection to the server with retry/backoff logic.
        """
        if self.websocket is not None:
            return

        protocol = "wss" if self.use_ssl else "ws"
        uri = f"{protocol}://{self.host}:{self.port}"

        if self.use_ssl:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        else:
            ssl_context = None

        max_retries = 5
        delay = 0.5
        backoff = 2.0
        last_exc: Optional[BaseException] = None

        for attempt in range(1, max_retries + 1):
            try:
                # connect(...) returns an async connection object
                self.websocket = await connect(uri, ssl=ssl_context)
                self.multiplexer = AsyncMultiplexConnection(self.websocket)
                return
            except Exception as exc:
                last_exc = exc
                if attempt == max_retries:
                    break
                await asyncio.sleep(delay)
                delay *= backoff

        # If we reach here, all attempts failed
        raise RuntimeError(
            f"Failed to connect to {uri} after {max_retries} attempts"
        ) from last_exc

    async def disconnect(self) -> None:
        """
        Close the WebSocket connection.
        """
        if self.multiplexer is not None:
            try:
                await self.multiplexer.close()
            except Exception:
                pass
            self.multiplexer = None

        if self.websocket is not None:
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None

        self.username = None
        self.token = None

    async def _parse_frame_data(self, frame: Frame) -> Any:
        if frame.data is None:
            raise RuntimeError("Received empty frame from server")

        if isinstance(frame.data, memoryview):
            raw = frame.data.tobytes()
        elif isinstance(frame.data, bytes):
            raw = frame.data
        elif isinstance(frame.data, str):
            raw = frame.data.encode("utf-8")
        else:
            raise TypeError("Unsupported frame data type")

        try:
            return orjson.loads(raw)
        except orjson.JSONDecodeError:
            # If not JSON, return raw string
            return raw.decode("utf-8", errors="ignore")

    async def _build_and_send_request(
        self,
        stream: AsyncStream,
        action: str,
        data: Optional[Dict[str, Any]] = None,
        username: Optional[str] = None,
        token: Optional[str] = None,
        include_auth: bool = True,
    ) -> Frame:
        request: Dict[str, Any] = {
            "action": action,
            "data": data if data is not None else {},
        }

        if include_auth:
            resolved_username = username if username is not None else self.username
            resolved_token = token if token is not None else self.token

            if resolved_username is not None or resolved_token is not None:
                if resolved_username is not None:
                    request["username"] = resolved_username
                if resolved_token is not None:
                    request["token"] = resolved_token
                request["nonce"] = secrets.token_hex(16)
                request["timestamp"] = time.time()

        await stream.send(orjson.dumps(request))
        frame = await stream.recv()
        return frame

    async def send_request(
        self,
        action: str,
        data: Optional[Dict[str, Any]] = None,
        username: Optional[str] = None,
        token: Optional[str] = None,
        include_auth: bool = True,
    ) -> Dict[str, Any]:
        """
        Send a request to the server and receive the response.

        Args:
            action: The action to perform
            data: Optional data payload for the request
            username: Optional username (defaults to stored username)
            token: Optional token (defaults to stored token)
            include_auth: Whether to include authentication credentials

        Returns:
            The response from the server as a dictionary
        """
        if self.multiplexer is None:
            raise RuntimeError("Not connected to server. Call connect() first.")

        stream = self.multiplexer.create_stream()
        frame = await self._build_and_send_request(
            stream,
            action,
            data=data,
            username=username,
            token=token,
            include_auth=include_auth,
        )

        payload = await self._parse_frame_data(frame)

        if isinstance(payload, dict):
            return payload

        # If not dict, try to parse it as JSON again
        if isinstance(payload, str):
            try:
                return orjson.loads(payload)
            except orjson.JSONDecodeError as e:
                raise RuntimeError(f"Invalid response from server: {e}") from e

        raise RuntimeError("Unexpected response format from server")

    async def send_raw_request(
        self,
        request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send a raw request object (custom nonce/timestamp) via multiplex stream."""
        if self.multiplexer is None:
            raise RuntimeError("Not connected to server. Call connect() first.")

        stream = self.multiplexer.create_stream()
        await stream.send(orjson.dumps(request))

        frame = await stream.recv()
        payload = await self._parse_frame_data(frame)

        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                return orjson.loads(payload)
            except orjson.JSONDecodeError as e:
                raise RuntimeError(f"Invalid response from server: {e}") from e

        raise RuntimeError("Unexpected response format from server")

    async def login(
        self, username: str, password: str, two_fa_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Authenticate with the server.

        Args:
            username: Username to authenticate with
            password: Password for the user
            two_fa_token: Optional 2FA token for two-factor authentication

        Returns:
            The login response from the server
        """
        data = {"username": username, "password": password}
        if two_fa_token:
            data["2fa_token"] = two_fa_token

        response = await self.send_request("login", data, include_auth=False)

        if response.get("code") == 200:
            self.username = username
            self.token = response.get("data", {}).get("token")

        return response

    async def server_info(self) -> Dict[str, Any]:
        """
        Get server information.

        Returns:
            Server information including version and protocol version
        """
        return await self.send_request("server_info", include_auth=False)

    async def refresh_token(self) -> Dict[str, Any]:
        """
        Refresh the authentication token.

        Returns:
            Response with new token
        """
        response = await self.send_request("refresh_token")

        if response.get("code") == 200:
            self.token = response.get("data", {}).get("token")

        return response

    async def get_document(self, document_id: str) -> Dict[str, Any]:
        """
        Get a document by ID.

        Args:
            document_id: The ID of the document to retrieve

        Returns:
            The document data
        """
        return await self.send_request("get_document", {"document_id": document_id})

    async def create_document(
        self, title: str, folder_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new document.

        Args:
            title: Title of the document
            folder_id: Optional folder ID to create the document in

        Returns:
            Response with created document information
        """
        data = {"title": title}
        if folder_id is not None:
            data["folder_id"] = folder_id
        return await self.send_request("create_document", data)

    async def delete_document(self, document_id: str) -> Dict[str, Any]:
        """
        Delete a document.

        Args:
            document_id: The ID of the document to delete

        Returns:
            Response indicating success or failure
        """
        return await self.send_request("delete_document", {"document_id": document_id})

    async def rename_document(self, document_id: str, new_title: str) -> Dict[str, Any]:
        """
        Rename a document.

        Args:
            document_id: The ID of the document to rename
            new_title: The new title for the document

        Returns:
            Response indicating success or failure
        """
        return await self.send_request(
            "rename_document", {"document_id": document_id, "new_title": new_title}
        )

    async def get_document_info(self, document_id: str) -> Dict[str, Any]:
        """
        Get information about a document.

        Args:
            document_id: The ID of the document

        Returns:
            Document information
        """
        return await self.send_request(
            "get_document_info", {"document_id": document_id}
        )

    async def list_directory(self, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """
        List contents of a directory.

        Args:
            folder_id: The ID of the folder (None for root)

        Returns:
            Directory listing
        """
        data = {}
        data["folder_id"] = folder_id

        return await self.send_request("list_directory", data)

    async def create_directory(
        self, name: str, parent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new directory.

        Args:
            name: Name of the directory
            parent_id: Optional parent directory ID

        Returns:
            Response with created directory information
        """
        data = {"name": name}
        if parent_id is not None:
            data["parent_id"] = parent_id
        return await self.send_request("create_directory", data)

    async def delete_directory(self, folder_id: str) -> Dict[str, Any]:
        """
        Delete a directory.

        Args:
            folder_id: The ID of the folder to delete

        Returns:
            Response indicating success or failure
        """
        return await self.send_request("delete_directory", {"folder_id": folder_id})

    async def move_directory(
        self, folder_id: str, target_folder_id: Optional[str]
    ) -> Dict[str, Any]:
        """
        Move a directory to a new location.

        Args:
            folder_id: The ID of the folder to move
            target_folder_id: The ID of the target parent folder (None for root)

        Returns:
            Response indicating success or failure
        """
        return await self.send_request(
            "move_directory",
            {"folder_id": folder_id, "target_folder_id": target_folder_id},
        )

    async def search(
        self,
        query: str,
        limit: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        search_documents: Optional[bool] = None,
        search_directories: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Search for documents and directories by name.

        Args:
            query: Search query string
            limit: Maximum number of results to return
            sort_by: Sort field (name, created_time, size, last_modified)
            sort_order: Sort order (asc, desc)
            search_documents: Whether to search documents
            search_directories: Whether to search directories

        Returns:
            Search results with matching documents and directories
        """
        data: Dict[str, Any] = {"query": query}
        if limit is not None:
            data["limit"] = limit
        if sort_by is not None:
            data["sort_by"] = sort_by
        if sort_order is not None:
            data["sort_order"] = sort_order
        if search_documents is not None:
            data["search_documents"] = search_documents
        if search_directories is not None:
            data["search_directories"] = search_directories
        return await self.send_request("search", data)

    async def create_user(
        self,
        username: str,
        password: str,
        nickname: Optional[str] = None,
        groups: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Create a new user.

        Args:
            username: Username for the new user
            password: Password for the new user
            nickname: Optional nickname
            groups: Optional list of group assignments

        Returns:
            Response with created user information
        """
        data: dict[str, Any] = {"username": username, "password": password}
        if nickname is not None:
            data["nickname"] = nickname
        if groups is not None:
            data["groups"] = groups
        return await self.send_request("create_user", data)

    async def delete_user(self, username: str) -> Dict[str, Any]:
        """
        Delete a user.

        Args:
            username: Username of the user to delete

        Returns:
            Response indicating success or failure
        """
        return await self.send_request("delete_user", {"username": username})

    async def get_user_info(self, username: str) -> Dict[str, Any]:
        """
        Get information about a user.

        Args:
            username: Username of the user

        Returns:
            User information
        """
        return await self.send_request("get_user_info", {"username": username})

    async def list_users(self) -> Dict[str, Any]:
        """
        List all users.

        Returns:
            List of users
        """
        return await self.send_request("list_users", {})

    async def create_group(
        self, group_name: str, permissions: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Create a new user group.

        Args:
            group_name: Name of the group
            permissions: Optional list of permissions

        Returns:
            Response with created group information
        """
        data: dict[str, Any] = {"group_name": group_name}
        if permissions is not None:
            data["permissions"] = permissions
        return await self.send_request("create_group", data)

    async def list_groups(self) -> Dict[str, Any]:
        """
        List all user groups.

        Returns:
            List of groups
        """
        return await self.send_request("list_groups", {})

    async def get_group_info(self, group_name: str) -> Dict[str, Any]:
        """
        Get information about a group.

        Args:
            group_name: Name of the group

        Returns:
            Group information
        """
        return await self.send_request("get_group_info", {"group_name": group_name})

    async def upload_file_to_server(self, task_id: str, file_path: str):
        """
        Upload a file to the server over WebSocket connection.

        Args:
            task_id: Server task ID for this upload
            file_path: Local path to the file to upload

        Raises:
            ValueError: If server response is invalid
            RuntimeError: If upload is rejected by server
        """

        # Start stream for file upload handshake + transfer
        if self.multiplexer is None:
            raise RuntimeError("Not connected (multiplexing missing).")

        stream = self.multiplexer.create_stream()
        frame = await self._build_and_send_request(
            stream,
            "upload_file",
            {"task_id": task_id},
            include_auth=True,
        )

        response = await self._parse_frame_data(frame)
        if not isinstance(response, dict) or response.get("action") != "transfer_file":
            raise ValueError("Invalid action received for file transfer")

        file_size = os.path.getsize(file_path)
        sha256 = calculate_sha256(file_path) if file_size else None

        task_info = {
            "action": "transfer_file",
            "data": {
                "sha256": sha256,
                "file_size": file_size,
            },
        }

        await stream.send(orjson.dumps(task_info))
        ready_frame = await stream.recv()
        raw_reply = ready_frame.data
        if isinstance(raw_reply, bytes):
            received_response = raw_reply.decode("utf-8", errors="ignore")
        elif isinstance(raw_reply, memoryview):
            received_response = raw_reply.tobytes().decode("utf-8", errors="ignore")
        elif isinstance(raw_reply, str):
            received_response = raw_reply
        else:
            raise RuntimeError("Unexpected file transfer response")

        if received_response.startswith("ready"):
            ready = True
        elif received_response == "stop":
            ready = False
        else:
            raise RuntimeError("Unexpected file transfer handshake response")

        if ready:
            try:
                chunk_size = int(received_response.split()[1])
                with open(file_path, "rb") as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        await stream.send(chunk)

                        if len(chunk) < chunk_size:
                            break

                # need to wait for server confirmation
                server_frame = await stream.recv()
                server_response = await self._parse_frame_data(server_frame)
                return server_response
            except Exception:
                raise
        else:
            raise RuntimeError("Server rejected file upload")

    # def receive_file_from_server(
    #     self,
    #     task_id: str,
    #     file_path: str,  # filename: str | None = None
    # ):
    #     """
    #     Receives a file from the server over a websocket connection using AES encryption.

    #     Steps:
    #         1. Requests file metadata (SHA-256 hash, file size, chunk info) from the server.
    #         2. Sends readiness acknowledgment to the server.
    #         3. Receives encrypted file chunks, saves them temporarily.
    #         4. Receives AES key and IV, decrypts all chunks, and writes the output file.
    #         5. Deletes temporary chunk files.
    #         6. Verifies the file size and SHA-256 hash.
    #         7. Removes the output file if verification fails.

    #     Args:
    #         client (ClientConnection): The websocket client connection.
    #         task_id (str): The identifier for the file transfer task.
    #         file_path (str): The path to save the received file.

    #     Yields:
    #         Tuple[int, ...]: Progress updates at various stages.

    #     Raises:
    #         ValueError: If the server response is invalid.
    #         FileSizeMismatchError: If the received file size does not match the expected size.
    #         FileHashMismatchError: If the received file hash does not match the expected hash.
    #         Exception: For other errors during transfer or decryption.
    #     """

    #     assert self.websocket

    #     # Send the request for file metadata
    #     self.websocket.send(
    #         orjson.dumps(
    #             {
    #                 "action": "download_file",
    #                 "data": {"task_id": task_id},
    #             },
    #
    #         )
    #     )

    #     # Receive file metadata from the server
    #     response = orjson.loads(self.websocket.recv())
    #     if response["action"] != "transfer_file":
    #         raise ValueError("Invalid action received for file transfer")

    #     sha256 = response["data"].get("sha256")  # SHA256 of original file
    #     file_size = response["data"].get("file_size")  # Size of original file
    #     chunk_size = response["data"].get("chunk_size", 8192)  # Chunk size
    #     total_chunks = response["data"].get("total_chunks")  # Total chunks

    #     self.websocket.send("ready")

    #     downloading_path = FLET_APP_STORAGE_TEMP + "/downloading/" + task_id
    #     await aiofiles.os.makedirs(downloading_path, exist_ok=True)

    #     if not file_size:
    #         async with aiofiles.open(file_path, "wb") as f:
    #             await f.truncate(0)
    #         return

    #     try:

    #         received_chunks = 0
    #         iv: bytes = b""

    #         while received_chunks + 1 <= total_chunks:
    #             # Receive encrypted data from the server

    #             data = await self.recv()
    #             if not data:
    #                 raise ValueError("Received empty data from server")

    #             data_json: dict = orjson.loads(data)

    #             index = data_json["data"].get("index")
    #             if index == 0:
    #                 iv = base64.b64decode(data_json["data"].get("iv"))
    #             chunk_hash = data_json["data"].get("hash")  # provided but unused
    #             chunk_data = base64.b64decode(data_json["data"].get("chunk"))
    #             chunk_file_path = os.path.join(downloading_path, str(index))

    #             async with aiofiles.open(chunk_file_path, "wb") as chunk_file:
    #                 await chunk_file.write(chunk_data)

    #             received_chunks += 1

    #             if received_chunks < total_chunks:
    #                 received_file_size = chunk_size * received_chunks
    #             else:
    #                 received_file_size = file_size

    #             yield 0, received_file_size, file_size

    #         # Get decryption information
    #         decrypted_data = await self.recv()
    #         decrypted_data_json: dict = orjson.loads(decrypted_data)

    #         aes_key = base64.b64decode(decrypted_data_json["data"].get("key"))

    #         # Decrypt chunks
    #         decrypted_chunks = 1
    #         cipher = AES.new(aes_key, AES.MODE_CFB, iv=iv)  # Initialize cipher

    #         async with aiofiles.open(file_path, "wb") as out_file:
    #             while decrypted_chunks <= total_chunks:
    #                 yield 1, decrypted_chunks, total_chunks

    #                 chunk_file_path = os.path.join(
    #                     downloading_path, str(decrypted_chunks - 1)
    #                 )

    #                 async with aiofiles.open(chunk_file_path, "rb") as chunk_file:
    #                     encrypted_chunk = await chunk_file.read()
    #                     decrypted_chunk = cipher.decrypt(encrypted_chunk)
    #                     await out_file.write(decrypted_chunk)

    #                 # os.remove(chunk_file_path)
    #                 decrypted_chunks += 1

    #         # Delete temporary folder
    #         yield 2,

    #         await asyncio.get_event_loop().run_in_executor(
    #             None, shutil.rmtree, downloading_path
    #         )

    #     except Exception:
    #         raise

    #     # Verify file

    #     async def _action_verify() -> None:

    #         if file_size != await aiofiles.os.path.getsize(file_path):
    #             raise FileSizeMismatchError(
    #                 file_size, await aiofiles.os.path.getsize(file_path)
    #             )

    #         # Verify SHA256
    #         actual_sha256 = await calculate_sha256(file_path)
    #         if sha256 and actual_sha256 != sha256:
    #             raise FileHashMismatchError(sha256, actual_sha256)

    #     yield 3,

    #     try:
    #         await _action_verify()
    #     except Exception:
    #         await aiofiles.os.remove(file_path)
    #         raise

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()

    # Two-Factor Authentication methods

    async def setup_2fa(self) -> Dict[str, Any]:
        """
        Setup two-factor authentication for the authenticated user.

        Returns:
            Response with TOTP secret, provisioning URI, and backup codes
        """
        return await self.send_request("setup_2fa", {})

    async def validate_2fa(self, token: str) -> Dict[str, Any]:
        """
        Validate and enable two-factor authentication.

        Args:
            token: TOTP token from authenticator app

        Returns:
            Response indicating success or failure
        """
        return await self.send_request("validate_2fa", {"token": token})

    async def cancel_2fa_setup(self) -> Dict[str, Any]:
        """
        Cancel two-factor authentication setup (before validation).

        Returns:
            Response indicating success or failure
        """
        return await self.send_request("cancel_2fa_setup", {})

    async def cancel_2fa(self, password: str) -> Dict[str, Any]:
        """
        Cancel two-factor authentication for the authenticated user.

        Args:
            password: User's password for verification

        Returns:
            Response indicating success or failure
        """
        return await self.send_request("disable_2fa", {"password": password})

    async def get_2fa_status(self) -> Dict[str, Any]:
        """
        Get two-factor authentication status for the authenticated user.

        Returns:
            Response with 2FA status information
        """
        return await self.send_request("get_2fa_status", {})

    async def grant_access(
        self,
        entity_type: str,
        entity_identifier: str,
        target_type: str,
        target_identifier: str,
        access_types: list[str],
        start_time: float,
        end_time: float | None = None,
    ) -> Dict[str, Any]:
        """
        Grant access to a user or group for a document or directory.

        Args:
            entity_type: Type of entity ("user" or "group")
            entity_identifier: Username or group name
            target_type: Type of target ("document" or "directory")
            target_identifier: Document or folder ID
            access_types: List of access types to grant
            start_time: When access starts (timestamp)
            end_time: When access ends (timestamp, optional)

        Returns:
            Response indicating success or failure
        """
        data: Dict[str, Any] = {
            "entity_type": entity_type,
            "entity_identifier": entity_identifier,
            "target_type": target_type,
            "target_identifier": target_identifier,
            "access_types": access_types,
            "start_time": start_time,
        }
        if end_time is not None:
            data["end_time"] = end_time
        return await self.send_request("grant_access", data)

    async def revoke_access(self, entry_id: int) -> Dict[str, Any]:
        """
        Revoke access by deleting an access entry.

        Args:
            entry_id: ID of the access entry to revoke

        Returns:
            Response indicating success or failure
        """
        return await self.send_request("revoke_access", {"entry_id": entry_id})

    async def view_access_entries(
        self, object_type: str, object_identifier: str
    ) -> Dict[str, Any]:
        """
        View access entries for a user, group, document, or directory.

        Args:
            object_type: Type of object ("user", "group", "document", or "directory")
            object_identifier: Identifier of the object

        Returns:
            Response with list of access entries
        """
        return await self.send_request(
            "view_access_entries",
            {"object_type": object_type, "object_identifier": object_identifier},
        )

    # Keyring methods

    async def upload_keyring(
        self,
        key_content: str,
        label: Optional[str] = None,
        target_username: Optional[str] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"content": key_content}
        if label is not None:
            data["label"] = label
        if target_username is not None:
            data["target_username"] = target_username
        return await self.send_request("upload_user_key", data)

    async def get_keyring(
        self,
        key_id: str,
    ) -> Dict[str, Any]:
        return await self.send_request("get_user_key", {"id": key_id})

    async def delete_keyring(
        self,
        key_id: str,
    ) -> Dict[str, Any]:
        return await self.send_request("delete_user_key", {"id": key_id})

    async def set_preference_keyring(
        self,
        key_id: str,
    ) -> Dict[str, Any]:
        return await self.send_request("set_user_preference_dek", {"id": key_id})

    async def list_keyrings(
        self,
        target_username: Optional[str] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if target_username is not None:
            data["target_username"] = target_username
        return await self.send_request("list_user_keys", data)
