import os
import secrets
import sys
import time
from typing import List
from typing import Optional

from sqlalchemy import VARCHAR, Float, ForeignKey, Integer, Text, Boolean, event
from sqlalchemy.orm import Mapped, Session
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import object_session

from include.database.handler import Base
from include.util.log import getCustomLogger

logger = getCustomLogger(__name__, filepath="./content/logs/file.log")


def _queue_deferred_file_deletion(session: Session, path: str) -> None:
    """Queue a file path for physical deletion after the session's next successful commit.

    This ensures filesystem changes only happen after the DB transaction is committed,
    preventing orphaned DB records if ``os.remove`` raises, and preventing deleted files
    when the DB transaction rolls back.

    On rollback the queue is cleared so no files are ever removed.
    """
    pending: list = session.info.setdefault("pending_delete_files", [])
    pending.append(path)

    # Register lifecycle hooks only once per session instance to avoid duplicate callbacks.
    if not session.info.get("_deferred_delete_hooks_registered"):
        session.info["_deferred_delete_hooks_registered"] = True

        @event.listens_for(session, "after_commit")
        def _do_deferred_file_deletes(session: Session):
            paths = session.info.pop("pending_delete_files", [])
            for path in paths:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass  # already removed manually — this is fine
                except OSError as exc:
                    # e.g. PermissionError on a locked file post-commit; the DB record
                    # has already been deleted so the file becomes an orphan.  Log the
                    # error so operators can clean up manually.
                    logger.warning(
                        "Failed to remove file after commit (orphaned file): %s — %s",
                        path, exc,
                    )

        @event.listens_for(session, "after_rollback")
        def _clear_deferred_file_deletes(session: Session):
            # Discard queued paths so they are never removed on a failed transaction.
            session.info.pop("pending_delete_files", None)


class File(Base):
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(
        VARCHAR(255), primary_key=True, default=lambda: secrets.token_hex(32)
    )

    sha256: Mapped[str] = mapped_column(VARCHAR(64), nullable=True)
    # calculate sha256 takes time, especially for large files lol
    #
    # there are also a lot of situations where sha256 in the database is null
    # or mismatch, so don't use it as a must

    path: Mapped[str] = mapped_column(Text, nullable=False)
    created_time: Mapped[float] = mapped_column(
        Float, nullable=False, default=lambda: time.time()
    )
    tasks: Mapped[List["FileTask"]] = relationship(
        "FileTask", back_populates="file", cascade="all, delete-orphan"
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    @property
    def size(self):
        if os.path.exists(self.path):
            return os.path.getsize(self.path)
        else:
            return None

    @property
    def writeable(self):
        if sys.platform == "win32":
            import win32file, pywintypes

            hFile = None
            try:
                if os.path.exists(self.path):
                    hFile = win32file.CreateFile(
                        self.path,
                        win32file.GENERIC_READ + win32file.GENERIC_WRITE,
                        win32file.FILE_SHARE_READ,
                        None,
                        win32file.OPEN_ALWAYS,  # win32file.OPEN_EXISTING,
                        0,
                        None,
                    )
            except pywintypes.error:
                return False
            finally:
                if hFile:
                    hFile.Close()

        # elif sys.platform == "linux":
        #     import fcntl
        #     try:
        #         with open(self.path, 'a') as f:
        #             fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        #     except IOError:
        #         return False

        # unsafe: for unknown platforms, won't check if the file is locked
        return True  # os.path.exists(self.path) and os.path.getsize(self.path) > 0

    def delete(self):
        """Remove this file from disk and clean up its associated FileTask records.

        When called within a DB session the physical ``os.remove`` is deferred until
        after the session commits successfully (via ``_queue_deferred_file_deletion``),
        so a DB rollback never leaves the filesystem in an inconsistent state.

        For bulk deletions prefer batching the FileTask cleanup upstream (using
        ``FileTask.file_id.in_(chunk)`` across all files at once) and calling
        ``_queue_deferred_file_deletion`` directly — this method is intended for
        single-file standalone use.
        """
        session = object_session(self)
        if session is not None:
            # Remove associated task records as part of the DB transaction.
            session.query(FileTask).filter(FileTask.file_id == self.id).delete(
                synchronize_session=False
            )  # be careful
            # Defer physical file removal until after a successful commit.
            _queue_deferred_file_deletion(session, self.path)
        else:
            # No session context — perform immediate deletion.
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass

    def get_latest_task(self):
        """
        返回最后一个尚未结束（也包括尚未开始）的任务，按起始时间排序。
        """

        now = time.time()
        active_tasks = [
            task
            for task in self.tasks
            if (task.end_time and now < task.end_time) or not task.end_time
        ]

        return (
            max(active_tasks, key=lambda task: task.start_time)
            if active_tasks
            else None
        )

    def __repr__(self) -> str:
        return f"File(id={self.id!r}, file_path={self.path!r}, created_time={self.created_time!r})"


class FileTask(Base):
    __tablename__ = "file_tasks"
    id: Mapped[str] = mapped_column(
        VARCHAR(255), primary_key=True, default=lambda: secrets.token_hex(32)
    )
    file_id: Mapped[str] = mapped_column(
        VARCHAR(255), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    # 0: 等待中, 1: 已完成, 2: 已取消
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mode: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="0: download, 1: upload"
    )
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # encryption_mode: Mapped[Optional[str]] = mapped_column(
    #     VARCHAR(32), nullable=True, default=None
    # )  # 加密模式，如 'AES', 'RSA'，未加密则为 None

    file: Mapped["File"] = relationship("File", back_populates="tasks")

    def __repr__(self) -> str:
        return (
            f"FileTask(id={self.id!r}, "
            f"file_id={self.file_id!r}, status={self.status!r})"
        )
