import base64
import hashlib
import orjson
import mmap
import os
import time
import traceback
from typing import Optional

import jsonschema
import websockets
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from websockets.typing import Data

from include.classes.frame import FrameType, MultiplexConnection, Stream
from include.conf_loader import global_config
from include.constants import FILE_TRANSFER_MAX_CHUNK_SIZE, FILE_TRANSFER_MIN_CHUNK_SIZE
from include.database.handler import Session
from include.database.models.file import File, FileTask
from include.shared import clients, clients_lock
from include.util.log import getCustomLogger, log_exception_with_id

logger = getCustomLogger(
    "connection",
    filepath="./content/logs/connection.log",
)


def calculate_sha256(file_path):
    # 使用更快的 hashlib 工具和内存映射文件
    with open(file_path, "rb") as f:
        # 使用内存映射文件直接映射到内存
        mmapped_file = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        return hashlib.sha256(mmapped_file).hexdigest()


# JSON Schema for the top-level request envelope.
# Validates field types so downstream code can rely on concrete types.
_REQUEST_ENVELOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "data": {"type": "object"},
        "username": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "token": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "nonce": {"type": "string"},
        "timestamp": {"type": "number"},
    },
    "required": ["action", "data"],
    "dependentRequired": {
        "username": ["token"],
        "token": ["username"],
    },
}


class ConnectionHandler:
    def __init__(self, stream: Stream) -> None:
        self.stream = stream
        self.remote_address = self.stream.connection._ws.remote_address[0]

        # Since a thread is created only after a new request has been
        # received, the necessary initial data should be available
        # immediately here.
        self.request = orjson.loads(stream.recv().data)
        self.logger = logger

        # Validate the request envelope structure and field types
        jsonschema.validate(self.request, _REQUEST_ENVELOPE_SCHEMA)

        self.action: str = self.request["action"]
        self.data: dict = self.request["data"]

        self.username: str = self.request.get("username", "")
        self.token: str = self.request.get("token", "")

        self.nonce: str = self.request.get("nonce", "")
        self.request_timestamp: float = self.request.get("timestamp", 0.0)

    def conclude_request(
        self, code: int, data: Optional[dict] = None, message: str = ""
    ) -> None:
        """
        Conclude the request by sending a response back to the client.

        Args:
            code: HTTP status code for the response.
            data: Data dictionary to include in the response.
            message: Message string to include in the response.
        """
        response = {
            "code": code,
            "data": data if data is not None else {},
            "message": message,
            "timestamp": time.time(),
        }

        response_json = orjson.dumps(
            response,
        )
        self.logger.debug(f"Sending response: {response_json}")

        self.stream.send(response_json, frame_type=FrameType.CONCLUSION)

    def report_error(
        self,
        exc: Exception,
        code: int = 500,
        context: Optional[str] = None,
        send_to_client: bool = True,
    ) -> str:
        """
        Log an exception with a generated log id and optionally send a safe message to client.

        Returns the generated log id.
        """
        log_id = log_exception_with_id(exc, self.logger, context=context)
        if send_to_client:
            self.conclude_request(
                code,
                {
                    "log_id": log_id,
                },
                context if context is not None else "Internal server error",
            )
        return log_id

    def send_file(self, task_id: str) -> None:
        """
        Sends a file associated with the given task ID to the client over a websocket connection using AES encryption.
        The method performs the following steps:
        1. Retrieves the file ID and file path based on the provided task ID.
        2. Calculates the SHA-256 hash and size of the file.
        3. Notifies the client of the impending file transfer, including the hash and size.
        4. Waits for the client to acknowledge readiness to receive the file.
        5. Encrypts the file using AES-256 in CFB mode with a randomly generated key and IV.
        6. Sends the IV with the first encrypted chunk, then sends the remaining encrypted chunks.
        7. After the file is sent, transmits the AES key and IV to the client (base64 encoded).
        8. Handles errors and logs relevant information.
        Args:
            task_id (str): The identifier for the task whose associated file is to be sent.
        Raises:
            ValueError: If the file ID or file path cannot be found for the given task ID.
            Exception: If an error occurs during file encryption or transmission.
        Returns:
            None
        """

        with Session() as session:
            # Query the FileTask table to get the file_id associated with the task_id
            file_task = session.get(FileTask, task_id)
            if not file_task:
                raise ValueError(f"File transfer task not found for task_id: {task_id}")
            if file_task.mode != 0:
                raise ValueError(f"Not a read-mode task: {task_id}")
            if file_task.status != 0:
                raise ValueError(
                    f"File transfer task already completed or cancelled: {task_id}"
                )
            # Query the File table to get the file path associated with the file_id
            file = session.get(File, file_task.file_id)
            if not file:
                raise ValueError(f"File not found for file_id: {file_task.file_id}")

            self.logger.info(
                f"Task {file_task.id}: preparing to send file (id: {file_task.file_id})."
            )

            file_size = os.path.getsize(file.path)
            sha256 = calculate_sha256(file.path) if file_size else None

            self.logger.info(
                f"Calculation complete. SHA256: {sha256}, File size: {file_size}"
            )

            file_path = file.path  # 防止 Session 关闭后可能出现的异常

            ### 发送方首先发出文件信息
            chunk_size = global_config["server"]["file_chunk_size"]  # 文件分块大小
            total_chunks = (file_size + chunk_size - 1) // chunk_size

            self.stream.send(
                orjson.dumps(
                    {
                        "action": "transfer_file",
                        "data": {
                            "sha256": sha256,  # 原始文件的 SHA256 哈希值
                            "file_size": file_size,  # 原始文件的大小
                            "chunk_size": chunk_size,  # 分块大小
                            "total_chunks": total_chunks,  # 文件总分块数
                        },
                    },
                )
            )

            received_response = (
                self.stream.recv()
            )  # Wait for client acknowledgment before sending the file
            if received_response.data != b"ready":
                self.logger.error(
                    "Client did not acknowledge readiness for file "
                    f"transfer: {received_response}"
                )
                self.conclude_request(400, {}, "Client not ready for file transfer")
                return

            if file_size != 0:
                self.logger.info("File transmission begin.")
                try:
                    aes_key = get_random_bytes(32)  # AES-256
                    iv = get_random_bytes(16)
                    cipher = AES.new(aes_key, AES.MODE_CFB, iv=iv)

                    with open(file_path, "rb") as file:
                        chunk_index = 0
                        while True:
                            chunk = file.read(chunk_size)
                            if not chunk:
                                break
                            chunk_hash = hashlib.sha256(chunk).hexdigest()
                            encrypted_chunk = cipher.encrypt(chunk)
                            payload = {
                                "action": "file_chunk",
                                "data": {
                                    "index": chunk_index,
                                    "hash": chunk_hash,
                                    "iv": (
                                        base64.b64encode(iv).decode()
                                        if chunk_index == 0
                                        else ""
                                    ),
                                    "chunk": base64.b64encode(encrypted_chunk).decode(),
                                },
                            }
                            self.stream.send(
                                orjson.dumps(
                                    payload,
                                )
                            )
                            chunk_index += 1

                    # 发送密钥和IV
                    self.stream.send(
                        orjson.dumps(
                            {
                                "action": "aes_key",
                                "data": {
                                    "key": base64.b64encode(aes_key).decode(),
                                    # "iv": base64.b64encode(iv).decode(),
                                },
                            },
                        )
                    )
                    file_task.status = 1
                    session.commit()

                except Exception as e:
                    self.report_error(e, context=f"Error sending file {file_path}")
                    return

            else:
                self.logger.info("Empty file, no need to send")

        self.logger.info(f"File {file_path} sent successfully.")

    def receive_file(self, task_id: str) -> None:
        """
        Receives a file from the client over a websocket connection using AES encryption.
        The method performs the following steps:
        1. Waits for the client to send the file transfer request, including the SHA-256 hash and file size.
        2. Acknowledges readiness to receive the file.
        3. Receives the encrypted file data in chunks, decrypting each chunk using AES-256 in CFB mode.
        4. Writes the decrypted data to a file on disk.
        5. Handles errors and logs relevant information.
        Returns:
            None
        """

        handshake_msg = {
            "action": "transfer_file",
            "data": {},
            "message": "waiting for file transfer",
        }

        self.stream.send(
            orjson.dumps(
                handshake_msg,
            )
        )
        self.logger.info("Receiving file: handshake sent")

        task_info = orjson.loads(self.stream.recv().data)

        try:
            jsonschema.validate(
                task_info,
                {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "pattern": "^transfer_file$"},
                        "data": {
                            "type": "object",
                            "properties": {
                                "sha256": {
                                    "anyOf": [{"type": "string"}, {"type": "null"}]
                                },
                                "file_size": {"type": "integer"},
                                "max_chunk_size": {
                                    "type": "integer",
                                    "minimum": FILE_TRANSFER_MIN_CHUNK_SIZE,
                                },
                            },
                            "required": ["file_size"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["data"],
                    "additionalProperties": False,
                },
            )
        except jsonschema.ValidationError:
            self.conclude_request(400, {}, "Invalid request for file transfer")
            return

        sha256: str = task_info["data"].get("sha256")
        file_size: int = task_info["data"].get("file_size")
        max_chunk_size: int = task_info["data"].get(
            "max_chunk_size", FILE_TRANSFER_MAX_CHUNK_SIZE
        )

        chunk_size = (
            FILE_TRANSFER_MAX_CHUNK_SIZE
            if max_chunk_size > FILE_TRANSFER_MAX_CHUNK_SIZE
            else max_chunk_size
        )

        ### 获取任务与文件基本信息
        with Session() as session:
            # Query the FileTask table to get the file_id associated with the task_id
            file_task = session.get(FileTask, task_id)
            if not file_task:
                raise ValueError(f"File transfer task not found for task_id: {task_id}")
            if file_task.mode != 1:
                raise ValueError(f"Not a write-mode task: {task_id}")
            if file_task.status != 0:
                raise ValueError(
                    f"File transfer task already completed or cancelled: {task_id}"
                )
            # Query the File table to get the file path associated with the file_id
            file = session.get(File, file_task.file_id)
            if not file:
                raise ValueError(f"File not found for file_id: {file_task.file_id}")

            if file_size == 0:  # 空文件
                self.stream.send("stop")
                with open(file.path, "wb") as f:
                    f.truncate(0)
                file.active = True
                session.commit()
                return

            self.stream.send(f"ready {chunk_size}")
            try:
                # 生成保存文件的路径
                if not file.id:
                    raise ValueError(f"File path not found for file_id: {file.id}")

                logger.info("Receiving file: transfer started")
                os.makedirs(os.path.dirname(file.path), exist_ok=True)
                with open(file.path, "wb") as f:
                    try:
                        while True:
                            # Receive encrypted data from the client
                            data = self.stream.recv().data
                            f.write(data)

                            if not data or len(data) < chunk_size:
                                break
                    except (
                        websockets.ConnectionClosed,
                        websockets.exceptions.ConnectionClosedOK,
                    ) as exc:
                        raise

                # 校验文件大小
                actual_size = os.path.getsize(file.path)
                if file_size and actual_size != file_size:
                    self.logger.error(
                        f"File size mismatch: expected {file_size}, got {actual_size}"
                    )
                    os.remove(file.path)

                    self.conclude_request(
                        400,
                        {},
                        f"File size mismatch: expected {file_size}, got {actual_size}",
                    )
                    return

                # 校验sha256
                if sha256:
                    actual_sha256 = calculate_sha256(file.path)
                    if actual_sha256 != sha256:
                        self.logger.error(
                            f"SHA256 mismatch: expected {sha256}, got {actual_sha256}"
                        )
                        os.remove(file.path)

                        self.conclude_request(
                            400,
                            {},
                            f"SHA256 mismatch: expected {sha256}, got {actual_sha256}",
                        )
                        return

                file_task.status = 1
                file.sha256 = sha256
                file.active = True
                session.commit()

                self.logger.info(
                    f"File received and saved to {file.path}, total size: {actual_size}"
                )

                self.conclude_request(200, {}, "File received successfully")

            except (
                websockets.ConnectionClosed,
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
            ):
                raise

            except Exception as e:
                self.report_error(e, context=f"Error receiving file for task {task_id}")
                return

    def broadcast(
        self,
        message: Data,
        raise_exceptions: bool = False,
    ):
        """
        Adopted from websockets.asyncio.server.broadcast().
        """
        with clients_lock:
            connections: set[MultiplexConnection] = clients.copy()

        if isinstance(message, str):
            message = message.encode()
        elif isinstance(message, (bytes, bytearray, memoryview)):
            pass
        else:
            raise TypeError("data must be str or bytes")

        exceptions: list[Exception] = []

        for connection in connections:
            exception: Exception

            if connection._ws.protocol.state is not websockets.protocol.OPEN:
                continue

            try:
                # Call connection.protocol.send_text or send_binary.
                # Either way, message is already converted to bytes.
                # getattr(connection.protocol, send_method)(message)
                stream = connection.create_stream()
                stream.send(message, frame_type=FrameType.CONCLUSION)
            except Exception as write_exception:
                if raise_exceptions:
                    exception = RuntimeError("failed to write message")
                    exception.__cause__ = write_exception
                    exceptions.append(exception)
                else:
                    connection._ws.logger.warning(
                        "skipped broadcast: failed to write message: %s",
                        traceback.format_exception_only(
                            # Remove first argument when dropping Python 3.9.
                            type(write_exception),
                            write_exception,
                        )[0].strip(),
                    )

        if raise_exceptions and exceptions:
            raise ExceptionGroup("skipped broadcast", exceptions)
