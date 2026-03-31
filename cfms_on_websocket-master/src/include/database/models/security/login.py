from typing import Optional

from sqlalchemy import Column, String, Integer, DateTime, func
from datetime import datetime, timedelta

from sqlalchemy.orm import Mapped, mapped_column
from include.database.handler import Base


class LoginSecurity(Base):
    __tablename__ = "login_security"

    identifier: Mapped[str] = mapped_column(String(128), primary_key=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def is_locked(self) -> bool:
        if self.locked_until is not None:
            return self.locked_until > datetime.now()
        return False
