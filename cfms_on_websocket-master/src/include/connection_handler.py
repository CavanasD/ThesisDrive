import orjson
import os
import threading
import time
from typing import Optional, Union
import jsonschema
import websockets
import websockets.sync.server
from include.classes.enum.permissions import Permissions
from include.classes.frame import FrameType, MultiplexConnection, Stream
from include.classes.misc.guard import LoginGuard
from include.classes.request import RequestHandler
from include.conf_loader import global_config
from include.classes.handler import ConnectionHandler
from include.database.handler import Session
from include.database.models.classic import User
from include.util.address import get_client_ip
from include.util.audit import log_audit
from include.handlers.auth import RequestLoginHandler, RequestRefreshTokenHandler
from include.handlers.two_factor import (
    RequestCancel2FASetupHandler,
    RequestSetup2FAHandler,
    RequestValidate2FAHandler,
    RequestDisable2FAHandler,
    RequestGet2FAStatusHandler,
)
from include.handlers.document import (
    RequestCreateDocumentHandler,
    RequestDeleteDocumentHandler,
    RequestDownloadFileHandler,
    RequestGetDocumentHandler,
    RequestGetDocumentInfoHandler,
    RequestGetDocumentAccessRulesHandler,
    RequestMoveDocumentHandler,
    RequestRenameDocumentHandler,
    RequestRestoreDocumentHandler,
    RequestSetDocumentRulesHandler,
    RequestUploadDocumentHandler,
    RequestUploadFileHandler,
    RequestPurgeDocumentHandler,
)
from include.handlers.directory import (
    RequestListDeletedItemsHandler,
    RequestListDirectoryHandler,
    RequestCreateDirectoryHandler,
    RequestDeleteDirectoryHandler,
    RequestGetDirectoryInfoHandler,
    RequestGetDirectoryAccessRulesHandler,
    RequestMoveDirectoryHandler,
    RequestRenameDirectoryHandler,
    RequestRestoreDirectoryHandler,
    RequestSetDirectoryRulesHandler,
    RequestPurgeDirectoryHandler,
)
from include.handlers.revision import (
    RequestDeleteRevisionHandler,
    RequestListRevisionsHandler,
    RequestGetRevisionHandler,
    RequestSetDocumentRevisionHandler,
)
from include.handlers.management.user import (
    RequestChangeUserGroupsHandler,
    RequestCreateUserHandler,
    RequestDeleteUserHandler,
    RequestBlockUserHandler,
    RequestListUserBlocksHandler,
    RequestGetUserAvatarHandler,
    RequestManageUserStatusHandler,
    RequestSetUserAvatarHandler,
    RequestUnblockUserHandler,
    RequestListUsersHandler,
    RequestGetUserInfoHandler,
    RequestRenameUserHandler,
    RequestSetPasswdHandler,
)
from include.handlers.management.group import (
    RequestChangeGroupPermissionsHandler,
    RequestCreateGroupHandler,
    RequestDeleteGroupHandler,
    RequestGetGroupInfoHandler,
    RequestListGroupsHandler,
    RequestRenameGroupHandler,
)
from include.handlers.management.access import (
    RequestGrantAccessHandler,
    RequestRevokeAccessHandler,
    RequestViewAccessEntriesHandler,
)
from include.handlers.management.system import (
    RequestLockdownHandler,
    RequestViewAuditLogsHandler,
)
from include.handlers.debugging.throw import RequestThrowExceptionHandler
from include.handlers.search import RequestSearchHandler
from include.handlers.keyring import (
    RequestUploadUserKeyHandler,
    RequestGetUserKeyHandler,
    RequestDeleteUserKeyHandler,
    RequestSetPreferenceDEKHandler,
    RequestListUserKeysHandler,
)

from include.constants import CORE_VERSION, NONCE_MIN_LENGTH, PROTOCOL_VERSION
from include.nonce_store import nonce_store
from include.shared import lockdown_enabled, clients, clients_lock

import cProfile, pstats, io
from pstats import SortKey

pr = cProfile.Profile()


from include.util.cert import get_client_cert_subject
from include.util.log import getCustomLogger

logger = getCustomLogger(
    "connection_handler", filepath="./content/logs/connection_handler.log"
)


def _validate_replay_protection(
    handler: ConnectionHandler,
) -> Optional[str]:
    """
    Validate nonce and timestamp for an authenticated request.

    Returns None on success, or an error string after sending a rejection
    response via handler.conclude_request.
    """
    nonce = handler.nonce
    request_timestamp = handler.request_timestamp

    if not nonce or len(nonce) < NONCE_MIN_LENGTH:
        handler.conclude_request(
            400, {}, "Missing or invalid nonce for replay protection"
        )
        return "nonce"

    if not request_timestamp:
        handler.conclude_request(
            400, {}, "Missing or invalid timestamp for replay protection"
        )
        return "timestamp"

    replay_error = nonce_store.validate_and_store(nonce, float(request_timestamp))
    if replay_error is not None:
        handler.conclude_request(1001, {}, replay_error)
        return "replay"

    return None


def handle_connection(websocket: websockets.sync.server.ServerConnection):
    """
    Handle incoming WebSocket connections.

    Args:
        websocket: The WebSocket connection object.
    """

    client_cn = get_client_cert_subject(websocket)
    if client_cn:
        logger.info(
            f"Incoming connection: {websocket.remote_address[0]} (client cert CN: {client_cn})"
        )
    else:
        logger.info(f"Incoming connection: {websocket.remote_address[0]}")

    multiplexer = MultiplexConnection(websocket)

    with clients_lock:
        clients.add(multiplexer)

    try:
        while True:
            stream = multiplexer.accept_stream()
            if stream is None:
                break  # Connection closed

            threading.Thread(target=handle_request, args=(stream,), daemon=True).start()

    except Exception as e:
        logger.error(f"Error handling WebSocket connection: {e}", exc_info=True)
    finally:
        multiplexer.close()
        websocket.close()

        with clients_lock:
            clients.discard(multiplexer)


def handle_request(stream: Stream):
    """
    Handle a specific request/message received over the WebSocket connection.

    Args:
        stream: The Stream object representing the logical request stream.
    """

    ip = get_client_ip(stream.connection._ws)

    if not LoginGuard.check_access(f"ip_limit|{ip}"):
        response = {
            "code": 403,
            "message": "Your IP has been temporarily blocked due to suspicious activity. Please try again later.",
            "timestamp": time.time(),
        }
        stream.send(orjson.dumps(response), frame_type=FrameType.CONCLUSION)
        # 强制断开 WebSocket 连接
        # 1008 是 WebSocket 协议定义的 Policy Violation 错误码
        stream.connection.close()
        stream.connection._ws.close(code=1008, reason="IP temporarily blocked")
        return

    try:
        this_handler = ConnectionHandler(stream)
    except jsonschema.ValidationError as error:
        # Request envelope failed schema validation — send error and bail out
        response = {
            "code": 400,
            "data": {},
            "message": f"Invalid request format: {error.message}",
            "timestamp": time.time(),
        }
        stream.send(
            orjson.dumps(
                response,
            ),
            frame_type=FrameType.CONCLUSION,
        )
        return

    action = this_handler.action

    if action is None:
        this_handler.conclude_request(400, {}, "No action specified in request")
        return

    available_functions: dict[str, type[RequestHandler]] = {
        "server_info": RequestServerInfoHandler,
        # 认证类
        "login": RequestLoginHandler,
        "refresh_token": RequestRefreshTokenHandler,
        # 两步验证类
        "setup_2fa": RequestSetup2FAHandler,
        "cancel_2fa_setup": RequestCancel2FASetupHandler,  # especially for cancelling setup
        "validate_2fa": RequestValidate2FAHandler,
        "disable_2fa": RequestDisable2FAHandler,
        "get_2fa_status": RequestGet2FAStatusHandler,
        # 文档类
        "get_document": RequestGetDocumentHandler,
        "create_document": RequestCreateDocumentHandler,
        "upload_document": RequestUploadDocumentHandler,
        "delete_document": RequestDeleteDocumentHandler,
        "restore_document": RequestRestoreDocumentHandler,
        "purge_document": RequestPurgeDocumentHandler,
        "rename_document": RequestRenameDocumentHandler,
        "move_document": RequestMoveDocumentHandler,
        "get_document_info": RequestGetDocumentInfoHandler,
        "get_document_access_rules": RequestGetDocumentAccessRulesHandler,
        "set_document_rules": RequestSetDocumentRulesHandler,
        # 修订版本类
        "list_revisions": RequestListRevisionsHandler,
        "get_revision": RequestGetRevisionHandler,
        "set_current_revision": RequestSetDocumentRevisionHandler,
        "delete_revision": RequestDeleteRevisionHandler,
        # 文件类
        "download_file": RequestDownloadFileHandler,
        "upload_file": RequestUploadFileHandler,
        # 目录类
        "list_directory": RequestListDirectoryHandler,
        "get_directory_info": RequestGetDirectoryInfoHandler,
        "get_directory_access_rules": RequestGetDirectoryAccessRulesHandler,
        "set_directory_rules": RequestSetDirectoryRulesHandler,
        "create_directory": RequestCreateDirectoryHandler,
        "delete_directory": RequestDeleteDirectoryHandler,
        "restore_directory": RequestRestoreDirectoryHandler,
        "purge_directory": RequestPurgeDirectoryHandler,
        "rename_directory": RequestRenameDirectoryHandler,
        "move_directory": RequestMoveDirectoryHandler,
        "list_deleted_items": RequestListDeletedItemsHandler,
        # Search
        "search": RequestSearchHandler,
        # Users
        "manage_user_status": RequestManageUserStatusHandler,
        "block_user": RequestBlockUserHandler,
        "unblock_user": RequestUnblockUserHandler,
        "list_user_blocks": RequestListUserBlocksHandler,
        "list_users": RequestListUsersHandler,
        "create_user": RequestCreateUserHandler,
        "delete_user": RequestDeleteUserHandler,
        "rename_user": RequestRenameUserHandler,
        "get_user_info": RequestGetUserInfoHandler,
        "get_user_avatar": RequestGetUserAvatarHandler,
        "set_user_avatar": RequestSetUserAvatarHandler,
        "change_user_groups": RequestChangeUserGroupsHandler,
        "set_passwd": RequestSetPasswdHandler,
        # 用户组类
        "list_groups": RequestListGroupsHandler,
        "create_group": RequestCreateGroupHandler,
        "delete_group": RequestDeleteGroupHandler,
        "rename_group": RequestRenameGroupHandler,
        "get_group_info": RequestGetGroupInfoHandler,
        "change_group_permissions": RequestChangeGroupPermissionsHandler,
        # 访问类
        "grant_access": RequestGrantAccessHandler,
        "revoke_access": RequestRevokeAccessHandler,
        "view_access_entries": RequestViewAccessEntriesHandler,
        # 系统类
        "lockdown": RequestLockdownHandler,
        "view_audit_logs": RequestViewAuditLogsHandler,
        # Keyring
        "upload_user_key": RequestUploadUserKeyHandler,
        "get_user_key": RequestGetUserKeyHandler,
        "delete_user_key": RequestDeleteUserKeyHandler,
        "set_user_preference_dek": RequestSetPreferenceDEKHandler,
        "list_user_keys": RequestListUserKeysHandler,
    }

    # Debugging
    if global_config["debug"]:
        available_functions["throw_exception"] = RequestThrowExceptionHandler

    # 定义白名单内的请求。这些请求即使在防范禁闭时也对所有用户可用。
    whitelisted_functions = [
        # "echo",
        "server_info",
        "login",
        "refresh_token",
        "validate_2fa",
        "upload_file",
        "download_file",
    ]

    user_permissions: set[Permissions] = set()
    authenticated = False
    if this_handler.username and this_handler.token:
        with Session() as session:
            user = session.get(User, this_handler.username)
            if user and user.is_token_valid(this_handler.token):
                authenticated = True
                user_permissions = user.all_permissions
            else:
                this_handler.conclude_request(401, {}, "Invalid user or token")
                return

    if lockdown_enabled.is_set():
        if action not in whitelisted_functions:
            can_bypass_lockdown = False
            if authenticated and Permissions.BYPASS_LOCKDOWN in user_permissions:
                can_bypass_lockdown = True

            if not can_bypass_lockdown:
                this_handler.conclude_request(999, {}, "lockdown")
                return

    # Replay attack protection: validate nonce and timestamp.
    # Only applied to authenticated requests to prevent unauthenticated
    # traffic from polluting the nonce store (DoS vector).
    if authenticated and _validate_replay_protection(this_handler) is not None:
        return

    if action == "shutdown":
        if not authenticated:
            this_handler.conclude_request(401, {}, "Authentication required")
            return

        if "shutdown" not in user_permissions:
            this_handler.conclude_request(403, {}, "Permission denied")
            return

        # Shutdown the server
        this_handler.conclude_request(200, {}, "Server is shutting down")
        logger.info("Server is shutting down")
        threading.Thread(target=os._exit(0), daemon=True).start()
    elif action in available_functions:

        _request_handler: RequestHandler = available_functions[action]()

        try:
            jsonschema.validate(this_handler.data, _request_handler.data_schema)
        except jsonschema.ValidationError as error:
            this_handler.conclude_request(
                400,
                {
                    "validator": error.validator,
                    "validator_value": error.validator_value,
                },
                error.message,
            )
            return

        if _request_handler.require_auth and not authenticated:
            this_handler.conclude_request(401, {}, "Authentication required")
            log_audit(
                action,
                401,
                data=this_handler.data,
                remote_address=this_handler.remote_address,
            )
            return

        try:
            t1 = time.perf_counter()
            # pr.enable()
            callback: Union[
                int,
                tuple[int, Optional[str]],
                tuple[int, Optional[str], dict],
                tuple[int, Optional[str], str],
                tuple[int, Optional[str], dict, str],
                None,
            ] = _request_handler.handle(this_handler)
            # pr.disable()
            # s = io.StringIO()
            # ps = pstats.Stats(pr, stream=s).sort_stats(SortKey.CUMULATIVE)
            # ps.print_stats()
            # print(s.getvalue())
            t2 = time.perf_counter()
            logger.debug(f"Handled action '{action}' in {t2 - t1:.3f} seconds")
        except (
            websockets.exceptions.ConnectionClosedOK,
            websockets.exceptions.ConnectionClosedError,
        ):
            raise
        except Exception as e:
            this_handler.report_error(e)
            return

        if type(callback) is tuple:
            match callback:
                case (result, target) if len(callback) == 2:
                    # 不判断各元素类型是否正确。第二个元素是目标对象
                    log_audit(
                        action,
                        result,
                        target=target,
                        remote_address=this_handler.remote_address,
                    )
                case (result, target, data) if (
                    isinstance(data, dict) and len(callback) == 3
                ):
                    log_audit(
                        action,
                        result,
                        target=target,
                        data=data,
                        remote_address=this_handler.remote_address,
                    )
                case (result, target, username) if (
                    isinstance(username, str) and len(callback) == 3
                ):
                    log_audit(
                        action,
                        result,
                        target=target,
                        username=username,
                        remote_address=this_handler.remote_address,
                    )
                case (result, target, data, username) if len(callback) == 4:
                    log_audit(
                        action,
                        result,
                        target=target,
                        data=data,
                        username=username,
                        remote_address=this_handler.remote_address,
                    )
                case _:
                    raise TypeError
        elif type(callback) is int:
            log_audit(action, callback)
        elif callback is None:
            # 这个设计为两种情况所预留：
            # 1. 为旧版本代码的向下兼容考量；
            # 2. 为不适合采用 return 提交审计信息的逻辑预留。
            return
        else:
            raise TypeError("Invaild returned value")
    else:
        # Handle unknown actions
        this_handler.conclude_request(400, {}, f"Unknown action: {this_handler.action}")

    return


class RequestServerInfoHandler(RequestHandler):
    """
    Handle the 'server_info' action to return server information.

    Args:
        this_handler: The ConnectionHandler instance handling the request.
    """

    data_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def handle(self, handler: ConnectionHandler):

        server_info = {
            "server_name": global_config["server"]["name"],
            "version": CORE_VERSION.original,
            "protocol_version": PROTOCOL_VERSION,
            "lockdown": lockdown_enabled.is_set(),
        }
        handler.conclude_request(
            200, server_info, "Server information retrieved successfully"
        )
        return
