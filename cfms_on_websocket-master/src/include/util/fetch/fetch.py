from typing import Literal

from sqlalchemy import or_

from include.database.models.blocking import UserBlockEntry, UserBlockSubEntry
from include.database.models.classic import ObjectAccessEntry, User
from include.constants import AVAILABLE_BLOCK_TYPES


def prefetch_user_blocks(
    session,
    user: User,
    access_type: str,
    now: float,
) -> tuple[bool, set[str]]:
    if access_type not in AVAILABLE_BLOCK_TYPES:
        return False, set()

    block_entries = (
        session.query(UserBlockEntry)
        .join(UserBlockSubEntry, UserBlockSubEntry.parent_id == UserBlockEntry.block_id)
        .filter(
            UserBlockEntry.username == user.username,
            UserBlockEntry.not_before <= now,
            (UserBlockEntry.not_after == -1) | (UserBlockEntry.not_after >= now),
            UserBlockSubEntry.block_type == access_type,
        )
        .all()
    )

    is_globally_blocked = any(entry.target_type == "all" for entry in block_entries)
    blocked_ids = {
        entry.target_id
        for entry in block_entries
        if entry.target_type != "all" and entry.target_id
    }

    return is_globally_blocked, blocked_ids


def batch_prefetch_granted_ids(
    session,
    user: User,
    obj_ids: list[str],
    target_type: Literal["document", "directory"],
    access_type: str,
    now: float,
) -> set[str]:
    """
    Batch prefetch object IDs that the user has been granted access to.
    This function queries the database to retrieve a set of object identifiers
    for which the specified user (directly or through their group memberships)
    has the requested access type at the given time.
    Args:
        session: SQLAlchemy session for database queries.
        user (User): The user object containing username and group memberships.
        obj_ids (list[str]): List of object identifiers to check access for.
        target_type (Literal["document", "directory"]): The type of target object.
        access_type (str): The type of access to check (e.g., "read", "write").
        now (float): The current timestamp used to validate access validity window.
    Returns:
        set[str]: A set of object identifiers that the user has been granted
                  access to based on their direct permissions or group memberships.
                  Returns an empty set if obj_ids is empty or no matching entries found.
    """

    if not obj_ids:
        return set()

    entity_identifiers = [user.username] + [g.group_name for g in user.groups]

    rows = (
        session.query(ObjectAccessEntry.target_identifier)
        .filter(
            ObjectAccessEntry.target_type == target_type,
            ObjectAccessEntry.target_identifier.in_(obj_ids),
            ObjectAccessEntry.entity_identifier.in_(entity_identifiers),
            ObjectAccessEntry.access_type == access_type,
            ObjectAccessEntry.start_time <= now,
            or_(
                ObjectAccessEntry.end_time == None,
                ObjectAccessEntry.end_time >= now,
            ),
        )
        .all()
    )
    return {row[0] for row in rows}
