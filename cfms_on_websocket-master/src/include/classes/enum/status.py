__all__ = ["EntityStatus", "DocumentRevisionStatus", "UserStatus"]

from enum import IntEnum


class EntityStatus(IntEnum):
    OK = 0
    DELETED = 1
    LOCKED = 2


class DocumentRevisionStatus(IntEnum):
    OK = 0
    DELETED = 1


class UserStatus(IntEnum):
    ACTIVE = 0
    DISABLED = 1