import secrets
import time
from typing import TYPE_CHECKING, Optional

from sqlalchemy import VARCHAR, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from include.database.handler import Base

if TYPE_CHECKING:
    from include.database.models.classic import User


class UserKey(Base):
    """
    Stores user-owned encryption keys (DEKs) for client configuration encryption
    and multi-device synchronization.

    Each key entry is bound to a specific user. Users can designate one key as
    their *preference* key; that key is returned in the login response so any
    conforming client can transparently retrieve the configuration-encryption DEK
    without having to know or guess a key identifier.
    """

    __tablename__ = "keyrings"

    id: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, default=lambda: secrets.token_hex(32)
    )
    username: Mapped[str] = mapped_column(
        ForeignKey("users.username", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # label is reserved for future use and is currently optional.
    label: Mapped[Optional[str]] = mapped_column(VARCHAR(255), nullable=True)
    created_time: Mapped[float] = mapped_column(
        Float, nullable=False, default=time.time
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="keyring",
        overlaps="preference_dek",
        foreign_keys=[username],
    )

    def __repr__(self) -> str:
        return (
            f"UserKey(id={self.id!r}, username={self.username!r}, "
            f"label={self.label!r})"
        )
