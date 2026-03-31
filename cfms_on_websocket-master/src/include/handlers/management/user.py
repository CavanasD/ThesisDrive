__all__ = [
    "RequestListUsersHandler",
    "RequestCreateUserHandler",
    "RequestDeleteUserHandler",
    "RequestRenameUserHandler",
    "RequestBlockUserHandler",
    "RequestUnblockUserHandler",
    "RequestListUserBlocksHandler",
    "RequestGetUserInfoHandler",
    "RequestGetUserAvatarHandler",
    "RequestSetUserAvatarHandler",
    "RequestChangeUserGroupsHandler",
    "RequestSetPasswdHandler",
    "RequestManageUserStatusHandler",
]

import time
import filetype
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from typing import Optional

from include.classes.enum.status import UserStatus
from include.classes.exceptions import UserNotActiveError

# Module-level PasswordHasher instance — reused across all calls to avoid
# repeated construction overhead.
_password_hasher = PasswordHasher()

from include.classes.enum.permissions import Permissions
from include.constants import AVAILABLE_BLOCK_TYPES
from include.classes.handler import ConnectionHandler
from include.classes.request import RequestHandler
from include.conf_loader import global_config
from include.database.handler import Session
from include.database.models.classic import (
    User,
    UserGroup,
)
from include.database.models.blocking import (
    UserBlockEntry,
    UserBlockSubEntry,
)
from include.database.models.entity import Document
from include.handlers.document import create_file_task
from include.util.user import create_user
from include.util.pwd import (
    InvaildPasswordLengthError,
    MissingComponentsError,
    check_passwd_requirements,
)
import include.system.messages as smsg


class RequestListUsersHandler(RequestHandler):
    data_schema = {
        "type": "object",
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        with Session() as session:
            this_user = session.get(User, handler.username)
            assert this_user is not None

            if Permissions.LIST_USERS not in this_user.all_permissions:
                handler.conclude_request(
                    code=403,
                    message="You do not have permission to list users",
                    data={},
                )
                return

            users = session.query(User).all()
            users_data = [
                {
                    "username": user.username,
                    "nickname": user.nickname,
                    "created_time": user.created_time,
                    "last_login": user.last_login,
                    "permissions": list(user.all_permissions),
                    "groups": list(user.all_groups),
                }
                for user in users
            ]

            handler.conclude_request(
                code=200,
                message="List of users",
                data={"users": users_data},
            )


class RequestCreateUserHandler(RequestHandler):

    data_schema = {
        "type": "object",
        "properties": {
            "username": {"type": "string", "minLength": 1, "maxLength": 64},
            "password": {"type": "string"},
            "nickname": {"type": "string"},
            "permissions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "permission": {"type": "string"},
                        "start_time": {"type": "number"},
                        "end_time": {"type": "number"},
                    },
                    "required": ["permission", "start_time"],
                    "additionalProperties": False,
                },
            },
            "groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "group_name": {"type": "string"},
                        "start_time": {"type": "number"},
                        "end_time": {"type": "number"},
                    },
                    "required": ["group_name", "start_time"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["username", "password"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        data = handler.data
        new_username = data["username"]
        new_password = data["password"]
        new_nickname = data.get("nickname")
        new_user_rights = data.get("permissions", [])
        new_user_groups = data.get("groups", [])

        with Session() as session:
            this_user = session.get(User, handler.username)
            assert this_user is not None

            # currently handle_create_user() will not judge whether the requesting
            # user is eligible to apply the given permissions for the new user.
            #
            # "create_user" is a dangerous privilege that should only be held by administrators.

            if Permissions.CREATE_USER not in this_user.all_permissions:
                handler.conclude_request(
                    403, {}, "You do not have permission to create users"
                )
                return

            user_exists = (
                session.query(User.username).filter_by(username=new_username).first()
                is not None
            )
            if user_exists:
                handler.conclude_request(400, {}, "Username already exists")
                return

            if new_user_groups:
                requested_group_names = {g["group_name"] for g in new_user_groups}
                existing_groups = (
                    session.query(UserGroup.group_name)
                    .filter(UserGroup.group_name.in_(requested_group_names))
                    .all()
                )
                existing_group_names = {row[0] for row in existing_groups}

                missing_groups = requested_group_names - existing_group_names
                if missing_groups:
                    handler.conclude_request(
                        400, {}, f"Groups do not exist: {', '.join(missing_groups)}"
                    )
                    return

            create_user(
                username=new_username,
                password=new_password,
                nickname=new_nickname,
                permissions=new_user_rights,
                groups=new_user_groups,
            )

        handler.conclude_request(200, {}, "User created successfully")
        return 0, new_username, handler.username


class RequestDeleteUserHandler(RequestHandler):
    data_schema = {
        "type": "object",
        "properties": {
            "username": {"type": "string", "minLength": 1},
        },
        "required": ["username"],
        "additionalProperties": False,
    }

    def handle(self, handler: ConnectionHandler):

        with Session() as session:
            this_user = session.get(User, handler.username)

            if not this_user or not this_user.is_token_valid(handler.token):
                handler.conclude_request(
                    **{"code": 403, "message": "Invalid user or token", "data": {}}
                )
                return

            if Permissions.DELETE_USER not in this_user.all_permissions:
                handler.conclude_request(
                    **{
                        "code": 403,
                        "message": "You do not have permission to delete users",
                        "data": {},
                    }
                )
                return

            user_to_delete_username = handler.data["username"]
            if not user_to_delete_username:
                handler.conclude_request(
                    **{"code": 400, "message": "Username is required", "data": {}}
                )
                return

            user_to_delete = session.get(User, user_to_delete_username)
            if not user_to_delete:
                handler.conclude_request(
                    **{"code": 404, "message": "User does not exist", "data": {}}
                )
                return

            if user_to_delete.username == this_user.username:
                handler.conclude_request(
                    **{"code": 400, "message": "Cannot delete yourself", "data": {}}
                )
                return

            # if "create_user" not in this_user.all_permissions:
            #     users_with_create_permission = session.query(User).filter(
            #         User.all_permissions.contains("create_user")
            #     ).all()

            #     if len(users_with_create_permission) <= 1:
            #         handler.conclude_request(
            #             **{
            #                 "code": 400,
            #                 "message": "There must be at least one user with 'create_user' permission",
            #                 "data": {},
            #             }
            #         )
            #         return

            for membership in user_to_delete.groups:
                session.delete(membership)

            for block_entry in user_to_delete.block_entries:
                for sub_entry in block_entry.sub_entries:
                    session.delete(sub_entry)

                session.delete(block_entry)

            session.delete(user_to_delete)
            session.commit()

        response = {
            "code": 200,
            "message": "User deleted successfully",
            "data": {},
        }

        handler.conclude_request(**response)


class RequestRenameUserHandler(RequestHandler):
    data_schema = {
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "minLength": 1,
            },
            "nickname": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["username"],
        "additionalProperties": False,
    }

    def handle(self, handler: ConnectionHandler):

        target_username: str = handler.data["username"]

        with Session() as session:
            this_user = session.get(User, handler.username)

            if not this_user or not this_user.is_token_valid(handler.token):
                handler.conclude_request(
                    **{"code": 403, "message": "Invalid user or token", "data": {}}
                )
                return

            if (
                Permissions.RENAME_USER not in this_user.all_permissions
                and target_username != this_user.username
            ):
                handler.conclude_request(
                    **{
                        "code": 403,
                        "message": "You do not have permission to rename users",
                        "data": {},
                    }
                )
                return

            new_nickname = handler.data.get("nickname", None)

            user_to_rename = session.get(User, target_username)
            if not user_to_rename:
                handler.conclude_request(
                    **{"code": 400, "message": "User does not exist", "data": {}}
                )
                return

            user_to_rename.nickname = new_nickname
            session.commit()

        response = {
            "code": 200,
            "message": "User renamed successfully",
            "data": {},
        }

        handler.conclude_request(**response)


class RequestBlockUserHandler(RequestHandler):
    """
    Handler for action `block_user`.

    This operation accepts only one block at a time, and if there are multiple blocks
    (NOT multiple block types), it should be requested in installments.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "minLength": 1,
            },
            "target": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        # "minLength": 1,
                        "pattern": "^(all|directory|document)$",
                    },
                    "id": {"type": "string", "minLength": 1},
                },
                "required": ["type"],
                "additionalProperties": False,
            },
            "block_types": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},  # not empty
            },
            "not_before": {"type": "number", "minimum": 0},
            "not_after": {"type": "number"},
        },
        "required": ["username", "block_types", "target"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        target_username: str = handler.data["username"]
        block_types: list[str] = handler.data["block_types"]

        not_before: int | float = handler.data.get("not_before", 0)
        not_after: int | float = handler.data.get("not_after", -1)

        target_type: str = handler.data["target"]["type"]
        target_id: Optional[str] = handler.data["target"].get("id")

        if not set(block_types).issubset(AVAILABLE_BLOCK_TYPES):
            handler.conclude_request(400, {}, "Unsupported block type(s)")
            return 400, target_username

        if not_after >= 0 and not_after <= not_before:
            handler.conclude_request(
                400, {}, "`not_after` must be later than `not_before`"
            )
            return 400, target_username

        with Session() as session:
            this_user = session.get(User, handler.username)

            if not this_user or not this_user.is_token_valid(handler.token):
                handler.conclude_request(401, {}, "Invaild user or token")
                return 401, target_username

            if Permissions.BLOCK not in this_user.all_permissions:
                handler.conclude_request(
                    403, {}, "You do not have permission to block users"
                )
                return 403, target_username, handler.username

            # 创建主条目
            now = time.time()
            block_entry = UserBlockEntry(
                username=target_username,
                timestamp=now,
                not_before=not_before,
                not_after=not_after,
                target_type=target_type,
                target_id=target_id,
            )
            session.add(block_entry)

            for each_type in block_types:
                new_sub_entry = UserBlockSubEntry(
                    block_type=each_type, parent_entry=block_entry
                )
                session.add(new_sub_entry)

            session.commit()
            # get block_id
            block_id = block_entry.block_id

        handler.conclude_request(200, {"block_id": block_id}, "User blocked")
        return 200, target_username, handler.username


class RequestUnblockUserHandler(RequestHandler):
    """
    Handler for action `unblock_user`.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "block_id": {
                "type": "string",
                "minLength": 1,
            },
        },
        "required": ["block_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        block_id: str = handler.data["block_id"]

        with Session() as session:
            this_user = session.get(User, handler.username)

            if not this_user or not this_user.is_token_valid(handler.token):
                handler.conclude_request(401, {}, "Invaild user or token")
                return 401, block_id

            if Permissions.UNBLOCK not in this_user.all_permissions:
                handler.conclude_request(
                    403, {}, "You do not have permission to unblock users"
                )
                return 403, block_id, handler.username

            block_entry = session.get(UserBlockEntry, block_id)
            if not block_entry:
                handler.conclude_request(404, {}, "Specified entry not found")
                return 404, block_id, handler.username

            if 0 <= block_entry.not_after < time.time():
                handler.conclude_request(400, {}, "The specified block has ended")
                return 400, block_id, handler.username

            # Currently, the operation of unblocking is to remove entries from
            # the database. However, an alternative approach is to set their
            # expiration time to the present.
            session.delete(block_entry)
            session.commit()

        handler.conclude_request(200, {}, "Unblocked user")
        return 200, block_id, handler.username


class RequestListUserBlocksHandler(RequestHandler):
    data_schema = {
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "minLength": 1,
            },
        },
        "required": ["username"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        target_username: str = handler.data["username"]

        with Session() as session:
            this_user = session.get(User, handler.username)

            if not this_user or not this_user.is_token_valid(handler.token):
                handler.conclude_request(401, {}, "Invaild user or token")
                return 401, target_username

            if (
                Permissions.LIST_USER_BLOCKS not in this_user.all_permissions
                and target_username != this_user.username
            ):
                handler.conclude_request(
                    403, {}, "You do not have permission to list user blocks"
                )
                return 403, target_username, handler.username

            block_entries = (
                session.query(UserBlockEntry)
                .filter(UserBlockEntry.username == target_username)
                .all()
            )

            blocks_data = []
            for entry in block_entries:
                sub_entries = (
                    session.query(UserBlockSubEntry)
                    .filter(UserBlockSubEntry.parent_id == entry.block_id)
                    .all()
                )
                blocks_data.append(
                    {
                        "block_id": entry.block_id,
                        "timestamp": entry.timestamp,
                        "not_before": entry.not_before,
                        "not_after": entry.not_after,
                        "target_type": entry.target_type,
                        "target_id": entry.target_id,
                        "block_types": [
                            sub_entry.block_type for sub_entry in sub_entries
                        ],
                    }
                )

        handler.conclude_request(200, {"blocks": blocks_data}, "List of user blocks")
        return 200, target_username, handler.username


class RequestGetUserInfoHandler(RequestHandler):
    data_schema = {
        "type": "object",
        "properties": {
            "username": {"type": "string", "minLength": 1},
        },
        "required": ["username"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        user_to_get_username = handler.data["username"]
        if not user_to_get_username:
            handler.conclude_request(
                **{"code": 400, "message": "Username is required", "data": {}}
            )
            return

        with Session() as session:
            this_user = session.get(User, handler.username)
            assert this_user is not None

            user_to_get = session.get(User, user_to_get_username)
            if not user_to_get:
                handler.conclude_request(
                    **{"code": 404, "message": "User does not exist", "data": {}}
                )
                return

            if (
                user_to_get_username != this_user.username
                and Permissions.GET_USER_INFO not in this_user.all_permissions
            ):
                handler.conclude_request(
                    **{
                        "code": 403,
                        "message": "You do not have permission to get user information",
                        "data": {},
                    }
                )
                return

            user_info = {
                "nickname": user_to_get.nickname,
                "username": user_to_get.username,
                "permissions": list(user_to_get.all_permissions),
                "groups": list(user_to_get.all_groups),
                "last_login": user_to_get.last_login,
                "created_time": user_to_get.created_time,
                "passwd_last_modified": user_to_get.passwd_last_modified,
            }

            handler.conclude_request(
                **{"code": 200, "message": "OK", "data": user_info}
            )


class RequestGetUserAvatarHandler(RequestHandler):
    """
    Handler for action `get_user_avatar`.

    This operation retrieves the avatar file ID of a specified user.
    However, when a user successfully authenticates themselves, their avatar ID is
    already included in the response.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "username": {"type": "string", "minLength": 1},
        },
        "required": ["username"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        user_to_get_username = handler.data["username"]
        if not user_to_get_username:
            handler.conclude_request(
                **{"code": 400, "message": "Username is required", "data": {}}
            )
            return

        with Session() as session:
            # when require_auth is True, user authentication has been verified
            this_user = session.get(User, handler.username)
            assert this_user is not None

            user_to_get = session.get(User, user_to_get_username)
            if not user_to_get:
                handler.conclude_request(
                    **{"code": 404, "message": "User does not exist", "data": {}}
                )
                return

            if (
                user_to_get_username != this_user.username
                and Permissions.GET_USER_INFO not in this_user.all_permissions
            ):
                handler.conclude_request(
                    **{
                        "code": 403,
                        "message": "You do not have permission to get user information",
                        "data": {},
                    }
                )
                return

            avatar = user_to_get.avatar

            if avatar:
                avatar_task_data = create_file_task(avatar, 0)
                handler.conclude_request(
                    200, {"task_data": avatar_task_data}, smsg.SUCCESS
                )
            else:
                handler.conclude_request(404, {}, smsg.TARGET_OBJECT_NOT_FOUND)


class RequestSetUserAvatarHandler(RequestHandler):
    """
    Handler for action `set_user_avatar`.

    This operation sets the user's avatar to the latest revision of a specified document.

    Note: The document itself is not required to be an image file, but its latest revision
    must be an image file. Additionally, if the access permissions of the document originally
    designated as the avatar are changed later, the avatar setting will not be lost.
    """

    data_schema = {
        "type": "object",
        "properties": {
            "username": {"type": "string", "minLength": 1},
            "document_id": {"type": "string", "minLength": 1},
        },
        "required": ["username", "document_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        target_username: str = handler.data["username"]
        document_id: Optional[str] = handler.data["document_id"]

        with Session() as session:
            this_user = session.get(User, handler.username)
            assert this_user is not None

            if (
                target_username != this_user.username
                and Permissions.SUPER_SET_USER_AVATAR not in this_user.all_permissions
            ):
                handler.conclude_request(
                    403, {}, "You do not have permission to set other user's avatar"
                )
                return 403, target_username, handler.username

            user_to_update = session.get(User, target_username)
            if not user_to_update:
                handler.conclude_request(404, {}, "User does not exist")
                return

            # judge whether the user has the right to use the document as avatar
            document = session.get(Document, document_id)
            if not document:
                handler.conclude_request(404, {}, "Document does not exist")
                return

            if not document.check_access_requirements(user_to_update, "read"):
                handler.conclude_request(
                    403, {}, "User does not have access to the specified document"
                )
                return

            latest_rev_file = document.get_latest_revision().file
            # check whether the file is an image
            extension = filetype.guess_extension(latest_rev_file.path)
            if extension not in ["jpg", "jpeg", "png", "gif", "bmp", "webp"]:
                handler.conclude_request(
                    400, {}, "The specified document is not an image file"
                )
                return

            user_to_update.avatar_id = latest_rev_file.id
            session.commit()

        handler.conclude_request(200, {}, "User avatar updated successfully")
        return 200, target_username, handler.username


class RequestChangeUserGroupsHandler(RequestHandler):
    data_schema = {
        "type": "object",
        "properties": {
            "username": {"type": "string", "minLength": 1},
            "groups": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["username"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        with Session() as session:
            this_user = session.get(User, handler.username)
            assert this_user is not None

            if Permissions.CHANGE_USER_GROUPS not in this_user.all_permissions:
                handler.conclude_request(
                    **{
                        "code": 403,
                        "message": "You do not have permission to change user groups",
                        "data": {},
                    }
                )
                return

            user_to_change_username = handler.data["username"]
            if not user_to_change_username:
                handler.conclude_request(
                    **{"code": 400, "message": "Username is required", "data": {}}
                )
                return

            user_to_change = session.get(User, user_to_change_username)
            if not user_to_change:
                handler.conclude_request(
                    **{"code": 404, "message": "User does not exist", "data": {}}
                )
                return

            new_user_groups: list[str] = handler.data.get("groups", [])

            if set(new_user_groups) != user_to_change.all_groups:
                user_to_change.all_groups = new_user_groups
                session.commit()

        response = {
            "code": 200,
            "message": "User groups changed successfully",
            "data": {},
        }

        handler.conclude_request(**response)


class RequestSetPasswdHandler(RequestHandler):
    data_schema = {
        "type": "object",
        "properties": {
            "username": {"type": "string", "minLength": 1},
            "old_passwd": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "new_passwd": {"type": "string", "minLength": 1},
            "force_update_after_login": {"type": "boolean"},
            "bypass_passwd_requirements": {"type": "boolean"},
        },
        "required": ["username", "new_passwd"],
        "additionalProperties": False,
    }

    def handle(self, handler: ConnectionHandler):

        with Session() as session:
            operator_username = handler.username

            target_username = handler.data.get("username", None)
            old_passwd = handler.data.get("old_passwd", None)
            new_passwd: str = handler.data["new_passwd"]
            # sysop feature.
            bypass_passwd_requirements: bool = handler.data.get(
                "bypass_passwd_requirements", False
            )
            force_update_after_login: bool = handler.data.get(
                "force_update_after_login", False
            )

            user = session.get(User, target_username)
            if not user:
                handler.conclude_request(
                    **{"code": 401, "message": "Invalid credentials", "data": {}}
                )
                return

            # 初始化操作员用户，如果没有指定 operator, 则以目标用户充任
            if operator_username:
                if not handler.token:
                    handler.conclude_request(
                        **{
                            "code": 400,
                            "message": "Given an operator, token is required",
                            "data": {},
                        }
                    )
                    return

                operator_user = session.get(User, operator_username)
                if not operator_user or not operator_user.is_token_valid(handler.token):
                    handler.conclude_request(
                        **{
                            "code": 401,
                            "message": "Invalid user or token",
                            "data": {},
                        }
                    )
                    return
            else:  # 这条路径下的 operator_user 应该永远也不会被调用。
                operator_user = None

            if old_passwd:  # 如果指定了旧密码，说明是用户更改自己的密码

                # Disallow these elevated flags when a user is changing their own password
                _flags_set = []
                if bypass_passwd_requirements:
                    _flags_set.append("bypass_passwd_requirements")
                if force_update_after_login:
                    _flags_set.append("force_update_after_login")

                if _flags_set:
                    handler.conclude_request(
                        400,
                        message="The following options cannot be set to True when changing your own password: "
                        + ", ".join(_flags_set),
                        data={flag: True for flag in _flags_set},
                    )
                    return

                if not user.verify_password(old_passwd):
                    handler.conclude_request(
                        **{
                            "code": 401,
                            "message": "Invalid credentials",
                            "data": {},
                        }
                    )
                    return
                if user.status != UserStatus.ACTIVE:
                    handler.conclude_request(
                        403, {}, "Account is not active"
                    )
                    return

                if not (
                    {Permissions.SET_PASSWD, Permissions.SUPER_SET_PASSWD}
                    & user.all_permissions
                ):
                    handler.conclude_request(
                        **{
                            "code": 403,
                            "message": "You do not have permission to change your own password",
                            "data": {},
                        }
                    )
                    return

            else:  # 用户更改其他用户的密码
                if not operator_user:
                    handler.conclude_request(
                        **{
                            "code": 400,
                            "message": "Operator is required when setting other user password",
                            "data": {},
                        }
                    )
                    return
                if not Permissions.SUPER_SET_PASSWD in operator_user.all_permissions:
                    handler.conclude_request(
                        **{
                            "code": 403,
                            "message": "You do not have permission to set user password",
                            "data": {},
                        }
                    )
                    return

            try:
                if not bypass_passwd_requirements:
                    check_passwd_requirements(
                        new_passwd,
                        global_config["security"]["passwd_min_length"],
                        global_config["security"]["passwd_max_length"],
                        global_config["security"]["passwd_must_contain"],
                    )
            except InvaildPasswordLengthError as e:
                handler.conclude_request(
                    400,
                    {"min_length": e.min_length, "max_length": e.max_length},
                    str(e),
                )
                return 400, target_username
            except MissingComponentsError as e:
                handler.conclude_request(400, {"missing": e.missing}, str(e))
                return 400, target_username

            try:
                _same = _password_hasher.verify(user.pass_hash, new_passwd)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                _same = False

            if _same:
                handler.conclude_request(
                    400,
                    {},
                    "New password should not be the same",
                )
                return

            user.set_password(
                new_passwd, force_update_after_login=force_update_after_login
            )
            # session.commit()

        response = {
            "code": 200,
            "message": "Password set successfully",
            "data": {},
        }

        handler.conclude_request(**response)


class RequestManageUserStatusHandler(RequestHandler):
    data_schema = {
        "type": "object",
        "properties": {
            "status": {"enum": ["active", "disabled"]},
            "username": {"type": "string", "minLength": 1},
        },
        "required": ["status", "username"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        new_status: str = handler.data["status"]
        username: str = handler.data["username"]

        with Session() as session:
            this_user = session.get(User, handler.username)
            assert this_user is not None

            if Permissions.MANAGE_USER_STATUS not in this_user.all_permissions:
                handler.conclude_request(
                    403, {}, "You do not have permission to manage user status"
                )
                return 403, None, handler.username

            mapping = {
                "active": UserStatus.ACTIVE,
                "disabled": UserStatus.DISABLED,
            }

            if username == handler.username:
                handler.conclude_request(
                    400, {}, "Cannot change your own account status"
                )
                return 400, username, handler.username

            user = session.get(User, username)
            if not user:
                handler.conclude_request(404, {}, "User does not exist")
                return 404, None, handler.username

            if user.status == mapping[new_status]:
                handler.conclude_request(400, {}, f"User is already {new_status}")
                return 400, None, handler.username
            else:
                user.status = mapping[new_status]

            session.commit()

        handler.conclude_request(200, {}, "User status updated successfully")
        return 200, username, handler.username
