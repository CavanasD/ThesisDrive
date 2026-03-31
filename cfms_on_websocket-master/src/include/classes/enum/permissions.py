__all__ = ["Permissions"]

from enum import StrEnum


class Permissions(StrEnum):
    # 文件与目录操作
    MOVE = "move"
    CREATE_DOCUMENT = "create_document"
    DELETE_DOCUMENT = "delete_document"
    RENAME_DOCUMENT = "rename_document"
    CREATE_DIRECTORY = "create_directory"
    DELETE_DIRECTORY = "delete_directory"
    RENAME_DIRECTORY = "rename_directory"

    LIST_DELETED_ITEMS = "list_deleted_items"
    """permission to view the list of deleted documents/directories in a directory."""
    PURGE = "purge"
    """permission to permanently delete documents/directories."""
    RESTORE = "restore"
    """permission to restore documents/directories from deletion."""

    # 超级权限操作 (Super)
    SUPER_CREATE_DOCUMENT = "super_create_document"
    SUPER_CREATE_DIRECTORY = "super_create_directory"
    SUPER_LIST_DIRECTORY = "super_list_directory"
    SUPER_SET_PASSWD = "super_set_passwd"
    SUPER_SET_USER_AVATAR = "super_set_user_avatar"

    # 系统与管理
    SHUTDOWN = "shutdown"
    MANAGE_SYSTEM = "manage_system"
    """
    A general permission for performing various system management 
    tasks that have not been assigned to other specific permissions.
    """
    DEBUGGING = "debugging"

    # 用户管理
    CREATE_USER = "create_user"
    DELETE_USER = "delete_user"
    RENAME_USER = "rename_user"
    MANAGE_USER_STATUS = "manage_user_status"
    GET_USER_INFO = "get_user_info"
    LIST_USERS = "list_users"
    MANAGE_2FA = "manage_2fa"
    SET_PASSWD = "set_passwd"

    # 组管理
    CREATE_GROUP = "create_group"
    DELETE_GROUP = "delete_group"
    RENAME_GROUP = "rename_group"
    GET_GROUP_INFO = "get_group_info"
    LIST_GROUPS = "list_groups"
    CHANGE_USER_GROUPS = "change_user_groups"
    SET_GROUP_PERMISSIONS = "set_group_permissions"

    # 访问控制与锁定
    VIEW_ACCESS_RULES = "view_access_rules"
    SET_ACCESS_RULES = "set_access_rules"
    MANAGE_ACCESS = "manage_access"
    VIEW_ACCESS_ENTRIES = "view_access_entries"
    APPLY_LOCKDOWN = "apply_lockdown"
    BYPASS_LOCKDOWN = "bypass_lockdown"
    BLOCK = "block"
    UNBLOCK = "unblock"
    LIST_USER_BLOCKS = "list_user_blocks"

    # 日志与版本控制
    VIEW_AUDIT_LOGS = "view_audit_logs"
    LIST_REVISIONS = "list_revisions"
    VIEW_REVISION = "view_revision"
    SET_CURRENT_REVISION = "set_current_revision"
    DELETE_REVISION = "delete_revision"

    # 密钥管理
    MANAGE_KEYRINGS = "manage_keyrings"
