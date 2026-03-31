import time

from argon2 import PasswordHasher

from include.database.models.classic import User, UserMembership, UserPermission
from include.database.handler import Session

# Module-level PasswordHasher instance — reused across all calls to avoid
# repeated construction overhead.
_password_hasher = PasswordHasher()


def create_user(**kwargs) -> None:
    """
    Create a new user in the system.

    This utility hashes the provided password using argon2id and creates
    a user record along with associated permissions and group memberships.

    Args:
        **kwargs: Arbitrary keyword arguments that may include:
            - username (str): The username for the new user.
            - password (str): The password for the new user.
            - nickname (str, optional): The nickname for the new user.
            - permissions (list, optional): A list of dicts for user
              permissions. Each dict may contain:
                - permission (str): The permission to be granted.
                - granted (bool, optional): Whether the permission is
                  granted (default is True).
                - start_time (float, optional): The start time for the
                  permission (default is current time).
                - end_time (float, optional): The end time for the
                  permission (default is None).
            - groups (list, optional): A list of dicts for user group
              memberships. Each dict may contain:
                - group_name (str): The name of the group.
                - start_time (float, optional): The start time for the
                  membership (default is current time).
                - end_time (float, optional): The end time for the
                  membership (default is None).

    Returns:
        None: Commits the new user to the database.
    """

    pass_hash = _password_hasher.hash(kwargs["password"])
    with Session() as session:
        user = User(
            username=kwargs["username"],
            pass_hash=pass_hash,
            nickname=kwargs.get("nickname", None),
            last_login=0,
            created_time=time.time(),
        )
        for i in kwargs.get("permissions", []):
            permission = UserPermission(
                user=user,
                permission=i["permission"],
                granted=i.get("granted", True),
                start_time=i.get("start_time", time.time()),
                end_time=i.get("end_time", None),
            )
            user.rights.append(permission)

        for k in kwargs.get("groups", []):
            membership = UserMembership(
                user=user,
                group_name=k["group_name"],
                start_time=k.get("start_time", time.time()),
                end_time=k.get("end_time", None),
            )
            user.groups.append(membership)

        session.add(user)
        session.commit()
