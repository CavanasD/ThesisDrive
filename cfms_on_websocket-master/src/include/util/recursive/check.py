from enum import IntEnum
from include.database.models.entity import Document, Folder
from include.database.models.classic import User, ObjectAccessEntry
from include.classes.access_rule import AccessRuleBase
from include.constants import AVAILABLE_ACCESS_TYPES


class SingleNodeCheckResult(IntEnum):
    ALLOWED_OAE = 2
    ALLOWED = 1
    DENIED = 0


def check_access_for_object(
    obj: Document | Folder,
    user: User,
    access_type: str,
    all_folders: list[Folder],
    oae_by_target: dict,
    recursive: bool = True,
) -> bool:

    if access_type not in AVAILABLE_ACCESS_TYPES:
        raise ValueError(f"Invalid access type: {access_type}")

    folder_map = {f.id: f for f in all_folders}

    def _check_single_node(node: Document | Folder) -> SingleNodeCheckResult:
        """
        Check if the current user has the specified access type to a single node (document or folder).
        This function performs a three-step access control check:
        1. **Object Access Entry (OAE) Check**: Evaluates special authorization rules with highest priority.
           - First checks if the user has a direct OAE matching the target node, access type, and entity type.
           - Then checks if any of the user's groups have a matching OAE.
           - Returns True immediately if a matching OAE is found.
        2. **Default Allow Rule**: If no access rules are defined on the node, access is granted by default.
        3. **Access Rules Validation**: Iterates through all access rules defined on the node.
           - Filters rules based on the requested access_type (read, write, move, manage).
           - Checks if the user matches the primary and sub-group requirements of each rule.
           - Returns False if any rule fails the matching check.
        Args:
            node: A Document or Folder object to check access permissions for.
        Returns:
            bool: True if the user has the specified access type to the node, False otherwise.
        Raises:
            NotImplementedError: If an unsupported access_type is encountered.
        Note:
            This function relies on external context: `user`, `access_type`, `oae_by_target`,
            and the helper function `_match_primary_sub_group`.
        """

        _TARGET_TYPE_MAPPING = {"folders": "directory", "documents": "document"}
        target_type = _TARGET_TYPE_MAPPING[node.__tablename__]

        # check OAE first (highest priority)
        entries: list[ObjectAccessEntry] = oae_by_target.get(node.id, [])

        # check user's direct OAE
        for entry in entries:
            if (
                entry.entity_type == "user"
                and entry.entity_identifier == user.username
                and entry.target_type == target_type
                and entry.access_type == access_type
            ):
                return SingleNodeCheckResult.ALLOWED_OAE

        # check user's group OAE
        user_groups = user.all_groups  # set[str]
        for entry in entries:
            if (
                entry.entity_type == "group"
                and entry.entity_identifier in user_groups
                and entry.target_type == target_type
                and entry.access_type == access_type
            ):
                return SingleNodeCheckResult.ALLOWED_OAE

        # If there are no access rules defined on the node, allow access by default
        if not node.access_rules:
            return SingleNodeCheckResult.ALLOWED

        # check access rules
        for rule in node.access_rules:
            rule: AccessRuleBase
            if not rule.rule_data:
                continue

            # filter by access_type
            match access_type:
                case "read":
                    if rule.access_type != "read":
                        continue
                case "write":
                    if rule.access_type not in ["read", "write"]:
                        continue
                case "move":
                    if rule.access_type != "move":
                        continue
                case "manage":
                    if rule.access_type not in ["read", "manage"]:
                        continue
                case _:
                    raise NotImplementedError(f"Unsupported access type: {access_type}")

            if not _match_primary_sub_group(rule.rule_data, user):
                return SingleNodeCheckResult.DENIED

        return SingleNodeCheckResult.ALLOWED

    # check the object itself first
    match _check_single_node(obj):
        case SingleNodeCheckResult.ALLOWED_OAE:
            return True  # OAE grants access immediately, no need to check further
        case SingleNodeCheckResult.ALLOWED:
            pass  # continue to check parent folders if necessary
        case SingleNodeCheckResult.DENIED:
            return False  # explicit denial, no need to check further
        case _:
            raise RuntimeError("Unexpected SingleNodeCheckResult value")
        
    # if not recursive or the object does not inherit permissions, stop here
    if not recursive or not obj.inherit:
        return True

    if isinstance(obj, Document):
        current_folder_id = obj.folder_id
    else:  # Folder
        current_folder_id = obj.parent_id

    visited_ids = set()  # prevent potential cycles in folder hierarchy

    while current_folder_id is not None:
        if current_folder_id in visited_ids:
            raise RuntimeError("Cycle detected in folder hierarchy")
        visited_ids.add(current_folder_id)

        current_folder = folder_map.get(current_folder_id)
        if current_folder is None:
            # This should not happen if the folder hierarchy is consistent,
            # but we handle it gracefully just in case
            break

        # check access for the current folder node
        if not _check_single_node(current_folder):
            return False

        # If the current folder does not inherit permissions, stop checking
        # further up the hierarchy
        if not current_folder.inherit:
            break

        current_folder_id = current_folder.parent_id

    return True


def _match_primary_sub_group(rule_data: dict, user: User) -> bool:
    def match_rights(sub_rights_group):
        if not sub_rights_group:
            return True
        sub_match_mode = sub_rights_group.get("match", "all")
        sub_rights_require = sub_rights_group.get("require", [])
        if not sub_rights_require:
            return True
        if sub_match_mode == "all":
            return set(sub_rights_require).issubset(user.all_permissions)
        elif sub_match_mode == "any":
            return any(r in user.all_permissions for r in sub_rights_require)
        else:
            raise ValueError('the value of "match" must be "all" or "any"')

    def match_groups(sub_groups_group):
        if not sub_groups_group:
            return True
        sub_match_mode = sub_groups_group.get("match", "all")
        sub_groups_require = sub_groups_group.get("require", [])
        if not sub_groups_require:
            return True
        if sub_match_mode == "all":
            return set(sub_groups_require).issubset(user.all_groups)
        elif sub_match_mode == "any":
            return any(g in user.all_groups for g in sub_groups_require)
        else:
            raise ValueError('the value of "match" must be "all" or "any"')

    def match_sub_group(sub_group):
        sub_match_mode = sub_group.get("match", "all")
        sub_rights_group = sub_group.get("rights", {})
        sub_groups_group = sub_group.get("groups", {})
        if not sub_rights_group.get("require", []) or not sub_groups_group.get(
            "require", []
        ):
            sub_match_mode = "all"
        if sub_match_mode == "any":
            return match_rights(sub_rights_group) or match_groups(sub_groups_group)
        if sub_match_mode == "all":
            return match_rights(sub_rights_group) and match_groups(sub_groups_group)
        else:
            raise ValueError('the value of "match" must be "all" or "any"')

    match_mode = rule_data.get("match", "all")
    for sub_group in rule_data.get("match_groups", []):
        if not sub_group:
            continue
        state = match_sub_group(sub_group)
        if match_mode == "any" and state:
            return True
        if match_mode == "all" and not state:
            return False

    return match_mode == "all"
