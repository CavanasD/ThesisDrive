__all__ = ["AccessRuleBase"]

from sqlalchemy.orm import Mapped


class AccessRuleBase:
    id: Mapped[int]
    access_type: Mapped[str]
    rule_data: Mapped[dict]
