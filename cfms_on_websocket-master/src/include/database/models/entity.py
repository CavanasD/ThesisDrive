from typing import Iterable, List, Literal, Union, cast
from typing import Optional

import secrets
from sqlalchemy import VARCHAR, Boolean, Float, ForeignKey, Integer, func
from include.classes.enum.status import DocumentRevisionStatus, EntityStatus
from include.classes.exceptions import NoActiveRevisionsError
from include.conf_loader import global_config
from include.constants import AVAILABLE_ACCESS_TYPES, MAX_PARAM_SIZE, QUERY_CHUNK_SIZE
from include.database.handler import Base
from include.classes.access_rule import AccessRuleBase
from sqlalchemy.orm import Mapped, Session
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship
import time
from sqlalchemy.orm.session import object_session
from sqlalchemy import JSON
from itertools import batched

from include.database.models.file import (
    File,
    FileTask,
    _queue_deferred_file_deletion,
)
from include.database.models.classic import User
from include.util.fetch.fetch import batch_prefetch_granted_ids, prefetch_user_blocks


def _batch_count_other_revisions(
    session: Session,
    file_ids: Iterable[str],
    exclude_doc_ids: Union[str, Iterable[str]],
) -> dict[str, int]:
    """
    计算引用了指定 file_ids 的修订版本数量，但排除属于 exclude_doc_ids 集合的文档。

    参数:
        file_ids: 待检查的文件 ID 列表。
        exclude_doc_ids: 单个文档 ID 或文档 ID 集合。这些文档对文件的引用将不被计入。
    """
    counts: dict[str, int] = {}
    if not file_ids:
        return counts

    if isinstance(exclude_doc_ids, str):
        exclude_doc_ids = [exclude_doc_ids]
    else:
        exclude_doc_ids = list(exclude_doc_ids)

    EXCLUDE_CHUNK_SIZE = MAX_PARAM_SIZE - QUERY_CHUNK_SIZE

    for f_chunk in batched(file_ids, QUERY_CHUNK_SIZE):
        query = session.query(
            DocumentRevision.file_id, func.count(DocumentRevision.id)
        ).filter(DocumentRevision.file_id.in_(list(f_chunk)))

        for e_chunk in batched(exclude_doc_ids, EXCLUDE_CHUNK_SIZE):
            query = query.filter(DocumentRevision.document_id.not_in(list(e_chunk)))

        rows = query.group_by(DocumentRevision.file_id).all()
        counts.update({file_id: count for file_id, count in rows})

    for fid in file_ids:
        if fid not in counts:
            counts[fid] = 0

    return counts


def _batch_count_avatar_usages(session: Session, file_ids) -> dict:
    """Count User records using any of the given ``file_ids`` as their avatar.

    Queries are chunked to stay within SQLite's bind-variable limit.
    """
    counts: dict = {}
    if not file_ids:
        return counts
    for chunk in batched(file_ids, QUERY_CHUNK_SIZE):
        rows = (
            session.query(User.avatar_id, func.count())
            .filter(User.avatar_id.in_(list(chunk)))
            .group_by(User.avatar_id)
            .all()
        )
        counts.update({file_id: count for file_id, count in rows})
    return counts


class BaseObject(Base):
    __abstract__ = True

    id: Mapped[str]
    access_rules: Mapped[List]

    # Whether to inherit access rules from parent folders.
    # Useful when enabling recursion check.
    inherit: Mapped[bool]

    status: Mapped[EntityStatus] = mapped_column(
        Integer, nullable=False, default=EntityStatus.OK
    )
    status_operation_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), nullable=True, index=True
    )

    def check_access_requirements(
        self, user: User, access_type: str = "read", _no_recursive_check=False
    ) -> bool:
        """
        Checks if a given user meets the access requirements for a specific access type based on defined access rules.
        Args:
            user (User): The user object whose permissions and groups are to be checked.
            access_type (int, optional): The type of access to check for. Defaults to `"read"`.
            _no_recursive_check (bool, optional): Useful when performing batch queries. Defaults to False.
        Returns:
            bool: True if the user meets all access requirements for the specified access type, False otherwise.
        Raises:
            ValueError: If the "match" value in any rule is not "all" or "any".
        Access rules are evaluated as follows:
            - Each rule may specify required permissions ("rights") and/or groups ("groups").
            - Each requirement can specify a "match" mode: "all" (all required items must be present) or "any" (at least one must be present).
            - Rules are grouped and evaluated according to their match modes and requirements.
            - If no access rules are defined, access is granted by default.
        """

        _TARGET_TYPE_MAPPING = {"folders": "directory", "documents": "document"}

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
                for right in sub_rights_require:
                    if right in user.all_permissions:
                        return True
                return False

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
                for group in sub_groups_require:
                    if group in user.all_groups:
                        return True
                return False
            else:
                raise ValueError('the value of "match" must be "all" or "any"')

        def match_sub_group(sub_group):
            sub_match_mode = sub_group.get("match", "all")
            sub_rights_group = sub_group.get("rights", {})
            sub_groups_group = sub_group.get("groups", {})

            if not (sub_rights_group.get("require", [])) or (
                not sub_groups_group.get("require", [])
            ):
                sub_match_mode = "all"

            if sub_match_mode == "any":
                return match_rights(sub_rights_group) or match_groups(sub_groups_group)
            if sub_match_mode == "all":
                return match_rights(sub_rights_group) and match_groups(sub_groups_group)
            else:
                raise ValueError('the value of "match" must be "all" or "any"')

        def match_primary_sub_group(per_match_group):
            match_mode = per_match_group.get("match", "all")
            for sub_group in per_match_group["match_groups"]:
                if not sub_group:
                    continue

                state = match_sub_group(sub_group)

                if match_mode == "any":
                    if state:
                        return True
                elif match_mode == "all":
                    if not state:
                        return False

            if match_mode == "any":
                return False
            elif match_mode == "all":
                return True

        # Checks whether the user or the user group to which he belongs
        # has special access rights to this object.

        # Get `session` from `User` object
        _session = object_session(user)
        if not _session:
            raise RuntimeError("No active session found for user")

        now = time.time()

        # check user blocks first
        is_globally_blocked, blocked_ids = prefetch_user_blocks(
            _session, user, access_type, now
        )
        if is_globally_blocked or self.id in blocked_ids:
            return False

        # then check special access entries
        self_type = cast(
            Literal["document", "directory"], _TARGET_TYPE_MAPPING[self.__tablename__]
        )
        explicitly_granted_ids = batch_prefetch_granted_ids(
            _session, user, [self.id], self_type, access_type, now
        )

        if self.id in explicitly_granted_ids:
            return True

        if (
            global_config["access"]["enable_access_recursive_check"]
            and self.inherit
            and not _no_recursive_check
        ):
            # check all parent folders' access rules
            parent = None
            if type(self) == Document:
                parent = self.folder
            elif type(self) == Folder:
                parent = self.parent

            visited_folder_ids = set()
            while parent is not None:
                if parent.id in visited_folder_ids:
                    # Cycle detected; break to prevent an infinite loop
                    raise RuntimeError("Cycle detected in folder hierarchy")
                visited_folder_ids.add(parent.id)

                if not parent.check_access_requirements(user, access_type=access_type):
                    return False

                if not parent.inherit:
                    break  # if the parent folder does not inherit, stop checking further up

                parent = parent.parent

        if not self.access_rules:
            return True

        for each_rule in self.access_rules:
            if not each_rule:
                continue

            each_rule: AccessRuleBase

            # access_type 一览：
            # read - 读
            # write - 写（删除=清空数据，重命名=写文件元数据，因此都算写）
            # move - 移动
            # manage - 管理

            if access_type not in AVAILABLE_ACCESS_TYPES:
                raise ValueError(
                    f"Invaild access type for {self.__tablename__}: {access_type}"
                )

            match access_type:
                case "read":  # 如果要检查的是读权限
                    if each_rule.access_type != "read":
                        continue
                case "write":  # 如果要检查写权限
                    if each_rule.access_type not in ["read", "write"]:
                        continue
                case "move":
                    # 取消了对读权限的要求
                    if each_rule.access_type != "move":
                        continue
                case "manage":  # 如果要检查管理权限
                    if each_rule.access_type not in ["read", "manage"]:
                        continue
                case _:
                    raise NotImplementedError("Unsupported access type")

            if not each_rule.rule_data:
                continue

            if not match_primary_sub_group(each_rule.rule_data):
                return False

        return True


class Folder(BaseObject):  # 文档文件夹
    __tablename__ = "folders"
    id: Mapped[str] = mapped_column(
        VARCHAR(255), primary_key=True, default=lambda: secrets.token_hex(32)
    )
    name: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, index=True
    )  # 文件夹名称
    created_time: Mapped[float] = mapped_column(
        Float, nullable=False, default=lambda: time.time()
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), ForeignKey("folders.id", ondelete="CASCADE")
    )  # 父文件夹ID
    parent: Mapped[Optional["Folder"]] = relationship(
        "Folder", back_populates="children", remote_side=[id]
    )
    children: Mapped[List["Folder"]] = relationship(
        "Folder", back_populates="parent", cascade="all, delete-orphan"
    )
    access_rules: Mapped[List["FolderAccessRule"]] = relationship(
        "FolderAccessRule", back_populates="folder", cascade="all, delete-orphan"
    )
    documents: Mapped[List["Document"]] = relationship(
        "Document", back_populates="folder", cascade="all, delete-orphan"
    )
    inherit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def count_of_child(self):
        active_folders_count = sum(
            1 for f in self.children if f.status == EntityStatus.OK
        )
        active_docs_count = sum(
            1 for doc in self.documents if doc.status == EntityStatus.OK and doc.active
        )
        return active_folders_count + active_docs_count

    def is_descendant_of(self, potential_ancestor: "Folder") -> bool:
        """
        Check if this folder is a descendant of the given potential ancestor folder.

        Args:
            potential_ancestor: The folder to check if it's an ancestor

        Returns:
            True if this folder is a descendant of potential_ancestor, False otherwise
        """
        current = self.parent
        visited_ids = set()
        while current is not None:
            # Detect cycles in the parent chain to avoid infinite loops
            if current.id == potential_ancestor.id:
                return True
            if current.id in visited_ids:
                # Cycle detected; break to prevent an infinite loop
                break
            visited_ids.add(current.id)
            current = current.parent
        return False


class Document(BaseObject):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(
        VARCHAR(255), primary_key=True, default=lambda: secrets.token_hex(32)
    )
    title: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), nullable=False, default="Untitled Document", index=True
    )  # 文档名称
    created_time: Mapped[float] = mapped_column(
        Float, nullable=False, default=lambda: time.time()
    )
    folder_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True
    )  # 文档所属文件夹ID
    folder: Mapped[Optional["Folder"]] = relationship(
        "Folder", back_populates="documents"
    )

    # 每个文档有多个访问规则（AccessRule对象），以JSON格式存储规则数据
    access_rules: Mapped[List["DocumentAccessRule"]] = relationship(
        "DocumentAccessRule", back_populates="document", cascade="all, delete-orphan"
    )

    current_revision_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("document_revisions.id"), nullable=True
    )
    current_revision: Mapped[Optional["DocumentRevision"]] = relationship(
        "DocumentRevision",
        foreign_keys=[current_revision_id],
        post_update=True,
        uselist=False,
    )

    # 每个文档有多个修订版本
    revisions: Mapped[List["DocumentRevision"]] = relationship(
        "DocumentRevision",
        back_populates="document",
        foreign_keys="[DocumentRevision.document_id]",
        order_by="DocumentRevision.created_time",
        cascade="all, delete-orphan",
        overlaps="current_revision",  # 声明与 current_revision 的重叠
    )
    inherit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @property
    def active(self):
        try:
            self.get_latest_revision()
        except (RuntimeError, NoActiveRevisionsError):
            return False
        return True

    def get_latest_revision(self) -> "DocumentRevision":
        """
        获取最新的活跃修订版本。

        该函数的逻辑如下：

        - 如果 current_revision 不为空，则从指定的 current_revision 开始，寻找从修订版本树末端上溯遇到的第一个活跃修订版本。
        - 如果 current_revision 为空（这一般仅在从过去的版本升级时发生），则将全体修订版本按`created_time`降序排列，返回第一个`revision.active`为`True`的修订版本。
        """
        if not self.revisions:
            raise RuntimeError("A document cannot have no revisions.")

        if self.current_revision:
            if self.current_revision.active:
                return self.current_revision

            # find active revisions
            latest_revision = self.current_revision.parent_revision
            while latest_revision is not None:
                if latest_revision.active:
                    return latest_revision
                latest_revision = latest_revision.parent_revision

            # if goes here, use backward compatibility method

        # for backward compatibility

        # 过滤出active为True的修订版本
        active_revisions = [rev for rev in self.revisions if rev.active]

        if not active_revisions:
            raise NoActiveRevisionsError("No active revisions found.")

        return max(active_revisions, key=lambda rev: rev.created_time)

    def delete_all_revisions(self, do_commit: bool = True):
        session = object_session(self)
        if not session:
            raise Exception("The object is not associated with a session")

        # Task 4: Lightweight tuple query — fetch only the IDs we need for logic.
        # Avoids loading the full ORM graph (revisions + files) just for reference counting.
        revision_tuples = (
            session.query(DocumentRevision.id, DocumentRevision.file_id)
            .filter(DocumentRevision.document_id == self.id)
            .all()
        )
        if not revision_tuples:
            return

        revision_ids = [row[0] for row in revision_tuples]
        all_file_ids = {row[1] for row in revision_tuples if row[1]}

        # Task 3: Chunked batch reference count queries to avoid variable limit.
        other_rev_counts = _batch_count_other_revisions(session, all_file_ids, self.id)
        avatar_counts = _batch_count_avatar_usages(session, all_file_ids)

        # Determine which files are exclusively referenced by this document's revisions.
        deletable_file_ids = {
            fid
            for fid in all_file_ids
            if other_rev_counts.get(fid, 0) + avatar_counts.get(fid, 0) == 0
        }

        # Load File ORM objects needed for deletion (chunked to stay within SQLite limits).
        # Task 4: Only loads files that are actually going to be deleted.
        files_to_delete: list = []
        if deletable_file_ids:
            for chunk in batched(deletable_file_ids, QUERY_CHUNK_SIZE):
                files_to_delete.extend(
                    session.query(File).filter(File.id.in_(list(chunk))).all()
                )

        self.current_revision_id = None
        self.current_revision = None

        with session.no_autoflush:
            # Task 2: Batch delete all FileTask rows for deletable files in one query per chunk.
            # Replaces N individual DELETE queries (one per file) with one per chunk.
            if deletable_file_ids:
                for chunk in batched(deletable_file_ids, QUERY_CHUNK_SIZE):
                    session.query(FileTask).filter(
                        FileTask.file_id.in_(list(chunk))
                    ).delete(synchronize_session=False)

            # Load DocumentRevision ORM objects for deletion (chunked).
            revisions: list = []
            for chunk in batched(revision_ids, QUERY_CHUNK_SIZE):
                revisions.extend(
                    session.query(DocumentRevision)
                    .filter(DocumentRevision.id.in_(list(chunk)))
                    .all()
                )

            # ORM-level delete so SQLAlchemy handles FK ordering correctly at flush time.
            for revision in revisions:
                session.delete(revision)
            for file_obj in files_to_delete:
                session.delete(file_obj)

        # Task 1: Queue physical file paths for deferred deletion.
        # Files are removed from disk ONLY after session.commit() succeeds.
        # If the transaction rolls back, the queued paths are discarded automatically.
        for file_obj in files_to_delete:
            _queue_deferred_file_deletion(session, file_obj.path)

        self.revisions = []
        if do_commit:
            session.commit()

    def __repr__(self) -> str:
        return f"Document(id={self.id!r}, created_time={self.created_time!r})"


class DocumentRevision(Base):
    """
    This class implemented a model for document revisions.

    A document revision is a historical version of the document,
    should only be written once and not changed.
    """

    __tablename__ = "document_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(
        VARCHAR(255), ForeignKey("documents.id"), nullable=False
    )
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id"))
    created_time: Mapped[float] = mapped_column(
        Float, nullable=False, default=lambda: time.time()
    )

    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="revisions",
        foreign_keys=[document_id],
        overlaps="current_revision",  # 声明重叠
    )
    file: Mapped["File"] = relationship(
        "File", primaryjoin="DocumentRevision.file_id == File.id"
    )

    parent_revision_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("document_revisions.id"), nullable=True
    )
    parent_revision: Mapped[Optional["DocumentRevision"]] = relationship(
        "DocumentRevision",
        remote_side=[id],
        back_populates="child_revisions",
    )

    child_revisions: Mapped[List["DocumentRevision"]] = relationship(
        "DocumentRevision",
        back_populates="parent_revision",
        foreign_keys="[DocumentRevision.parent_revision_id]",
    )

    status: Mapped[DocumentRevisionStatus] = mapped_column(
        Integer, nullable=False, default=DocumentRevisionStatus.OK
    )

    @property
    def active(self):
        return self.file.active

    @property
    def writeable(self):
        return self.file.writeable

    def before_delete(self):
        session = object_session(self)
        if not session:
            raise Exception("The object is not associated with a session")

        other_refs = (
            session.query(DocumentRevision)
            .filter(DocumentRevision.file_id == self.file_id)
            .filter(DocumentRevision.id != self.id)
            .count()
            +
            # Check if file is not used as any avatar property
            session.query(User).filter(User.avatar_id == self.file_id).count()
        )

        if other_refs == 0:
            try:
                self.file.delete()
            except PermissionError:
                raise
            session.delete(self.file)

    def __repr__(self) -> str:
        return (
            f"DocumentRevision(id={self.id!r}, document_id={self.document_id!r}, "
            f"file={self.file!r}, created_time={self.created_time!r})"
        )


class DocumentAccessRule(Base, AccessRuleBase):
    __tablename__ = "document_access_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    access_type: Mapped[str] = mapped_column(
        VARCHAR(64),
        nullable=False,
        default="read",
        # comment="0: read, 1: write",  # rename is regarded as write
    )
    document_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("documents.id"), nullable=False
    )
    rule_data: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )  # 存储单个Json格式的规则数据

    document: Mapped[Optional["Document"]] = relationship(
        "Document", back_populates="access_rules"
    )

    def __repr__(self) -> str:
        return f"DocumentAccessRule(id={self.id!r}, document_id={self.document_id!r}, rule_data={self.rule_data!r})"


class FolderAccessRule(Base, AccessRuleBase):
    __tablename__ = "folder_access_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    access_type: Mapped[str] = mapped_column(
        VARCHAR(64),
        nullable=False,
        default="read",
    )
    folder_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("folders.id"), nullable=True
    )
    rule_data: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )  # 存储单个Json格式的规则数据

    folder: Mapped[Optional["Folder"]] = relationship(
        "Folder", back_populates="access_rules"
    )

    def __repr__(self) -> str:
        return f"FolderAccessRule(id={self.id!r}, folder_id={self.folder_id!r}, rule_data={self.rule_data!r})"
