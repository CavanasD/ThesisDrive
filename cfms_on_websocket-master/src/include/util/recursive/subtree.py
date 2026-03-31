from collections import defaultdict
from collections import deque
from typing import Optional
from itertools import batched
import time

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text

from include.classes.enum.status import EntityStatus
from include.constants import QUERY_CHUNK_SIZE
from include.database.models.entity import Document, Folder, DocumentRevision
from include.database.models.classic import User, ObjectAccessEntry
from include.util.fetch.fetch import prefetch_user_blocks
from include.util.recursive.check import check_access_for_object


def fetch_subtree_for_deletion(
    session: Session,
    root_folder_id: str,
    user: User,
    now: Optional[float] = None,
    include_deleted: bool = False,
) -> tuple[
    list[str],  # deletable_folder_ids: ordered
    set[str],  # deletable_doc_ids
    list[dict],  # failed_items
    set[str],  # protected_folder_ids
    dict[str, Folder],  # folder_map
]:
    """
    一次性分析 root_folder_id 下整棵子树的可删性。

    返回：
        deletable_folder_ids  - 可以被删除的目录 ID 集合（自身有权删 且 无不可删后代）
        deletable_doc_ids     - 可以被删除的文档 ID 集合
        failed_items          - 鉴权失败的条目列表，用于返回给客户端
        protected_folder_ids  - 因包含不可删后代而必须保留的目录 ID 集合
        folder_map            - 目录 ID 到 Folder ORM 对象的映射
    """
    if now is None:
        now = time.time()

    # ── Step 1: 用递归 CTE 捞出整棵子树的所有文件夹 ID ─────────────────────
    exec_opts = {"include_deleted": True} if include_deleted else {}
    status_filter = "" if include_deleted else f"AND f.status = {EntityStatus.OK.value}"

    subtree_sql = text(
        f"""
        WITH RECURSIVE subtree(id, parent_id, status) AS (
            SELECT id, parent_id, status
            FROM folders
            WHERE id = :root_id

            UNION ALL

            SELECT f.id, f.parent_id, f.status
            FROM folders f
            INNER JOIN subtree s ON f.parent_id = s.id
            WHERE 1=1 {status_filter}
        )
        SELECT id FROM subtree WHERE id != :root_id
        """
    )
    # 注意：root_id 本身的可删性由调用方（handler）已检查，这里只分析"内容"
    # 如果需要连 root 本身也纳入分析，去掉 WHERE id != :root_id 即可

    all_subfolder_ids = [
        row[0]
        for row in session.execute(subtree_sql, {"root_id": root_folder_id}).fetchall()
    ]

    # 将 root 本身也纳入需要加载的范围（用于后续 BFS 推导）
    all_folder_ids_to_load = list(set(all_subfolder_ids + [root_folder_id]))

    # ── Step 2: 批量加载所有文件夹（含 access_rules）────────────────────────
    # Chunked to avoid SQLite bind-variable limit for large subtrees.
    folders: list[Folder] = []
    for chunk in batched(all_folder_ids_to_load, QUERY_CHUNK_SIZE):
        folders.extend(
            session.query(Folder)
            .options(joinedload(Folder.access_rules))
            .execution_options(**exec_opts)
            .filter(Folder.id.in_(list(chunk)))
            .all()
        )
    folder_map: dict[str, Folder] = {f.id: f for f in folders}
    actual_folder_ids = list(folder_map.keys())

    # ── Step 3: 批量加载子树内所有文档（含 access_rules、revisions、files）──────────────────
    # Chunked to avoid SQLite bind-variable limit for large subtrees.
    documents: list[Document] = []
    for chunk in batched(actual_folder_ids, QUERY_CHUNK_SIZE):
        documents.extend(
            session.query(Document)
            .options(
                joinedload(Document.access_rules),
                joinedload(Document.current_revision).joinedload(DocumentRevision.file),
            )
            .execution_options(**exec_opts)
            .filter(Document.folder_id.in_(list(chunk)))
            .all()
        )

    # ── Step 4: 批量预取 OAE ────────────────────────────────────────────────
    # Chunked to avoid bind-variable limit for large subtrees.
    all_target_ids = actual_folder_ids + [doc.id for doc in documents]
    oae_entries: list[ObjectAccessEntry] = []
    for chunk in batched(all_target_ids, QUERY_CHUNK_SIZE):
        oae_entries.extend(
            session.query(ObjectAccessEntry)
            .execution_options(**exec_opts)
            .filter(
                ObjectAccessEntry.target_identifier.in_(list(chunk)),
                ObjectAccessEntry.start_time <= now,
                (ObjectAccessEntry.end_time == None)
                | (ObjectAccessEntry.end_time >= now),
            )
            .all()
        )
    oae_by_target: dict = defaultdict(list)
    for entry in oae_entries:
        oae_by_target[entry.target_identifier].append(entry)

    # ── Step 5: 预取用户 block 状态（一次性，避免后续重复查询）──────────────
    is_globally_blocked, blocked_write_ids = prefetch_user_blocks(
        session, user, "write", now
    )

    # ── Step 6: 对每个文档鉴权 ──────────────────────────────────────────────
    # check_access_for_object 接收预加载好的 all_folders 和 oae_by_target，不产生额外 SQL
    deletable_doc_ids: set[str] = set()
    failed_items: list[dict] = []

    has_delete_document_perm = "delete_document" in user.all_permissions

    for doc in documents:
        if not include_deleted and doc.status != EntityStatus.OK:
            continue

        can_delete = (
            not is_globally_blocked
            and doc.id not in blocked_write_ids
            and has_delete_document_perm
            and check_access_for_object(
                doc,
                user,
                "write",
                all_folders=folders,
                oae_by_target=oae_by_target,
            )
        )

        if can_delete:
            deletable_doc_ids.add(doc.id)
        else:
            assert doc.folder_id is not None
            if check_access_for_object(
                folder_map[doc.folder_id],
                user,
                "read",
                all_folders=folders,
                oae_by_target=oae_by_target,
            ):
                failed_items.append(
                    {
                        "type": "document",
                        "id": doc.id,
                        "title": doc.title,
                        "parent_folder_id": doc.folder_id,
                        "reason": "permission_denied",
                    }
                )

    # ── Step 7: 对每个子文件夹自身鉴权 ─────────────────────────────────────
    has_delete_directory_perm = "delete_directory" in user.all_permissions

    # folder_self_deletable: 仅考虑自身权限，暂不考虑后代
    folder_self_deletable: dict[str, bool] = {}

    for folder in folders:
        if folder.id == root_folder_id:
            # root 本身由 handler 层已鉴权，假设可删
            folder_self_deletable[folder.id] = True
            continue

        can_delete = (
            not is_globally_blocked
            and folder.id not in blocked_write_ids
            and has_delete_directory_perm
            and check_access_for_object(
                folder,
                user,
                "write",
                all_folders=folders,
                oae_by_target=oae_by_target,
            )
        )
        folder_self_deletable[folder.id] = can_delete
        if not can_delete:
            assert (
                folder.parent_id is not None
            ), "Root folder should have been handled separately"
            if check_access_for_object(
                folder_map[folder.parent_id],
                user,
                "read",
                all_folders=folders,
                oae_by_target=oae_by_target,
            ):
                failed_items.append(
                    {
                        "type": "folder",
                        "id": folder.id,
                        "name": folder.name,
                        "parent_folder_id": folder.parent_id,
                        "reason": "permission_denied",
                    }
                )

    # ── Step 8: 自底向上推导"因包含不可删后代而必须保留的目录" ────────────
    # 思路：维护一个 folder_has_undeletable_descendant: set[str]
    # 对子树做拓扑排序（BFS 从叶到根），逐层向上冒泡

    # 构建父子关系映射
    children_map: dict[str, list[str]] = defaultdict(list)
    parent_map: dict[str, Optional[str]] = {}
    for folder in folders:
        parent_map[folder.id] = folder.parent_id
        if folder.parent_id and folder.parent_id in set(actual_folder_ids):
            children_map[folder.parent_id].append(folder.id)

    # 对每个文件夹：记录它"是否含有不可删内容"
    # 初始化：自身权限不足 → 视为有不可删内容（对父节点而言）
    has_undeletable_content: dict[str, bool] = {}

    # 按拓扑序从叶到根处理（BFS 反向）
    # 先找出所有叶节点（在子树中没有子文件夹的节点）

    in_degree = {fid: len(children_map[fid]) for fid in actual_folder_ids}
    queue = deque([fid for fid in actual_folder_ids if in_degree[fid] == 0])

    topo_order = []
    while queue:
        fid = queue.popleft()
        topo_order.append(fid)
        parent_id = parent_map.get(fid)
        if parent_id and parent_id in in_degree:
            in_degree[parent_id] -= 1
            if in_degree[parent_id] == 0:
                queue.append(parent_id)

    if len(topo_order) != len(actual_folder_ids):
        raise RuntimeError("Cycle detected in folder hierarchy.")

    # 按拓扑序（叶 → 根）计算 has_undeletable_content
    # 文档归属到各自 folder 的"不可删内容"
    folder_has_undeletable_doc: dict[str, bool] = defaultdict(bool)
    for doc in documents:
        is_active = (
            doc.current_revision is not None and doc.current_revision.file.active
        )
        if is_active and doc.id not in deletable_doc_ids:
            if doc.folder_id:
                folder_has_undeletable_doc[doc.folder_id] = True

    for fid in topo_order:
        self_undeletable = not folder_self_deletable.get(fid, True)
        child_undeletable = any(
            has_undeletable_content.get(child_fid, False)
            for child_fid in children_map[fid]
        )
        doc_undeletable = folder_has_undeletable_doc.get(fid, False)
        has_undeletable_content[fid] = (
            self_undeletable or child_undeletable or doc_undeletable
        )

    # ── Step 9: 最终判定 (基于 topo_order 生成有序列表) ──────────────────────
    deletable_folder_ids: list[str] = []
    protected_folder_ids: set[str] = set()

    # 遍历 topo_order。由于 topo_order 是从叶子到根的，
    # 填充进 deletable_folder_ids 的顺序也将是“先删子目录，后删父目录”。
    for fid in topo_order:
        # 跳过 root_folder_id，它的处理由外部逻辑（Handler）决定
        if fid == root_folder_id:
            continue

        # 判断逻辑：自身有权删 且 没有任何不可删后代
        can_delete_folder = folder_self_deletable.get(
            fid, False
        ) and not has_undeletable_content.get(fid, False)

        if can_delete_folder:
            deletable_folder_ids.append(fid)
        else:
            protected_folder_ids.add(fid)

    return (
        deletable_folder_ids,  # 这是一个从深到浅的列表
        deletable_doc_ids,
        failed_items,
        protected_folder_ids,
        folder_map,
    )
