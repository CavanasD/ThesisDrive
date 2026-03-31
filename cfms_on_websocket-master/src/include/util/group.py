import time
from include.database.models.classic import UserGroup, UserGroupPermission
from include.database.handler import Session


def create_group(**kwargs) -> None:

    with Session() as session:
        group = UserGroup(
            group_name=kwargs["group_name"],
            group_display_name=kwargs.get("display_name", None),
        )
        for i in kwargs.get("permissions", []):
            permission = UserGroupPermission(
                group=group,
                permission=i["permission"],
                granted=i.get("granted", True),
                start_time=i.get("start_time", time.time()),
                end_time=i.get("end_time", None)
            )
            group.permissions.append(permission)

        session.add(group)
        session.commit()
