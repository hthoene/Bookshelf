"""add author sort key and index for the default library order

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12 21:29:14.539958
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _author_sort_key(author: str | None) -> str | None:
    # Frozen copy of bookshelf.models.author_sort_key at the time of this migration.
    first = (author or "").split(" & ")[0].strip()
    if not first:
        return None
    if "," not in first and " " in first:
        given, surname = first.rsplit(" ", 1)
        first = f"{surname}, {given}"
    return first.casefold()


def upgrade() -> None:
    with op.batch_alter_table("books", schema=None) as batch_op:
        batch_op.add_column(sa.Column("author_sort", sa.String(length=500), nullable=True))
        batch_op.create_index("ix_books_user_recent", ["user_id", "created_at", "id"])

    connection = op.get_bind()
    books = sa.table("books", sa.column("id"), sa.column("author"), sa.column("author_sort"))
    rows = connection.execute(sa.select(books.c.id, books.c.author)).all()
    for book_id, author in rows:
        connection.execute(
            books.update()
            .where(books.c.id == book_id)
            .values(author_sort=_author_sort_key(author))
        )


def downgrade() -> None:
    with op.batch_alter_table("books", schema=None) as batch_op:
        batch_op.drop_index("ix_books_user_recent")
        batch_op.drop_column("author_sort")
