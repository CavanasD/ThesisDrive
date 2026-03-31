"""optimize database structure

Revision ID: e805605cbb30
Revises: 436b0d3452b6
Create Date: 2026-02-20 23:05:18.215004

"""
from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import MetaData, Table, ForeignKeyConstraint


# revision identifiers, used by Alembic.
revision: str = 'e805605cbb30'
down_revision: Union[str, Sequence[str], None] = '436b0d3452b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_fk(
    conn: sa.engine.Connection,
    table_name: str,
    fk_col: str,
    ref_table: str,
    ref_col: str,
    fk_name: str,
    ondelete: Optional[str] = None,
) -> None:
    """
    Replace a FK constraint on *fk_col* with a new one, optionally adding an
    ON DELETE action.  Works for both named and unnamed FK constraints so that
    the migration is safe regardless of how the database was originally created
    (i.e. with or without a SQLAlchemy naming convention in effect).

    The implementation reflects the current table into a fresh MetaData that
    carries no naming convention, removes the old FK, appends the new one, and
    then hands the modified Table to ``batch_alter_table(copy_from=…)`` so that
    Alembic rebuilds the table from that definition.  No explicit
    ``drop_constraint`` call is made, which avoids the two failure modes:

    * ``ValueError: No such constraint: '<name>'``   – FK was unnamed in the DB.
    * ``IndexError: list index out of range``         – naming convention fires
      on an empty ForeignKeyConstraint when ``None`` is passed as the name.
    """
    fresh_meta = MetaData()  # no naming convention → safe to attach unnamed FKs
    current_table = Table(table_name, fresh_meta, autoload_with=conn)

    # Remove the old FK on *fk_col* (named or unnamed)
    fk_to_remove = None
    for constraint in list(current_table.constraints):
        if isinstance(constraint, ForeignKeyConstraint):
            cols = [fk.parent.key for fk in constraint.elements]
            if cols == [fk_col]:
                fk_to_remove = constraint
                break
    if fk_to_remove is not None:
        current_table.constraints.discard(fk_to_remove)

    # Add the replacement FK
    kw: dict[str, str] = {"name": fk_name}
    if ondelete:
        kw["ondelete"] = ondelete
    current_table.append_constraint(
        ForeignKeyConstraint([fk_col], [f"{ref_table}.{ref_col}"], **kw)
    )

    # Rebuild the table using the modified schema as the source
    with op.batch_alter_table(
        table_name, recreate="always", copy_from=current_table
    ) as _batch_op:
        pass  # all changes are expressed through copy_from


def upgrade() -> None:
    """Add ON DELETE CASCADE to all FK constraints that participate in cascade deletes."""
    conn = op.get_bind()

    _replace_fk(conn, "documents", "folder_id", "folders", "id",
                "fk_documents_folder_id_folders", ondelete="CASCADE")
    _replace_fk(conn, "file_tasks", "file_id", "files", "id",
                "fk_file_tasks_file_id_files", ondelete="CASCADE")
    _replace_fk(conn, "folders", "parent_id", "folders", "id",
                "fk_folders_parent_id_folders", ondelete="CASCADE")
    _replace_fk(conn, "group_permissions", "group_name", "user_groups", "group_name",
                "fk_group_permissions_group_name_user_groups", ondelete="CASCADE")
    _replace_fk(conn, "keyrings", "username", "users", "username",
                "fk_keyrings_username_users", ondelete="CASCADE")
    _replace_fk(conn, "user_memberships", "username", "users", "username",
                "fk_user_memberships_username_users", ondelete="CASCADE")
    _replace_fk(conn, "user_memberships", "group_name", "user_groups", "group_name",
                "fk_user_memberships_group_name_user_groups", ondelete="CASCADE")
    _replace_fk(conn, "user_permissions", "username", "users", "username",
                "fk_user_permissions_username_users", ondelete="CASCADE")
    _replace_fk(conn, "userblock_entries", "username", "users", "username",
                "fk_userblock_entries_username_users", ondelete="CASCADE")
    _replace_fk(conn, "userblock_sub_entries", "parent_id", "userblock_entries", "block_id",
                "fk_userblock_sub_entries_parent_id_userblock_entries", ondelete="CASCADE")


def downgrade() -> None:
    """Remove ON DELETE CASCADE from FK constraints (restore to NO ACTION)."""
    conn = op.get_bind()

    _replace_fk(conn, "userblock_sub_entries", "parent_id", "userblock_entries", "block_id",
                "fk_userblock_sub_entries_parent_id_userblock_entries")
    _replace_fk(conn, "userblock_entries", "username", "users", "username",
                "fk_userblock_entries_username_users")
    _replace_fk(conn, "user_permissions", "username", "users", "username",
                "fk_user_permissions_username_users")
    _replace_fk(conn, "user_memberships", "group_name", "user_groups", "group_name",
                "fk_user_memberships_group_name_user_groups")
    _replace_fk(conn, "user_memberships", "username", "users", "username",
                "fk_user_memberships_username_users")
    _replace_fk(conn, "keyrings", "username", "users", "username",
                "fk_keyrings_username_users")
    _replace_fk(conn, "group_permissions", "group_name", "user_groups", "group_name",
                "fk_group_permissions_group_name_user_groups")
    _replace_fk(conn, "folders", "parent_id", "folders", "id",
                "fk_folders_parent_id_folders")
    _replace_fk(conn, "file_tasks", "file_id", "files", "id",
                "fk_file_tasks_file_id_files")
    _replace_fk(conn, "documents", "folder_id", "folders", "id",
                "fk_documents_folder_id_folders")
