from include.constants import AVAILABLE_ACCESS_TYPES
from include.database.models.classic import User
from include.database.models.entity import (
    Document,
    DocumentAccessRule,
    Folder,
    FolderAccessRule,
)
from include.util.rule.validation import validate_access_rules


def set_access_rules(
    target: Document | Folder,
    new_access_rules: dict[str, list[dict]],
    inherit_parent: bool = True,
) -> None:
    """
    Core helper: attach access rules to a Document or Folder without performing
    any user-permission checks.  Only modifies the ORM object — does NOT commit.

    Raises:
        ValueError: if an access type is unrecognised or rule data is null.
        TypeError: if ``target`` is neither a Document nor a Folder.
    """
    if not new_access_rules:
        for rule in target.access_rules.copy():
            target.access_rules.remove(rule)  # pyright: ignore[reportArgumentType]
        target.inherit = inherit_parent
        return

    for access_type, this_type_rules in new_access_rules.items():
        if access_type not in AVAILABLE_ACCESS_TYPES:
            raise ValueError(f"Invalid access type: {access_type}")

        if this_type_rules is None:
            raise ValueError(
                f"Access rule data for access type {access_type} can't be null"
            )
        validate_access_rules(this_type_rules)

        for rule in target.access_rules.copy():
            if rule.access_type == access_type:
                target.access_rules.remove(rule)  # pyright: ignore[reportArgumentType]

        for each_rule in this_type_rules:
            if each_rule:
                if type(target) == Document:
                    this_new_rule = DocumentAccessRule(
                        document_id=target.id,
                        access_type=access_type,
                        rule_data=each_rule,
                    )
                elif type(target) == Folder:
                    this_new_rule = FolderAccessRule(
                        folder_id=target.id,
                        access_type=access_type,
                        rule_data=each_rule,
                    )
                else:
                    raise TypeError("Unsupported Object Type")
                target.access_rules.append(
                    this_new_rule  # pyright: ignore[reportArgumentType]
                )

    target.inherit = inherit_parent


def apply_access_rules(
    target: Document | Folder,
    new_access_rules: dict[str, list[dict]],
    user: User,
    inherit_parent: bool = True,
) -> bool:
    """
    Attach access rules and verify the acting user still satisfies each rule.
    Only modifies the ORM object — does NOT commit.

    Returns False if any resulting rule would deny access to ``user``.
    """
    set_access_rules(target, new_access_rules, inherit_parent)

    for access_type in new_access_rules:
        if not target.check_access_requirements(user, access_type):
            return False

    return True
