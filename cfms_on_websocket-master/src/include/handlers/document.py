__all__ = [
    "RequestGetDocumentInfoHandler",
    "RequestGetDocumentHandler",
    "RequestCreateDocumentHandler",
    "RequestUploadDocumentHandler",
    "RequestDeleteDocumentHandler",
    "RequestRenameDocumentHandler",
    "RequestDownloadFileHandler",
    "RequestUploadFileHandler",
    "RequestSetDocumentRulesHandler",
    "RequestMoveDocumentHandler",
]

import datetime
import secrets
import time

import jsonschema

from include.classes.handler import ConnectionHandler
from include.classes.enum.permissions import Permissions
from include.classes.enum.status import EntityStatus
from include.classes.request import RequestHandler
from include.conf_loader import global_config
from include.constants import FILE_TASK_DEFAULT_DURATION_SECONDS
from include.constants import ROOT_DIRECTORY_ID
from include.database.handler import Session
from include.database.models.classic import User
from include.database.models.entity import (
    Document,
    DocumentRevision,
    Folder,
    NoActiveRevisionsError,
)
from include.database.models.file import File, FileTask
from include.util.rule.applying import apply_access_rules
import include.system.messages as smsg


def create_file_task(file: File, transfer_mode: int = 0):
    """
    Creates a new file processing task for the specified file.
    Args:
        file (File): The file object for which the task is to be generated.
    Returns:
        dict or None: A dictionary containing the task details:
            - task_id (int): The unique identifier of the created task.
            - created_at (float): The timestamp when the task was created.
            - start_time (float): The start time of the task.
            - end_time (float): The end time of the task (1 hour after start).
        Returns None if the file with the given file_id does not exist.
    """

    with Session() as session:
        if not file:
            return None

        now = time.time()
        task = FileTask(
            file_id=file.id,
            status=0,
            mode=transfer_mode,
            start_time=now,
            end_time=now + FILE_TASK_DEFAULT_DURATION_SECONDS,
        )
        session.add(task)
        session.commit()

        return {
            "task_id": task.id,
            "start_time": task.start_time,
            "end_time": task.end_time,
        }


class RequestGetDocumentInfoHandler(RequestHandler):
    """
    Handles the "get_document_info" action.
    """

    data_schema = {
        "type": "object",
        "properties": {"document_id": {"type": "string", "minLength": 1}},
        "required": ["document_id"],
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        document_id = handler.data.get("document_id")

        if not document_id:
            handler.conclude_request(400, {}, "Document ID is required")
            return

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None

            document = session.get(Document, document_id)

            if not document:
                handler.conclude_request(404, {}, "Document not found")
                return 404, document_id, handler.username

            try:
                document.get_latest_revision()
            except NoActiveRevisionsError:
                handler.conclude_request(
                    404, {}, "No active revisions found for this document"
                )
                return 404, document_id, handler.username

            if not document.check_access_requirements(user, access_type="read"):
                handler.conclude_request(403, {}, "Permission denied")
                return 403, document_id, handler.username

            info_code = 0
            ### generate access_rules text
            access_rules = []
            if Permissions.VIEW_ACCESS_RULES in user.all_permissions:
                for each_rule in document.access_rules:
                    access_rules.append(
                        {
                            "rule_id": each_rule.id,
                            "rule_data": each_rule.rule_data,
                            "access_type": each_rule.access_type,
                        }
                    )
            else:
                info_code = 1  # 无权访问文档的权限

            data = {
                "document_id": document.id,
                "parent_id": document.folder_id,
                "title": document.title,
                "size": document.get_latest_revision().file.size,
                "created_time": document.created_time,
                "last_modified": document.get_latest_revision().created_time,
                "access_rules": access_rules,
                "info_code": info_code,
            }

            handler.conclude_request(200, data, "Document info retrieved successfully")
            return 0, document_id, handler.username


class RequestGetDocumentAccessRulesHandler(RequestHandler):
    data_schema = {
        "type": "object",
        "properties": {"document_id": {"type": "string", "minLength": 1}},
        "required": ["document_id"],
        "additionalProperties": False,
    }
    require_auth = True

    def handle(self, handler: ConnectionHandler):

        document_id: str = handler.data["document_id"]

        with Session() as session:
            user = session.get(User, handler.username)
            document = session.get(Document, document_id)

            if user is None or not user.is_token_valid(handler.token):
                handler.conclude_request(403, {}, "Invalid user or token")
                return 401, document_id

            if not document:
                handler.conclude_request(404, {}, "Document not found")
                return 404, document_id, handler.username

            if (
                not document.check_access_requirements(user, access_type="read")
                or not Permissions.VIEW_ACCESS_RULES in user.all_permissions
            ):
                handler.conclude_request(403, {}, "Permission denied")
                return 403, document_id, handler.username

            # generate access_rules
            access_rules: dict[str, list] = {}

            for each_rule in document.access_rules:
                if each_rule.access_type not in access_rules:
                    access_rules[each_rule.access_type] = []
                access_rules[each_rule.access_type].append(each_rule.rule_data)

            handler.conclude_request(
                200,
                {"rules": access_rules, "inherit": document.inherit},
                "Document access rules retrieved successfully",
            )
            return 0, document_id, handler.username


class RequestGetDocumentHandler(RequestHandler):
    """
    Handles the "get_document" action.
    """

    data_schema = {
        "type": "object",
        "properties": {"document_id": {"type": "string", "minLength": 1}},
        "required": ["document_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        document_id: str = handler.data["document_id"]

        with Session() as session:
            user = session.get(User, handler.username)
            document = session.get(Document, document_id)
            assert user is not None

            if not document:
                handler.conclude_request(404, {}, "Document not found")
                return 404, document_id, handler.username

            if not document.check_access_requirements(user):
                handler.conclude_request(403, {}, "Access denied to the document")
                return 403, document_id, handler.username

            try:
                latest_revision = document.get_latest_revision()
            except NoActiveRevisionsError:
                handler.conclude_request(
                    404, {}, "No active revisions found for this document"
                )
                return 4041, document_id, handler.username

            data = {
                "document_id": document.id,
                "title": document.title,
                "task_data": create_file_task(latest_revision.file),
            }

            handler.conclude_request(200, data, "Document successfully fetched")
            return 0, document_id, handler.username


class RequestCreateDocumentHandler(RequestHandler):
    """
    Handles the "create_document" action.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "folder_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "title": {"type": "string", "minLength": 1},
            "access_rules": {"type": "object"},
            "inherit_parent": {"type": "boolean"},
        },
        "required": ["title"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        folder_id = handler.data.get("folder_id") or None
        title = (handler.data.get("title") or "").strip()
        access_rules = handler.data.get("access_rules") or {}
        inherit_parent = handler.data.get("inherit_parent", True)

        if not title:
            handler.conclude_request(400, {}, "Document title is required")
            return

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None

            if Permissions.CREATE_DOCUMENT not in user.all_permissions:
                handler.conclude_request(403, {}, "Permission denied")
                return 403, folder_id, {"title": title}, handler.username

            if folder_id:
                folder = session.get(Folder, folder_id)
                if not folder or folder.id == ROOT_DIRECTORY_ID:
                    handler.conclude_request(404, {}, "Folder not found")
                    return 404, folder_id, {"title": title}, handler.username

                if (
                    not folder.check_access_requirements(user, access_type="write")
                    and Permissions.SUPER_CREATE_DOCUMENT not in user.all_permissions
                ):
                    handler.conclude_request(403, {}, "Access denied to the folder")
                    return 403, folder_id, {"title": title}, handler.username
            else:
                root_folder = session.get(Folder, ROOT_DIRECTORY_ID)
                if (
                    root_folder is not None
                    and not root_folder.check_access_requirements(
                        user, access_type="write"
                    )
                    and Permissions.SUPER_CREATE_DOCUMENT not in user.all_permissions
                ):
                    handler.conclude_request(403, {}, "Access denied to the folder")
                    return 403, folder_id, {"title": title}, handler.username

            if not global_config["document"]["allow_name_duplicate"]:
                existing_doc = (
                    session.query(Document)
                    .filter_by(folder_id=folder_id, title=title)
                    .first()
                )

                if existing_doc:
                    if existing_doc.active:
                        resp_id = (
                            existing_doc.id
                            if existing_doc.check_access_requirements(user, "read")
                            else None
                        )
                        handler.conclude_request(
                            409,
                            {"type": "document", "id": resp_id},
                            smsg.DOCUMENT_NAME_DUPLICATE,
                        )
                        return
                    else:
                        if existing_doc.check_access_requirements(user, "write"):
                            try:
                                existing_doc.delete_all_revisions()
                            except PermissionError:
                                handler.conclude_request(
                                    500,
                                    {},
                                    "Failed to delete revisions. Perhaps a file task is in progress?",
                                )
                                return (
                                    500,
                                    folder_id,
                                    {"title": title},
                                    handler.username,
                                )
                            session.delete(existing_doc)
                        else:
                            resp_id = (
                                existing_doc.id
                                if existing_doc.check_access_requirements(user, "read")
                                else None
                            )
                            handler.conclude_request(
                                409,
                                {"type": "document", "id": resp_id},
                                smsg.DENIED_FOR_DOC_NAME_DUPLICATE,
                            )
                            return (
                                409,
                                folder_id,
                                {"title": title, "duplicate_id": existing_doc.id},
                                handler.username,
                            )
                else:
                    existing_folder = (
                        session.query(Folder)
                        .filter_by(parent_id=folder_id, name=title)
                        .first()
                    )
                    if existing_folder:
                        resp_id = (
                            existing_folder.id
                            if existing_folder.check_access_requirements(user, "read")
                            else None
                        )
                        handler.conclude_request(
                            409,
                            {"type": "directory", "id": resp_id},
                            smsg.DIRECTORY_NAME_DUPLICATE,
                        )
                        return

            today = datetime.date.today()
            file_id = secrets.token_hex(32)
            real_filename = secrets.token_hex(32)

            new_file = File(
                id=file_id,
                path=f"./content/files/{today.year}/{today.month}/{real_filename}",
            )
            new_document = Document(
                id=secrets.token_hex(32),
                title=title,
                folder_id=folder_id,
            )
            new_revision = DocumentRevision(file_id=new_file.id)
            new_document.revisions.append(new_revision)

            try:
                if not apply_access_rules(
                    new_document, access_rules, user, inherit_parent
                ):
                    session.rollback()
                    handler.conclude_request(
                        403, {}, "Set access rules failed: permission denied"
                    )
                    return 403, folder_id, {"title": title}, handler.username

                session.add(new_file)
                session.add(new_document)
                session.add(new_revision)

                new_document.current_revision = new_revision
                session.commit()

                task_data = create_file_task(new_revision.file, transfer_mode=1)
                handler.conclude_request(
                    200,
                    {"document_id": new_document.id, "task_data": task_data},
                    "Task successfully created",
                )

                return 0, folder_id, {"title": title}, handler.username

            except (ValueError, jsonschema.ValidationError) as exc:
                session.rollback()
                handler.conclude_request(
                    400, {}, f"Set access rules failed: {str(exc)}"
                )
                return 400, folder_id, {"title": title}, handler.username


class RequestUploadDocumentHandler(RequestHandler):
    """
    Handles the "upload_document" action.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "document_id": {"type": "string", "minLength": 1},
        },
        "required": ["document_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        document_id = handler.data["document_id"]

        with Session() as session:
            document = session.get(Document, document_id)
            this_user = session.get(User, handler.username)
            assert this_user is not None

            if document:
                if not document.check_access_requirements(
                    this_user, access_type="write"
                ):
                    handler.conclude_request(403, {}, "Access denied to the document")
                    return 403, document_id, handler.username

                today = datetime.date.today()

                file_id = secrets.token_hex(32)
                real_filename = secrets.token_hex(32)

                new_file = File(
                    id=file_id,
                    path=f"./content/files/{today.year}/{today.month}/{real_filename}",
                )

                try:
                    latest_revision_id = document.get_latest_revision().id
                except NoActiveRevisionsError:
                    latest_revision_id = None

                new_revision = DocumentRevision(
                    document_id=document_id,
                    file_id=file_id,
                    parent_revision_id=latest_revision_id,
                )
                document.revisions.append(new_revision)

                session.add(new_file)
                session.add(new_revision)

                document.current_revision = new_revision
                session.commit()

            else:
                handler.conclude_request(404, {}, "Document not found")
                return 404, document_id, handler.username

            task_data = create_file_task(new_file, 1)

        handler.conclude_request(
            200, {"task_data": task_data}, "Task successfully created"
        )
        return 0, document_id, task_data, handler.username


class RequestDeleteDocumentHandler(RequestHandler):
    """
    Handles the "delete_document" action.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "document_id": {"type": "string", "minLength": 1},
        },
        "required": ["document_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        document_id = handler.data["document_id"]

        with Session() as session:
            user = session.get(User, handler.username)
            document = session.get(Document, document_id)
            assert user is not None

            if not document:
                handler.conclude_request(404, {}, "Document not found")
                return 404, document_id, handler.username

            if (
                Permissions.DELETE_DOCUMENT not in user.all_permissions
                or not document.check_access_requirements(user, access_type="write")
            ):
                handler.conclude_request(403, {}, "Access denied to the document")
                return 403, document_id, handler.username

            document.status = EntityStatus.DELETED
            document.status_operation_id = (
                f"OP_DEL_{secrets.token_hex(8)}_{int(time.time())}"
            )
            session.commit()

        handler.conclude_request(200, {}, "Document successfully deleted")
        return 0, document_id, handler.username


class RequestRenameDocumentHandler(RequestHandler):
    """
    Handles the "rename_document" action.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "document_id": {"type": "string", "minLength": 1},
            "new_title": {"type": "string", "minLength": 1},
        },
        "required": ["document_id", "new_title"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        # Parse the directory renaming request
        document_id: str = handler.data["document_id"]
        new_title: str = handler.data["new_title"]

        with Session() as session:
            this_user = session.get(User, handler.username)
            document = session.get(Document, document_id)
            assert this_user is not None

            if not document:
                handler.conclude_request(
                    **{"code": 404, "message": "Document not found", "data": {}}
                )
                return 404, document_id, handler.username
            if (
                Permissions.RENAME_DOCUMENT not in this_user.all_permissions
                or not document.check_access_requirements(this_user, "write")
            ):
                handler.conclude_request(
                    **{"code": 403, "message": "Access denied", "data": {}}
                )
                return 403, document_id, handler.username

            if document.title == new_title:
                handler.conclude_request(
                    **{
                        "code": 400,
                        "message": "New name is the same as the current name",
                        "data": {},
                    }
                )
                return

            if not global_config["document"]["allow_name_duplicate"]:
                # 检查是否有同名文件或文件夹

                # 检查同一 folder_id 下是否有与目标名同名文件
                existing_doc = (
                    session.query(Document)
                    .filter_by(
                        folder_id=(document.folder_id if document.folder_id else None),
                        title=new_title,
                    )
                    .first()
                )
                # 检查同一 folder_id 下是否有同名文件夹
                existing_folder = (
                    session.query(Folder)
                    .filter_by(
                        parent_id=(document.folder_id if document.folder_id else None),
                        name=new_title,
                    )
                    .first()
                )

                if existing_doc:
                    if existing_doc.active:
                        handler.conclude_request(400, {}, smsg.DOCUMENT_NAME_DUPLICATE)
                        return
                    else:
                        # 如果该文档尚未被激活，则先尝试删除未激活的文档
                        if existing_doc.check_access_requirements(
                            this_user, "write"
                        ):  # 如果有权删除
                            existing_doc.delete_all_revisions()
                            session.delete(existing_doc)
                            session.commit()
                        else:
                            handler.conclude_request(403, {}, smsg.ACCESS_DENIED)
                            return (
                                403,
                                document.folder_id,
                                {
                                    "title": document.title,
                                    "duplicate_id": existing_doc.id,
                                },
                                handler.username,
                            )
                elif existing_folder:
                    handler.conclude_request(400, {}, smsg.DIRECTORY_NAME_DUPLICATE)
                    return

            document.title = new_title
            session.commit()

            handler.conclude_request(
                **{
                    "code": 200,
                    "message": "Document renamed successfully",
                    "data": {},
                }
            )
            return 0, document_id, handler.username


class RequestDownloadFileHandler(RequestHandler):
    """
    Handles the "download_file" action.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "minLength": 1},
        },
        "required": ["task_id"],
        "additionalProperties": False,
    }

    def handle(self, handler: ConnectionHandler):
        task_id: str = handler.data["task_id"]

        with Session() as session:
            task = session.get(FileTask, task_id)
            if not task:
                handler.conclude_request(404, {}, "Task not found")
                return

            if task.status != 0 or task.mode != 0:
                handler.conclude_request(
                    400, {}, "Task is not in a valid state for download"
                )
                return

            if task.start_time > time.time() or (
                task.end_time and task.end_time < time.time()
            ):
                handler.conclude_request(
                    400, {}, "Task is either not started yet or has already ended"
                )
                return

        ### 服务器还需要发送一次响应
        handler.send_file(task_id)


class RequestUploadFileHandler(RequestHandler):
    """
    Handles the "upload_file" action.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "minLength": 1},
        },
        "required": ["task_id"],
        "additionalProperties": False,
    }

    def handle(self, handler: ConnectionHandler):
        task_id = handler.data["task_id"]

        with Session() as session:
            task = session.get(FileTask, task_id)
            if not task:
                handler.conclude_request(404, {}, "Task not found")
                return

            if task.status != 0 or task.mode != 1:
                handler.conclude_request(
                    400, {}, "Task is not in a valid state for upload"
                )
                return

            if task.start_time > time.time() or (
                task.end_time and task.end_time < time.time()
            ):
                handler.conclude_request(
                    400, {}, "Task is either not started yet or has already ended"
                )
                return

        ### 服务器需要发送一次响应
        handler.receive_file(task_id)


class RequestSetDocumentRulesHandler(RequestHandler):
    """
    Handles the "set_document_rules" action.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "document_id": {"type": "string", "minLength": 1},
            "access_rules": {
                "type": "object",
                "properties": {},
                "additionalProperties": {"type": "array", "items": {}},
            },
            "inherit_parent": {"type": "boolean"},
        },
        "required": ["document_id", "access_rules"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        """
        Handles the document access rules setting request from the client.
        """
        document_id: str = handler.data["document_id"]
        access_rules_to_apply: dict = handler.data["access_rules"]
        inherit_parent: bool = handler.data.get("inherit_parent", True)

        if not handler.username:
            handler.conclude_request(
                **{"code": 401, "message": "Authentication is required", "data": {}}
            )
            return 401, document_id

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None

            document = session.get(Document, document_id)

            if not document:
                handler.conclude_request(404, {}, "Document not found")
                return 404, document_id, handler.username

            if Permissions.SET_ACCESS_RULES not in user.all_permissions:
                handler.conclude_request(403, {}, "Access denied to set access rules")
                return 403, document_id, handler.username

            if not document.check_access_requirements(user, access_type="manage"):
                handler.conclude_request(403, {}, "Access denied to the document")
                return 403, document_id, handler.username

            try:
                if apply_access_rules(
                    document, access_rules_to_apply, user, inherit_parent
                ):
                    session.commit()
                    handler.conclude_request(200, {}, "Set access rules successfully")
                    return 0, document_id, handler.username
                else:
                    session.rollback()
                    handler.conclude_request(
                        403, {}, "Set access rules failed: permission denied"
                    )
                    return 403, document_id, handler.username
            except (ValueError, jsonschema.ValidationError) as exc:
                session.rollback()
                handler.conclude_request(
                    400, {}, f"Set access rules failed: {str(exc)}"
                )
                return 400, document_id, handler.username


class RequestMoveDocumentHandler(RequestHandler):
    """
    Handles the "move_document" action.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "document_id": {"type": "string", "minLength": 1},
            "target_folder_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["document_id"],  # , "target_folder_id"
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        document_id: str = handler.data["document_id"]
        target_folder_id: str = handler.data.get("target_folder_id", "")

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None

            if Permissions.MOVE not in user.all_permissions:
                handler.conclude_request(403, {}, smsg.ACCESS_DENIED_MOVE_DOCUMENT)
                return (
                    403,
                    document_id,
                    {"target_folder_id": target_folder_id},
                    handler.username,
                )

            document = session.get(Document, document_id)
            if not document:
                handler.conclude_request(
                    **{
                        "code": 404,
                        "message": smsg.TARGET_DOCUMENT_NOT_FOUND,
                        "data": {},
                    }
                )
                return (
                    404,
                    document_id,
                    {"target_folder_id": target_folder_id},
                    handler.username,
                )

            if document.folder_id == target_folder_id:
                handler.conclude_request(400, {}, "Cannot move to the same folder")
                return (
                    400,
                    document_id,
                    {"target_folder_id": target_folder_id},
                    handler.username,
                )

            if not document.check_access_requirements(user, "move"):
                handler.conclude_request(403, {}, smsg.ACCESS_DENIED_MOVE_DOCUMENT)
                return (
                    403,
                    document_id,
                    {"target_folder_id": target_folder_id},
                    handler.username,
                )

            if not global_config["document"]["allow_name_duplicate"]:
                # 检查是否有同名文件或文件夹

                # 检查同一 folder_id 下是否有同名文件
                existing_doc = (
                    session.query(Document)
                    .filter_by(
                        folder_id=target_folder_id,
                        title=document.title,
                    )
                    .first()
                )
                # 检查同一 folder_id 下是否有同名文件夹
                existing_folder = (
                    session.query(Folder)
                    .filter_by(
                        parent_id=target_folder_id,
                        name=document.title,
                    )
                    .first()
                )

                if existing_doc:
                    if existing_doc.active:
                        handler.conclude_request(400, {}, smsg.DOCUMENT_NAME_DUPLICATE)
                        return
                    else:
                        # 如果该文档尚未被激活，则先尝试删除未激活的文档
                        if existing_doc.check_access_requirements(
                            user, "write"
                        ):  # 如果有权删除
                            existing_doc.delete_all_revisions()
                            session.delete(existing_doc)
                            session.commit()
                        else:
                            handler.conclude_request(403, {}, smsg.ACCESS_DENIED)
                            return (
                                403,
                                document.folder_id,
                                {
                                    "title": document.title,
                                    "duplicate_id": existing_doc.id,
                                },
                                handler.username,
                            )
                elif existing_folder:
                    handler.conclude_request(400, {}, smsg.DIRECTORY_NAME_DUPLICATE)
                    return

            if target_folder_id:
                target_folder = session.get(Folder, target_folder_id)
                if not target_folder or target_folder.id == ROOT_DIRECTORY_ID:
                    handler.conclude_request(
                        **{
                            "code": 404,
                            "message": smsg.TARGET_DIRECTORY_NOT_FOUND,
                            "data": {},
                        }
                    )
                    return (
                        404,
                        document_id,
                        {"target_folder_id": target_folder_id},
                        handler.username,
                    )

                if not target_folder.check_access_requirements(
                    user, "write"
                ):  # 对于目标文件夹，移动可视为一种写操作
                    handler.conclude_request(
                        403, {}, smsg.ACCESS_DENIED_WRITE_DIRECTORY
                    )
                    return (
                        403,
                        document_id,
                        {"target_folder_id": target_folder_id},
                        handler.username,
                    )

                document.folder = target_folder
            else:
                root_folder = session.get(Folder, ROOT_DIRECTORY_ID)
                if (
                    root_folder is not None
                    and not root_folder.check_access_requirements(user, "write")
                    and Permissions.SUPER_CREATE_DOCUMENT not in user.all_permissions
                ):
                    handler.conclude_request(
                        403, {}, smsg.ACCESS_DENIED_WRITE_DIRECTORY
                    )
                    return (
                        403,
                        document_id,
                        {"target_folder_id": target_folder_id},
                        handler.username,
                    )
                document.folder = None

            session.commit()

        handler.conclude_request(200, {}, smsg.SUCCESS)
        return 0, document_id, {"target_folder_id": target_folder_id}, handler.username


class RequestPurgeDocumentHandler(RequestHandler):
    """
    Handles the "purge_document" action, which permanently deletes a document and all its revisions.

    This action is irreversible and should only be allowed for users with special permissions.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "document_id": {"type": "string", "minLength": 1},
        },
        "required": ["document_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        doc_id = handler.data["document_id"]
        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None

            if Permissions.PURGE not in user.all_permissions:
                handler.conclude_request(403, {}, "No permission to permanently delete")
                return

            document = session.get(
                Document, doc_id, execution_options={"include_deleted": True}
            )
            if document is None:
                handler.conclude_request(404, {}, "Document not found")
                return

            if document.status != EntityStatus.DELETED:
                handler.conclude_request(
                    400, {}, "Document must be marked as deleted before purging"
                )
                return

            if not document.check_access_requirements(user, "write"):
                handler.conclude_request(403, {}, "Access denied to the document")
                return

            document.delete_all_revisions(do_commit=False)
            session.delete(document)
            session.commit()

        handler.conclude_request(200, {}, "Document permanently deleted")
        return 0, doc_id, handler.username


class RequestRestoreDocumentHandler(RequestHandler):
    """
    Handles the "restore_document" action.
    Restores a marked-as-deleted document. Supports renaming and moving to a
    new folder during restoration. Maps virtual ROOT_DIRECTORY_ID to database None.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "document_id": {"type": "string", "minLength": 1},
            "target_folder_id": {"type": ["string", "null"], "minLength": 1},
            "new_title": {"type": "string", "minLength": 1},
        },
        "required": ["document_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        doc_id = handler.data["document_id"]

        target_folder_provided = "target_folder_id" in handler.data
        target_folder_id = handler.data.get("target_folder_id")
        new_title = handler.data.get("new_title")

        with Session() as session:
            user = session.get(User, handler.username)
            assert user is not None

            if Permissions.RESTORE not in user.all_permissions:
                handler.conclude_request(403, {}, smsg.PERMISSION_DENIED)
                return 403, doc_id, handler.username

            document = session.get(
                Document, doc_id, execution_options={"include_deleted": True}
            )

            if not document or document.status != EntityStatus.DELETED:
                handler.conclude_request(404, {}, "Deleted document not found")
                return 404, doc_id, handler.username

            if not document.check_access_requirements(user, "write"):
                handler.conclude_request(403, {}, "Access denied to the document")
                return 403, doc_id, handler.username

            if target_folder_provided:
                db_folder_id = (
                    None if target_folder_id == ROOT_DIRECTORY_ID else target_folder_id
                )
            else:
                db_folder_id = document.folder_id

            final_title = new_title if new_title else document.title

            if db_folder_id is None:
                root_obj = session.get(Folder, ROOT_DIRECTORY_ID)
                if root_obj and not root_obj.check_access_requirements(user, "write"):
                    handler.conclude_request(
                        403, {}, "Access denied to the root directory"
                    )
                    return 403, ROOT_DIRECTORY_ID, handler.username
            else:
                target_folder = session.get(
                    Folder, db_folder_id, execution_options={"include_deleted": True}
                )
                if not target_folder:
                    handler.conclude_request(404, {}, "Target folder not found")
                    return 404, db_folder_id, handler.username

                if not target_folder.check_access_requirements(user, "write"):
                    handler.conclude_request(
                        403, {}, "Access denied to the target folder"
                    )
                    return 403, db_folder_id, handler.username

                if target_folder.status != EntityStatus.OK:
                    handler.conclude_request(
                        409,
                        {"folder_id": db_folder_id},
                        "Cannot restore: Target folder is deleted. Restore it first.",
                    )
                    return 409, doc_id, handler.username

            existing_conflict = (
                session.query(Document)
                .filter(
                    Document.folder_id == db_folder_id,
                    Document.title == final_title,
                    Document.status == EntityStatus.OK,
                )
                .first()
                or session.query(Folder)
                .filter(
                    Folder.parent_id == db_folder_id,
                    Folder.name == final_title,
                    Folder.status == EntityStatus.OK,
                )
                .first()
            )

            if existing_conflict:
                handler.conclude_request(
                    409,
                    {"conflict_id": existing_conflict.id},
                    f"Conflict: An active item named '{final_title}' already exists in the destination.",
                )
                return 409, doc_id, handler.username

            document.status = EntityStatus.OK
            document.status_operation_id = None
            document.title = final_title
            document.folder_id = db_folder_id

            session.commit()

            handler.conclude_request(
                200,
                {
                    "title": final_title,
                    "folder_id": db_folder_id,
                },
                "Document successfully restored",
            )
            return 0, doc_id, handler.username
