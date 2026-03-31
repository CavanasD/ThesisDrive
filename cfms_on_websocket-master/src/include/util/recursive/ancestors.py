__all__ = [
    "search_documents_with_access",
    "search_folders_with_access",
]

from collections import defaultdict
from typing import Optional
import time

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text

from include.database.models.entity import Document, Folder
from include.database.models.classic import ObjectAccessEntry


# ── 内部辅助：给定起始 folder_id 集合和需要查OAE的目标ID集合，
#    批量展开祖先链、预加载权限数据 ──────────────────────────────────────────
def _fetch_ancestors_and_oae(
    session: Session,
    seed_folder_ids: list[str],  # CTE 递归的起点文件夹 ID 集合
    extra_target_ids: list[str],  # 除文件夹外还需要查 OAE 的其他目标ID（如文档ID）
    exclude_folder_ids: set[
        str
    ],  # 已经加载过的文件夹ID，不需要重复查（如命中的文件夹自身）
    now: float,
) -> tuple[list[Folder], dict]:
    """
    公共内部函数：
    1. 用递归 CTE 从 seed_folder_ids 出发，展开所有祖先文件夹
    2. 批量加载这些文件夹（含 access_rules 预加载），排除 exclude_folder_ids
    3. 批量拉取 extra_target_ids + 所有祖先文件夹 的 ObjectAccessEntry

    返回：
        ancestor_folders - 祖先文件夹列表（已排除 exclude_folder_ids）
        oae_by_target    - Dict[target_id, List[ObjectAccessEntry]]
    """
    if not seed_folder_ids:
        # 没有任何祖先需要查（比如所有文档都在根目录）
        all_target_ids = extra_target_ids
        ancestor_folders = []
    else:
        # Step A：递归 CTE 展开所有祖先 ID（自动去重）
        placeholders = ", ".join(f":fid_{i}" for i in range(len(seed_folder_ids)))
        params = {f"fid_{i}": fid for i, fid in enumerate(seed_folder_ids)}

        ancestor_sql = text(
            f"""
            WITH RECURSIVE anc(id, parent_id, inherit) AS (
                SELECT id, parent_id, inherit
                FROM folders
                WHERE id IN ({placeholders})

                UNION

                SELECT f.id, f.parent_id, f.inherit
                FROM folders f
                INNER JOIN anc ON f.id = anc.parent_id
            )
            SELECT DISTINCT id FROM anc
        """
        )

        all_ancestor_ids = [
            row[0] for row in session.execute(ancestor_sql, params).fetchall()
        ]

        # Step B：排除已加载的，批量加载祖先 Folder（含 access_rules）
        pure_ancestor_ids = [
            fid for fid in all_ancestor_ids if fid not in exclude_folder_ids
        ]

        ancestor_folders = (
            (
                session.query(Folder)
                .options(joinedload(Folder.access_rules))
                .filter(Folder.id.in_(pure_ancestor_ids))
                .all()
            )
            if pure_ancestor_ids
            else []
        )

        all_target_ids = extra_target_ids + all_ancestor_ids

    # Step C：批量拉取 OAE（文档 + 所有文件夹，一次查询）
    oae_by_target: dict = defaultdict(list)
    if all_target_ids:
        oae_entries = (
            session.query(ObjectAccessEntry)
            .filter(
                ObjectAccessEntry.target_identifier.in_(all_target_ids),
                ObjectAccessEntry.start_time <= now,
                (ObjectAccessEntry.end_time == None)
                | (ObjectAccessEntry.end_time >= now),
            )
            .all()
        )
        for entry in oae_entries:
            oae_by_target[entry.target_identifier].append(entry)

    return ancestor_folders, oae_by_target


# ── 搜索文档 ────────────────────────────────────────────────────────────────
def search_documents_with_access(
    session: Session,
    keyword: str,
    now: Optional[float] = None,
) -> tuple[list[Document], list[Folder], dict]:
    """
    按关键词搜索文档标题，批量预取祖先链权限信息。

    返回：
        documents     - 命中的文档列表（access_rules 已预加载）
        folders       - 所有祖先文件夹列表（access_rules 已预加载）
        oae_by_target - Dict[target_id, List[ObjectAccessEntry]]
    """
    if now is None:
        now = time.time()

    # Step 1：搜索文档
    documents = (
        session.query(Document)
        .options(joinedload(Document.access_rules))
        .filter(Document.title.ilike(f"%{keyword}%"))
        .all()
    )
    if not documents:
        return [], [], {}

    # Step 2：收集起点 folder_id（文档的直接父文件夹，去重）
    seed_folder_ids = list(
        {doc.folder_id for doc in documents if doc.folder_id is not None}
    )

    # Step 3-5：交给公共函数处理
    ancestor_folders, oae_by_target = _fetch_ancestors_and_oae(
        session=session,
        seed_folder_ids=seed_folder_ids,
        extra_target_ids=[doc.id for doc in documents],  # 文档本身也需要查 OAE
        exclude_folder_ids=set(),  # 文档搜索时没有预加载过任何文件夹
        now=now,
    )

    return documents, ancestor_folders, oae_by_target


# ── 搜索文件夹 ──────────────────────────────────────────────────────────────
def search_folders_with_access(
    session: Session,
    keyword: str,
    now: Optional[float] = None,
) -> tuple[list[Folder], list[Folder], dict]:
    """
    按关键词搜索文件夹名称，批量预取祖先链权限信息。

    返回：
        matched_folders  - 命中的文件夹列表（access_rules 已预加载）
        ancestor_folders - 所有祖先文件夹列表（access_rules 已预加载，不含命中的）
        oae_by_target    - Dict[target_id, List[ObjectAccessEntry]]
    """
    if now is None:
        now = time.time()

    # Step 1：搜索文件夹
    matched_folders = (
        session.query(Folder)
        .options(joinedload(Folder.access_rules))
        .filter(Folder.name.ilike(f"%{keyword}%"))
        .all()
    )
    if not matched_folders:
        return [], [], {}

    # Step 2：收集起点 parent_id（命中文件夹的直接父级，去重）
    #         注意：命中的文件夹本身已加载，起点从它们的 parent_id 开始向上
    seed_folder_ids = list(
        {f.parent_id for f in matched_folders if f.parent_id is not None}
    )

    matched_ids = {f.id for f in matched_folders}

    # Step 3-5：交给公共函数处理
    #           exclude_folder_ids=matched_ids 避免重复加载命中的文件夹
    ancestor_folders, oae_by_target = _fetch_ancestors_and_oae(
        session=session,
        seed_folder_ids=seed_folder_ids,
        extra_target_ids=[f.id for f in matched_folders],  # 命中文件夹本身也需要查 OAE
        exclude_folder_ids=matched_ids,
        now=now,
    )

    return matched_folders, ancestor_folders, oae_by_target
