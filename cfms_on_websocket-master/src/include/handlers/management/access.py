__all__ = ["RequestGrantAccessHandler", "RequestRevokeAccessHandler"]

from include.classes.handler import ConnectionHandler
from include.classes.enum.permissions import Permissions
from include.classes.request import RequestHandler
from include.database.handler import Session
from include.database.models.classic import (
    ObjectAccessEntry,
    User,
    UserGroup,
)
from include.database.models.entity import (
    Document,
    Folder,
)
import include.system.messages as smsg

ENTITY_TYPE_MAPPING = {"user": User, "group": UserGroup}
TARGET_TYPE_MAPPING = {"document": Document, "directory": Folder}


class RequestGrantAccessHandler(RequestHandler):

    data_schema = {
        "type": "object",
        "properties": {
            "entity_type": {
                "type": "string",
                "minLength": 1,
                "pattern": "^(user|group)$",
            },
            "entity_identifier": {"type": "string", "minLength": 1},
            "target_type": {
                "type": "string",
                "minLength": 1,
                "pattern": "^(document|directory)$",
            },
            "target_identifier": {"type": "string", "minLength": 1},
            "access_types": {"type": "array", "items": {"type": "string"}},
            "start_time": {
                "type": "number",
                "minimum": 0,
            },
            "end_time": {"type": "number", "minimum": 0},
        },
        "required": [
            "entity_type",
            "entity_identifier",
            "target_type",
            "target_identifier",
            "access_types",
            "start_time",
        ],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):

        entity_type: str = handler.data["entity_type"]
        entity_identifier: str = handler.data["entity_identifier"]

        target_type: str = handler.data["target_type"]
        target_identifier: str = handler.data["target_identifier"]

        access_types: list[str] = handler.data["access_types"]
        start_time: float = handler.data["start_time"]
        end_time: float | None = handler.data.get("end_time")

        with Session() as session:

            if end_time and not start_time <= end_time:
                handler.conclude_request(
                    400, {}, "The start time should be before the end time"
                )
                return 400, None, handler.data, handler.username

            operator = session.get(User, handler.username)
            assert operator is not None

            if Permissions.MANAGE_ACCESS not in operator.all_permissions:
                handler.conclude_request(
                    code=403,
                    message="You do not have permission to manage object access",
                    data={},
                )
                return 403, handler.username

            entity: User | UserGroup | None = session.get(
                ENTITY_TYPE_MAPPING[entity_type], entity_identifier
            )
            if not entity:
                handler.conclude_request(404, {}, "entity not found")
                return (
                    404,
                    None,
                    handler.data,
                    handler.username,
                )

            target: Document | Folder | None = session.get(
                TARGET_TYPE_MAPPING[target_type], target_identifier
            )
            if not target:
                handler.conclude_request(404, {}, "target not found")
                return (
                    404,
                    None,
                    handler.data,
                    handler.username,
                )

            for access_type in access_types:

                if not target.check_access_requirements(operator, access_type):
                    handler.conclude_request(403, {}, "access denied")
                    return (
                        403,
                        None,
                        handler.data,
                        handler.username,
                    )

                new = ObjectAccessEntry(
                    entity_type=entity_type,
                    entity_identifier=entity_identifier,
                    target_type=target_type,
                    target_identifier=target_identifier,
                    access_type=access_type,
                    start_time=start_time,
                    end_time=end_time,
                )
                session.add(new)

            session.commit()

        handler.conclude_request(200, {}, smsg.SUCCESS)
        return 200, None, handler.data, handler.username


class RequestViewAccessEntriesHandler(RequestHandler):

    data_schema = {
        "type": "object",
        "properties": {
            "object_type": {
                "type": "string",
                "minLength": 1,
                "pattern": "^(user|group|document|directory)$",
            },
            "object_identifier": {"type": "string", "minLength": 1},
        },
        "required": [
            "object_type",
            "object_identifier",
        ],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        object_type: str = handler.data["object_type"]
        object_identifier: str = handler.data["object_identifier"]

        with Session() as session:

            operator = session.get(User, handler.username)
            assert operator is not None

            if Permissions.VIEW_ACCESS_ENTRIES not in operator.all_permissions:
                handler.conclude_request(
                    code=403,
                    message="You do not have permission to view access entries",
                    data={},
                )
                return 403, handler.username

            if object_type in ["user", "group"]:
                _query_result = (
                    session.query(ObjectAccessEntry)
                    .filter(
                        ObjectAccessEntry.entity_type == object_type,
                        ObjectAccessEntry.entity_identifier == object_identifier,
                    )
                    .all()
                )
            else:
                _query_result = (
                    session.query(ObjectAccessEntry)
                    .filter(
                        ObjectAccessEntry.target_type == object_type,
                        ObjectAccessEntry.target_identifier == object_identifier,
                    )
                    .all()
                )

            result = [
                {
                    "id": each.id,
                    "entity_type": each.entity_type,
                    "entity_identifier": each.entity_identifier,
                    "target_type": each.target_type,
                    "target_identifier": each.target_identifier,
                    "access_type": each.access_type,
                    "start_time": each.start_time,
                    "end_time": each.end_time,
                }
                for each in _query_result
            ]

        handler.conclude_request(200, {"result": result}, smsg.SUCCESS)
        return (
            200,
            None,
            {"object_type": object_type, "object_identifier": object_identifier},
            handler.username,
        )


class RequestRevokeAccessHandler(RequestHandler):

    data_schema = {
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "integer",
                "minimum": 1,
            },
        },
        "required": ["entry_id"],
        "additionalProperties": False,
    }

    require_auth = True

    def handle(self, handler: ConnectionHandler):
        entry_id: int = handler.data["entry_id"]

        with Session() as session:

            operator = session.get(User, handler.username)
            assert operator is not None

            if Permissions.MANAGE_ACCESS not in operator.all_permissions:
                handler.conclude_request(
                    code=403,
                    message="You do not have permission to manage object access",
                    data={},
                )
                return 403, None, handler.username

            # Get the access entry
            entry = session.get(ObjectAccessEntry, entry_id)
            if not entry:
                handler.conclude_request(404, {}, "Access entry not found")
                return (
                    404,
                    None,
                    handler.data,
                    handler.username,
                )

            # Delete the entry
            session.delete(entry)
            session.commit()

        handler.conclude_request(200, {}, smsg.SUCCESS)
        return 200, None, handler.data, handler.username
