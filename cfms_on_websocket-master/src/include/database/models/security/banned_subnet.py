from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from include.database.handler import Base


class BannedSubnet(Base):
    """
    Represents a manually blocked IP subnet (CIDR notation).

    Administrators can add CIDR ranges here (e.g. '192.168.1.0/24' or
    '2001:db8::/32') to permanently block all addresses within that range
    at the LoginGuard level, independent of per-identifier lockout records.
    """

    __tablename__ = "banned_subnets"

    subnet: Mapped[str] = mapped_column(String(128), primary_key=True)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
