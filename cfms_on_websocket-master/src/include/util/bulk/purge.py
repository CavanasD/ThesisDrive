from itertools import batched
from typing import List
from sqlalchemy.orm import Session

from include.constants import QUERY_CHUNK_SIZE
from include.database.models.entity import (
    Document,
    DocumentRevision,
    _batch_count_avatar_usages,
    _batch_count_other_revisions,
)
from include.database.models.file import File, FileTask, _queue_deferred_file_deletion


def purge_documents_bulk(session: Session, document_ids: List[str]):
    """
    高度优化的批量粉碎函数。
    将原本 600+ 次的单个文档删除，转化为针对所有文档的一组批量删除。
    """
    if not document_ids:
        return

    # 1. 批量获取所有受影响的修订版本 ID 和文件 ID
    revision_data = (
        session.query(DocumentRevision.id, DocumentRevision.file_id)
        .filter(DocumentRevision.document_id.in_(document_ids))
        .all()
    )

    if not revision_data:
        # 如果这些文档都没有修订版本，直接删除文档记录即可
        for chunk in batched(document_ids, QUERY_CHUNK_SIZE):
            session.query(Document).filter(Document.id.in_(chunk)).delete(
                synchronize_session=False
            )
        return

    rev_ids = [r[0] for r in revision_data]
    file_ids = {r[1] for r in revision_data if r[1]}

    # 2. 批量引用计数检查
    # 我们需要确认这些文件是否被“这批文档以外”的其他东西引用
    # 修改原本的计数逻辑，使其支持 excluded_doc_ids 集合
    other_rev_counts = _batch_count_other_revisions(
        session, list(file_ids), document_ids
    )
    avatar_counts = _batch_count_avatar_usages(session, list(file_ids))

    # 找出仅被这批文档引用、可以物理删除的文件 ID
    deletable_file_ids = [
        fid
        for fid in file_ids
        if other_rev_counts.get(fid, 0) + avatar_counts.get(fid, 0) == 0
    ]

    # 3. 批量删除 (使用 SQL 级别的 delete)
    # 我们处于 no_autoflush 模式下运行此块

    # 3a. 清理相关任务
    if deletable_file_ids:
        for chunk in batched(deletable_file_ids, QUERY_CHUNK_SIZE):
            session.query(FileTask).filter(FileTask.file_id.in_(chunk)).delete(
                synchronize_session=False
            )

    # 3b. 收集文件路径并删除 File 记录
    if deletable_file_ids:
        for chunk in batched(deletable_file_ids, QUERY_CHUNK_SIZE):
            files = session.query(File).filter(File.id.in_(chunk)).all()
            for f in files:
                _queue_deferred_file_deletion(session, f.path)
            session.query(File).filter(File.id.in_(chunk)).delete(
                synchronize_session=False
            )

    # 3c. 批量删除修订版本和文档
    for chunk in batched(rev_ids, QUERY_CHUNK_SIZE):
        session.query(DocumentRevision).filter(DocumentRevision.id.in_(chunk)).delete(
            synchronize_session=False
        )

    for chunk in batched(document_ids, QUERY_CHUNK_SIZE):
        # 还要处理 current_revision_id 的外键约束
        session.query(Document).filter(Document.id.in_(chunk)).update(
            {Document.current_revision_id: None}, synchronize_session=False
        )
        session.query(Document).filter(Document.id.in_(chunk)).delete(
            synchronize_session=False
        )
