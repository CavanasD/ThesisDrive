import secrets
import time
from typing import Optional

import jsonschema
from itertools import batched

from include.classes.handler import ConnectionHandler
from include.classes.enum.permissions import Permissions
from include.classes.enum.status import EntityStatus
from include.classes.request import RequestHandler
from include.conf_loader import global_config
from include.constants import ROOT_DIRECTORY_ID, QUERY_CHUNK_SIZE
from include.database.handler import Session
from include.database.models.classic import User
from include.database.models.entity import Folder, Document
from include.util.audit import log_audit
from include.util.bulk.purge import purge_documents_bulk
from include.util.rule.applying import apply_access_rules
from include.util.recursive.subtree import fetch_subtree_for_deletion
from include.util.log import getCustomLogger
import include.system.messages as smsg

logger = getCustomLogger(__name__, filepath="./content/logs/directory.log")


class RequestListDirectoryHandler(RequestHandler):
    """
    Handles directory listing requests.
    This util processes a directory listing request by generating a list of files and directories in the specified directory.
    It sends an appropriate response back to the client, indicating success or failure.
    Args:
        handler (ConnectionHandler): The connection handler containing request data and methods for responding.
    Response Codes:
        200 - Directory listing successful, returns a list of files and directories in the response data.
        400 - Invalid request.
        403 - Invalid user or token.
        404 - Directory not found.
        500 - Internal server error, with the exception message.
    """

    data_schema = {
        "type": "object",
        "properties": {"folder_id": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["folder_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        # Parse the directory listing request
        folder_id: Optional[str] = handler.data.get("folder_id")

        with Session() as session:
            this_user = session.get(User, handler.username)
            assert this_user is not None

            # Determine parent folder and fetch children/documents
            if not folder_id:
                parent = None
                # NOTE: Root-level folders have parent_id=None, not parent_id=ROOT_DIRECTORY_ID.
                # The sentinel record exists only for access control purposes; it does not
                # participate in the parent/child hierarchy of ordinary folders.
                children = (
                    session.query(Folder)
                    .filter(Folder.parent_id.is_(None), Folder.id != ROOT_DIRECTORY_ID)
                    .all()
                )
                documents = (
                    session.query(Document).filter(Document.folder_id.is_(None)).all()
                )
                root_folder = session.get(Folder, ROOT_DIRECTORY_ID)
                has_permission = (
                    Permissions.SUPER_LIST_DIRECTORY in this_user.all_permissions
                    or (
                        root_folder is not None
                        and root_folder.check_access_requirements(this_user, "read")
                    )
                )
            else:
                folder = session.get(Folder, folder_id)
                if not folder or folder.id == ROOT_DIRECTORY_ID:
                    handler.conclude_request(404, {}, smsg.DIRECTORY_NOT_FOUND)
                    return 404, folder_id, handler.username

                has_permission = (
                    Permissions.SUPER_LIST_DIRECTORY in this_user.all_permissions
                    or folder.check_access_requirements(this_user, "read")
                )
                parent = folder.parent
                children = folder.children
                documents = folder.documents

            if not has_permission:
                handler.conclude_request(403, {}, smsg.ACCESS_DENIED)
                return 403, folder_id, handler.username

            active_documents = [document for document in documents if document.active]

            if parent:
                parent_id = parent.id
            elif not folder_id:
                parent_id = None
            else:
                parent_id = "/"

            response = {
                "code": 200,
                "message": "Directory listing successful",
                "data": {
                    "parent_id": parent_id,
                    "documents": [
                        {
                            "id": document.id,
                            "title": document.title,
                            "created_time": document.created_time,
                            "last_modified": (
                                last_revision := document.get_latest_revision()
                            ).created_time,
                            "sha256": last_revision.file.sha256,
                            "size": last_revision.file.size,
                        }
                        for document in active_documents
                    ],
                    "folders": [
                        {
                            "id": child.id,
                            "name": child.name,
                            "created_time": child.created_time,
                        }
                        for child in children
                    ],
                },
            }

        # Send the response back to the client
        handler.conclude_request(**response)
        return 200, folder_id, handler.username


class RequestGetDirectoryInfoHandler(RequestHandler):
    """
    Handles directory information requests.
    This util processes a directory information request by retrieving information about the specified directory.
    It sends an appropriate response back to the client, indicating success or failure.
    Args:
        handler (ConnectionHandler): The connection handler containing request data and methods for responding.
    Response Codes:
        200 - Directory info successful, returns directory info in the response data.
        400 - Invalid request.
        403 - Invalid user or token.
        404 - Directory not found.
        500 - Internal server error, with the exception message.
    """

    data_schema = {
        "type": "object",
        "properties": {"directory_id": {"type": "string", "minLength": 1}},
        "required": ["directory_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        directory_id: str = handler.data["directory_id"]

        if not directory_id:
            handler.conclude_request(400, {}, "Directory ID is required")
            return

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None  # require_auth ensures this

            directory = session.get(Folder, directory_id)

            if not directory or directory.id == ROOT_DIRECTORY_ID:
                handler.conclude_request(404, {}, smsg.DIRECTORY_NOT_FOUND)
                return 404, directory_id, handler.username

            if not directory.check_access_requirements(user, access_type="read"):
                handler.conclude_request(403, {}, "Permission denied")
                return 403, directory_id, handler.username

            info_code = 0
            ### generate access_rules text
            access_rules = []
            if Permissions.VIEW_ACCESS_RULES in user.all_permissions:
                for each_rule in directory.access_rules:
                    access_rules.append(
                        {
                            "rule_id": each_rule.id,
                            "rule_data": each_rule.rule_data,
                            "access_type": each_rule.access_type,
                        }
                    )
            else:
                info_code = 1  # 无权访问目录

            data = {
                "directory_id": directory.id,
                "count_of_child": directory.count_of_child,
                "parent_id": directory.parent_id,
                "name": directory.name,
                "created_time": directory.created_time,
                "access_rules": access_rules,
                "info_code": info_code,
            }

            handler.conclude_request(200, data, "Directory info retrieved successfully")
            return 0, directory_id, handler.username


class RequestGetDirectoryAccessRulesHandler(RequestHandler):
    data_schema = {
        "type": "object",
        "properties": {"directory_id": {"type": "string", "minLength": 1}},
        "required": ["directory_id"],
        "additionalProperties": False,
    }
    require_auth = True

    def handle(self, handler: ConnectionHandler):

        directory_id: str = handler.data["directory_id"]

        with Session() as session:
            user = session.get(User, handler.username)
            directory = session.get(Folder, directory_id)

            if user is None or not user.is_token_valid(handler.token):
                handler.conclude_request(403, {}, "Invalid user or token")
                return 401, directory_id

            if not directory:
                handler.conclude_request(404, {}, "Document not found")
                return 404, directory_id, handler.username

            if (
                not directory.check_access_requirements(user, access_type="read")
                or not Permissions.VIEW_ACCESS_RULES in user.all_permissions
            ):
                handler.conclude_request(403, {}, "Permission denied")
                return 403, directory_id, handler.username

            # generate access_rules
            access_rules: dict[str, list] = {}

            for each_rule in directory.access_rules:
                if each_rule.access_type not in access_rules:
                    access_rules[each_rule.access_type] = []
                access_rules[each_rule.access_type].append(each_rule.rule_data)

            handler.conclude_request(
                200,
                {"rules": access_rules, "inherit": directory.inherit},
                "Directory access rules retrieved successfully",
            )
            return 0, directory_id, handler.username


class RequestCreateDirectoryHandler(RequestHandler):
    """
    Handles directory creation requests.
    This util processes a directory creation request by creating a new directory in the specified parent directory.
    It sends an appropriate response back to the client, indicating success or failure.
    Args:
        handler (ConnectionHandler): The connection handler containing request data and methods for responding.
    Response Codes:
        200 - Directory created successfully, returns the created directory in the response data.
        400 - Invalid request.
        403 - Invalid user or token.
        404 - Parent directory not found.
        500 - Internal server error, with the exception message.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "parent_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "name": {"type": "string", "minLength": 1},
            "access_rules": {
                "type": "object",
                "properties": {},
                "additionalProperties": {"type": "array", "items": {}},
            },
            "exists_ok": {"type": "boolean"},
            "inherit_parent": {"type": "boolean"},
        },
        "required": ["name"],
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        data = handler.data
        parent_id = data.get("parent_id")
        name = data["name"]
        access_rules = data.get("access_rules", {})
        exists_ok = data.get("exists_ok", False)
        inherit_parent = data.get("inherit_parent", True)

        if parent_id == ROOT_DIRECTORY_ID:
            handler.conclude_request(404, {}, smsg.DIRECTORY_NOT_FOUND)
            return

        with Session() as session:
            this_user = session.get(User, handler.username)
            assert this_user is not None  # require_auth ensures this

            if Permissions.CREATE_DIRECTORY not in this_user.all_permissions:
                handler.conclude_request(
                    403, {}, "You have no permissions to create directories"
                )
                return 403, parent_id, handler.username

            parent = None
            if parent_id:
                parent = session.get(Folder, parent_id)
                if not parent:
                    handler.conclude_request(404, {}, smsg.DIRECTORY_NOT_FOUND)
                    return 404, parent_id, handler.username
                if not parent.check_access_requirements(this_user, "write"):
                    handler.conclude_request(
                        403, {}, "Access denied for parent directory"
                    )
                    return 403, parent_id, handler.username
            else:
                root_folder = session.get(Folder, ROOT_DIRECTORY_ID)
                has_root_write = (
                    root_folder.check_access_requirements(this_user, "write")
                    if root_folder
                    else True
                )
                if (
                    not has_root_write
                    and Permissions.SUPER_CREATE_DIRECTORY
                    not in this_user.all_permissions
                ):
                    handler.conclude_request(403, {}, smsg.ACCESS_DENIED)
                    return 403, parent_id, handler.username

            if not global_config["document"]["allow_name_duplicate"]:
                existing_doc = (
                    session.query(Document)
                    .filter_by(folder_id=parent_id if parent_id else None, title=name)
                    .first()
                )
                if existing_doc:
                    handler.conclude_request(
                        400,
                        {"type": "document", "id": existing_doc.id},
                        smsg.DOCUMENT_NAME_DUPLICATE,
                    )
                    return

                existing_folder = (
                    session.query(Folder)
                    .filter_by(parent_id=parent_id if parent_id else None, name=name)
                    .first()
                )

                if existing_folder:
                    if exists_ok:
                        handler.conclude_request(
                            200,
                            {
                                "id": existing_folder.id,
                                "name": existing_folder.name,
                                "last_modified": existing_folder.created_time,
                            },
                            "Directory already exists",
                        )
                        return
                    else:
                        handler.conclude_request(400, {}, smsg.DIRECTORY_NAME_DUPLICATE)
                        return

            folder = Folder(name=name, parent=parent)
            if not apply_access_rules(folder, access_rules, this_user, inherit_parent):
                session.rollback()
                handler.conclude_request(
                    403, {}, "Set access rules failed: permission denied"
                )
                return 403, parent_id, handler.username

            session.add(folder)
            session.commit()

            handler.conclude_request(
                200,
                {
                    "id": folder.id,
                    "name": folder.name,
                    "last_modified": folder.created_time,
                },
                "Directory created successfully",
            )
            return 0, parent_id, handler.username


class RequestDeleteDirectoryHandler(RequestHandler):
    """
    Handles directory deletion requests.
    This util processes a directory deletion request by deleting the specified directory.
    It sends an appropriate response back to the client, indicating success or failure.
    Args:
        handler (ConnectionHandler): The connection handler containing request data and methods for responding.
    Response Codes:
        200 - Directory deleted successfully.
        400 - Invalid request.
        403 - Invalid user or token.
        404 - Directory not found.
        500 - Internal server error, with the exception message.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "folder_id": {"type": "string", "minLength": 1},
        },
        "required": ["folder_id"],
        "additionalProperties": False,
    }

    def handle(self, handler: ConnectionHandler):

        # Parse the directory deletion request
        folder_id = handler.data["folder_id"]  # Get the folder ID from the request data

        if folder_id == ROOT_DIRECTORY_ID:
            handler.conclude_request(404, {}, smsg.DIRECTORY_NOT_FOUND)
            return 404, folder_id, handler.username

        with Session() as session:
            this_user = session.get(User, handler.username)
            if not this_user or not this_user.is_token_valid(handler.token):
                handler.conclude_request(
                    **{"code": 403, "message": "Invalid user or token", "data": {}}
                )
                return 401, folder_id
            folder = session.get(Folder, folder_id)
            if not folder:
                handler.conclude_request(
                    **{"code": 404, "message": "Directory not found", "data": {}}
                )
                return 404, folder_id, handler.username
            if (
                Permissions.DELETE_DIRECTORY not in this_user.all_permissions
                or not folder.check_access_requirements(this_user, "write")
            ):
                handler.conclude_request(
                    **{"code": 403, "message": "Access denied", "data": {}}
                )
                return 403, folder_id, handler.username

            operation_id = f"OP_DEL_{secrets.token_hex(8)}_{int(time.time())}"
            now = time.time()

            # analyze subtree, determine deletable items and protected items,
            # prepare for batch deletion
            (
                deletable_folder_ids,
                deletable_doc_ids,
                failed_items,
                protected_folder_ids,
                folder_map,
            ) = fetch_subtree_for_deletion(session, folder_id, this_user, now=now)

            # execute batch deletion in a transaction

            # 2a. mark documents for deletion in DB; failures are logged.
            for chunk in batched(list(deletable_doc_ids), QUERY_CHUNK_SIZE):
                session.query(Document).filter(Document.id.in_(list(chunk))).update(
                    {
                        "status": EntityStatus.DELETED,
                        "status_operation_id": operation_id,
                    },
                    synchronize_session=False,
                )

            # 2b. Mark folders as DELETED
            for chunk in batched(list(deletable_folder_ids), QUERY_CHUNK_SIZE):
                session.query(Folder).filter(Folder.id.in_(list(chunk))).update(
                    {
                        "status": EntityStatus.DELETED,
                        "status_operation_id": operation_id,
                    },
                    synchronize_session=False,
                )

            # 2c. Mark the root folder as DELETED
            root_fully_deletable = (
                len(protected_folder_ids) == 0 and len(failed_items) == 0
            )
            if root_fully_deletable:
                folder.status = EntityStatus.DELETED
                folder.status_operation_id = operation_id

            session.commit()

            # construct response based on deletion result
            if failed_items:
                handler.conclude_request(
                    207,  # 207 Multi-Status：partial success
                    {
                        "deleted_folders": list(deletable_folder_ids),
                        "deleted_documents": list(deletable_doc_ids),
                        "root_deleted": root_fully_deletable,
                        "failed": failed_items,
                    },
                    "Directory partially deleted: some items could not be removed due to insufficient permissions.",
                )
                return 207, folder_id, handler.username
            else:
                handler.conclude_request(
                    200, {}, "Directory marked as deleted successfully"
                )
                return 0, folder_id, handler.username


class RequestRenameDirectoryHandler(RequestHandler):
    """
    Handles directory renaming requests.
    This util processes a directory renaming request by updating the name of the specified directory.
    It sends an appropriate response back to the client, indicating success or failure.
    Args:
        handler (ConnectionHandler): The connection handler containing request data and methods for responding.
    Response Codes:
        200 - Directory renamed successfully.
        400 - Invalid request.
        403 - Invalid user or token.
        404 - Directory not found.
        500 - Internal server error, with the exception message.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "folder_id": {"type": "string", "minLength": 1},
            "new_name": {"type": "string", "minLength": 1},
        },
        "required": ["folder_id", "new_name"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        # Parse the directory renaming request
        folder_id = handler.data["folder_id"]
        new_name = handler.data["new_name"]

        if folder_id == ROOT_DIRECTORY_ID:
            handler.conclude_request(404, {}, smsg.DIRECTORY_NOT_FOUND)
            return 404, folder_id, handler.username

        with Session() as session:
            this_user = session.get(User, handler.username)
            assert this_user is not None  # require_auth ensures this

            folder = session.get(Folder, folder_id)
            if not folder:
                handler.conclude_request(404, {}, smsg.DIRECTORY_NOT_FOUND)
                return 404, folder_id, handler.username
            if (
                Permissions.RENAME_DIRECTORY not in this_user.all_permissions
                or not folder.check_access_requirements(this_user, "write")
            ):
                handler.conclude_request(
                    **{"code": 403, "message": "Access denied", "data": {}}
                )
                return 403, folder_id, handler.username

            if folder.name == new_name:
                handler.conclude_request(
                    **{
                        "code": 400,
                        "message": "New name is the same as the current name",
                        "data": {},
                    }
                )
                return

            if not global_config["document"]["allow_name_duplicate"]:
                existing_folder = (
                    session.query(Folder)
                    .filter_by(
                        parent_id=folder.parent_id if folder.parent_id else None,
                        name=new_name,
                    )
                    .first()
                )
                existing_document = (
                    session.query(Document)
                    .filter_by(
                        folder_id=folder.parent_id if folder.parent_id else None,
                        title=new_name,
                    )
                    .first()
                )

                if existing_document:
                    if existing_document.active:
                        handler.conclude_request(400, {}, smsg.DOCUMENT_NAME_DUPLICATE)
                        return
                    else:
                        # 如果该文档尚未被激活，则先尝试删除未激活的文档
                        if existing_document.check_access_requirements(
                            this_user, "write"
                        ):  # 如果有权删除
                            existing_document.delete_all_revisions(do_commit=False)
                            session.delete(existing_document)
                            session.commit()
                        else:
                            handler.conclude_request(403, {}, smsg.ACCESS_DENIED)
                            return (
                                403,
                                folder_id,
                                {
                                    "title": existing_document.title,
                                    "duplicate_id": existing_document.id,
                                },
                                handler.username,
                            )

                elif existing_folder:  # 第二步判断有无同名文件夹
                    handler.conclude_request(
                        400,
                        {},
                        smsg.DIRECTORY_NAME_DUPLICATE,  # 第一步判断已经知道没有同名文档，则一定是同名文件夹
                    )
                    return

            folder.name = new_name
            session.commit()

            handler.conclude_request(
                **{
                    "code": 200,
                    "message": "Directory renamed successfully",
                    "data": {},
                }
            )
            return 0, folder_id, handler.username


class RequestMoveDirectoryHandler(RequestHandler):

    data_schema = {
        "type": "object",
        "properties": {
            "folder_id": {"type": "string", "minLength": 1},
            "target_folder_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["folder_id", "target_folder_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        folder_id: str = handler.data["folder_id"]
        target_folder_id: Optional[str] = handler.data.get("target_folder_id")

        if folder_id == ROOT_DIRECTORY_ID:
            handler.conclude_request(404, {}, smsg.DIRECTORY_NOT_FOUND)
            return 404, folder_id, handler.username

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None  # require_auth ensures this

            if Permissions.MOVE not in user.all_permissions:
                handler.conclude_request(403, {}, smsg.ACCESS_DENIED_MOVE_DIRECTORY)
                return 403, folder_id, handler.username

            folder = session.get(Folder, folder_id)

            if not folder:
                handler.conclude_request(
                    **{
                        "code": 404,
                        "message": smsg.SUBJECT_DIRECTORY_NOT_FOUND,
                        "data": {},
                    }
                )
                return 404, folder_id, handler.username

            if not folder.check_access_requirements(user, "move"):
                handler.conclude_request(403, {}, smsg.ACCESS_DENIED_MOVE_DIRECTORY)
                return 403, folder_id, handler.username

            if not global_config["document"]["allow_name_duplicate"]:
                existing_folder = (
                    session.query(Folder)
                    .filter_by(
                        parent_id=target_folder_id,
                        name=folder.name,
                    )
                    .first()
                )
                existing_document = (
                    session.query(Document)
                    .filter_by(
                        folder_id=target_folder_id,
                        title=folder.name,
                    )
                    .first()
                )

                if existing_document:
                    if existing_document.active:
                        handler.conclude_request(400, {}, smsg.DOCUMENT_NAME_DUPLICATE)
                        return
                    else:
                        # 如果该文档尚未被激活，则先尝试删除未激活的文档
                        if existing_document.check_access_requirements(
                            user, "write"
                        ):  # 如果有权删除
                            existing_document.delete_all_revisions(do_commit=False)
                            session.delete(existing_document)
                            session.commit()
                        else:
                            handler.conclude_request(403, {}, smsg.ACCESS_DENIED)
                            return (
                                403,
                                folder_id,
                                {
                                    "title": existing_document.title,
                                    "duplicate_id": existing_document.id,
                                },
                                handler.username,
                            )

                elif existing_folder:  # 第二步判断有无同名文件夹
                    handler.conclude_request(
                        400,
                        {},
                        smsg.DIRECTORY_NAME_DUPLICATE,
                    )
                    return

            if target_folder_id:
                target_folder = session.get(Folder, target_folder_id)
                if not target_folder:
                    handler.conclude_request(
                        **{
                            "code": 404,
                            "message": smsg.TARGET_DIRECTORY_NOT_FOUND,
                            "data": {},
                        }
                    )
                    return 404, folder_id, handler.username

                if not target_folder.check_access_requirements(
                    user, "write"
                ):  # 对于目标文件夹，移动可视为一种写操作
                    handler.conclude_request(
                        403, {}, smsg.ACCESS_DENIED_WRITE_DIRECTORY
                    )
                    return 403, folder_id, handler.username

                # Check if target folder is a descendant of the folder being moved
                if target_folder.id == folder.id or target_folder.is_descendant_of(
                    folder
                ):
                    handler.conclude_request(
                        400, {}, smsg.CANNOT_MOVE_DIRECTORY_INTO_SUBDIRECTORY
                    )
                    return 400, folder_id, handler.username

                folder.parent = target_folder
            else:
                root_folder = session.get(Folder, ROOT_DIRECTORY_ID)
                if (
                    root_folder is not None
                    and not root_folder.check_access_requirements(user, "write")
                    and Permissions.SUPER_CREATE_DIRECTORY not in user.all_permissions
                ):
                    handler.conclude_request(
                        403, {}, smsg.ACCESS_DENIED_WRITE_DIRECTORY
                    )
                    return 403, folder_id, handler.username
                folder.parent = None

            session.commit()

        handler.conclude_request(200, {}, smsg.SUCCESS)
        return 0, folder_id, handler.username


class RequestSetDirectoryRulesHandler(RequestHandler):
    """
    Handles the "set_directory_rules" action.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "directory_id": {"type": "string", "minLength": 1},
            "access_rules": {
                "type": "object",
                "properties": {},
                "additionalProperties": {"type": "array", "items": {}},
            },
            "inherit_parent": {"type": "boolean"},
        },
        "required": ["directory_id", "access_rules"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        """
        Handles the directory access rules setting request from the client.
        """
        directory_id: str = handler.data["directory_id"]
        access_rules_to_apply: dict = handler.data["access_rules"]
        inherit_parent: bool = handler.data.get("inherit_parent", True)

        if not handler.username:
            handler.conclude_request(
                **{"code": 401, "message": "Authentication is required", "data": {}}
            )
            return 401, directory_id

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None  # require_auth ensures this

            directory = session.get(Folder, directory_id)

            if not directory:
                handler.conclude_request(404, {}, "Directory not found")
                return 404, directory_id, handler.username

            if not Permissions.SET_ACCESS_RULES in user.all_permissions:
                handler.conclude_request(403, {}, "Access denied to set access rules")
                return 403, directory_id, handler.username

            if not directory.check_access_requirements(user, access_type="manage"):
                handler.conclude_request(403, {}, "Access denied to the directory")
                return 403, directory_id, handler.username

            try:
                if apply_access_rules(
                    directory, access_rules_to_apply, user, inherit_parent
                ):
                    session.commit()
                    handler.conclude_request(200, {}, "Set access rules successfully")
                    return 0, directory_id, handler.username
                else:
                    session.rollback()
                    handler.conclude_request(
                        403, {}, "Set access rules failed: permission denied"
                    )
                    return 403, directory_id, handler.username
            except (ValueError, jsonschema.ValidationError) as exc:
                session.rollback()
                handler.conclude_request(
                    400, {}, f"Set access rules failed: {str(exc)}"
                )
                return 400, directory_id, handler.username


class RequestPurgeDirectoryHandler(RequestHandler):
    """
    Handles the "purge_directory" action.
    Permanently removes a directory, all its subdirectories, and all documents within.
    This action is irreversible.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "folder_id": {"type": "string", "minLength": 1},
        },
        "required": ["folder_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        folder_id = handler.data["folder_id"]

        if folder_id == ROOT_DIRECTORY_ID:
            handler.conclude_request(403, {}, "Cannot purge the root directory")
            return 403, folder_id, handler.username

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None

            if Permissions.PURGE not in user.all_permissions:
                handler.conclude_request(
                    403, {}, "No permission to permanently purge data"
                )
                return 403, folder_id, handler.username

            folder = session.get(
                Folder, folder_id, execution_options={"include_deleted": True}
            )

            if not folder:
                handler.conclude_request(404, {}, "Directory not found")
                return 404, folder_id, handler.username

            if folder.status != EntityStatus.DELETED:
                handler.conclude_request(
                    400, {}, "Directory must be marked as deleted before purging"
                )
                return 400, folder_id, handler.username

            if not folder.check_access_requirements(user, "write"):
                handler.conclude_request(403, {}, "Access denied to the directory")
                return 403, folder_id, handler.username

            try:
                (
                    all_folder_ids,
                    all_doc_ids,
                    failed_items,
                    _,
                    folder_map,
                ) = fetch_subtree_for_deletion(
                    session, folder_id, user, include_deleted=True
                )

                if failed_items:
                    handler.conclude_request(
                        403,
                        {"failed": failed_items},
                        "Some items in the directory cannot be purged due to insufficient permissions",
                    )
                    return 403, folder_id, handler.username

                session.autoflush = False

                if all_doc_ids:
                    purge_documents_bulk(session, list(all_doc_ids))

                if all_folder_ids:
                    for chunk in batched(all_folder_ids, QUERY_CHUNK_SIZE):
                        session.query(Folder).filter(Folder.id.in_(chunk)).delete(
                            synchronize_session=False
                        )

                session.delete(folder)
                session.commit()

                handler.conclude_request(
                    200,
                    {},
                    "Directory and all its contents have been permanently purged",
                )
                return 0, folder_id, handler.username

            finally:
                session.autoflush = True


class RequestRestoreDirectoryHandler(RequestHandler):
    """
    Handles the "restore_directory" action.
    Supports virtual ROOT_DIRECTORY_ID translation to database None.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "folder_id": {"type": "string", "minLength": 1},
            "target_parent_id": {"type": ["string", "null"], "minLength": 1},
            "new_name": {"type": "string", "minLength": 1},
        },
        "required": ["folder_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        folder_id = handler.data["folder_id"]
        target_parent_provided = "target_parent_id" in handler.data
        target_parent_id = handler.data.get("target_parent_id")
        new_name = handler.data.get("new_name")

        if folder_id == ROOT_DIRECTORY_ID:
            handler.conclude_request(400, {}, "Cannot restore root directory")
            return 400, folder_id, handler.username

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None

            if Permissions.RESTORE not in user.all_permissions:
                handler.conclude_request(403, {}, "No permission to restore data")
                return 403, folder_id, handler.username

            folder = session.get(
                Folder, folder_id, execution_options={"include_deleted": True}
            )

            if not folder or folder.status != EntityStatus.DELETED:
                handler.conclude_request(404, {}, "Deleted directory not found")
                return 404, folder_id, handler.username

            if not folder.check_access_requirements(user, "write"):
                handler.conclude_request(
                    403, {}, "Access denied to directory being restored"
                )
                return 403, folder_id, handler.username

            if target_parent_provided:
                db_parent_id = (
                    None if target_parent_id == ROOT_DIRECTORY_ID else target_parent_id
                )
            else:
                db_parent_id = folder.parent_id

            final_name = new_name if new_name else folder.name

            if db_parent_id is None:
                root_obj = session.get(Folder, ROOT_DIRECTORY_ID)
                if root_obj and not root_obj.check_access_requirements(user, "write"):
                    handler.conclude_request(403, {}, "Access denied to root directory")
                    return 403, ROOT_DIRECTORY_ID, handler.username
            else:
                target_parent = session.get(
                    Folder, db_parent_id, execution_options={"include_deleted": True}
                )
                if not target_parent or target_parent.status != EntityStatus.OK:
                    handler.conclude_request(409, {}, "Target directory is not active")
                    return 409, db_parent_id, handler.username

                if not target_parent.check_access_requirements(user, "write"):
                    handler.conclude_request(
                        403, {}, "Access denied to target directory"
                    )
                    return 403, db_parent_id, handler.username

            existing_conflict = (
                session.query(Folder)
                .filter(
                    Folder.parent_id == db_parent_id,
                    Folder.name == final_name,
                    Folder.status == EntityStatus.OK,
                )
                .first()
                or session.query(Document)
                .filter(
                    Document.folder_id == db_parent_id,
                    Document.title == final_name,
                    Document.status == EntityStatus.OK,
                )
                .first()
            )

            if existing_conflict:
                handler.conclude_request(
                    409, {"conflict_id": existing_conflict.id}, "Name conflict"
                )
                return 409, folder_id, handler.username

            op_id = folder.status_operation_id

            if op_id:
                # 批量恢复文档
                session.query(Document).execution_options(include_deleted=True).filter(
                    Document.status_operation_id == op_id,
                    Document.status == EntityStatus.DELETED,
                ).update(
                    {"status": EntityStatus.OK, "status_operation_id": None},
                    synchronize_session=False,
                )

                # 批量恢复文件夹
                session.query(Folder).execution_options(include_deleted=True).filter(
                    Folder.status_operation_id == op_id,
                    Folder.status == EntityStatus.DELETED,
                    Folder.id != folder.id,
                ).update(
                    {"status": EntityStatus.OK, "status_operation_id": None},
                    synchronize_session=False,
                )

            folder.status = EntityStatus.OK
            folder.status_operation_id = None
            folder.name = final_name
            folder.parent_id = db_parent_id

            session.commit()

            handler.conclude_request(
                200, {"parent_id": db_parent_id, "name": final_name}, smsg.SUCCESS
            )
            return 0, folder_id, handler.username


class RequestListDeletedItemsHandler(RequestHandler):
    """
    Handles the "list_deleted_items" action.
    Lists folders and documents that have been marked as deleted within
     a specific parent directory.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "folder_id": {"type": "string", "minLength": 1},
        },
        "required": ["folder_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        parent_id = handler.data["folder_id"]

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None

            if Permissions.LIST_DELETED_ITEMS not in user.all_permissions:
                handler.conclude_request(403, {}, smsg.PERMISSION_DENIED)
                return 403, parent_id, handler.username

            db_parent_id = None if parent_id == ROOT_DIRECTORY_ID else parent_id

            parent_folder = session.get(
                Folder,
                db_parent_id or ROOT_DIRECTORY_ID,
                execution_options={"include_deleted": True},
            )

            # FIXME: Unify the access requirement check response
            if not parent_folder or (
                Permissions.SUPER_LIST_DIRECTORY not in user.all_permissions
                and not parent_folder.check_access_requirements(user, "read")
            ):
                handler.conclude_request(404, {}, "Directory not found")
                return 404, parent_id, handler.username

            deleted_folders = (
                session.query(Folder)
                .execution_options(include_deleted=True)
                .filter(
                    Folder.parent_id == db_parent_id,
                    Folder.status == EntityStatus.DELETED,
                )
                .all()
            )

            deleted_documents = (
                session.query(Document)
                .execution_options(include_deleted=True)
                .filter(
                    Document.folder_id == db_parent_id,
                    Document.status == EntityStatus.DELETED,
                )
                .all()
            )

            result_data = {
                "folders": [
                    {
                        "id": f.id,
                        "name": f.name,
                        "created_time": f.created_time,
                        "status_operation_id": f.status_operation_id,
                    }
                    for f in deleted_folders
                ],
                "documents": [
                    {
                        "id": d.id,
                        "title": d.title,
                        "created_time": d.created_time,
                        "status_operation_id": d.status_operation_id,
                    }
                    for d in deleted_documents
                ],
                "parent_id": parent_id,
            }

            handler.conclude_request(200, result_data, "Deleted items retrieved")
            return 0, parent_id, handler.username
