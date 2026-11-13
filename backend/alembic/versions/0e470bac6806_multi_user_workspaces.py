"""multi user workspaces

Adds a user_id owner to every workspace table and makes post/keyword uniqueness
per-user. Existing rows stay NULL and are claimed by the first account that
registers (see routers/auth.py).

Revision ID: 0e470bac6806
Revises: 1a84431d645e
Create Date: 2026-11-12 20:39:20.559453
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0e470bac6806"
down_revision: Union[str, None] = "1a84431d645e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    "action_log",
    "agent_settings",
    "draft_example",
    "job_post",
    "profile",
    "resume",
    "run",
    "search_query",
    "x_account",
)


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            batch_op.create_index(f"ix_{table}_user_id", ["user_id"], unique=False)

    # A post is unique per workspace, not globally.
    with op.batch_alter_table("job_post", schema=None) as batch_op:
        batch_op.drop_constraint("uq_job_post_post_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_job_post_user_post", ["user_id", "post_id"]
        )

    # Keywords are unique per workspace; the old global unique index goes away.
    with op.batch_alter_table("search_query", schema=None) as batch_op:
        batch_op.drop_index("ix_search_query_keyword")
        batch_op.create_index("ix_search_query_keyword", ["keyword"], unique=False)
        batch_op.create_unique_constraint(
            "uq_search_query_user_keyword", ["user_id", "keyword"]
        )


def downgrade() -> None:
    with op.batch_alter_table("search_query", schema=None) as batch_op:
        batch_op.drop_constraint("uq_search_query_user_keyword", type_="unique")
        batch_op.drop_index("ix_search_query_keyword")
        batch_op.create_index("ix_search_query_keyword", ["keyword"], unique=True)

    with op.batch_alter_table("job_post", schema=None) as batch_op:
        batch_op.drop_constraint("uq_job_post_user_post", type_="unique")
        batch_op.create_unique_constraint("uq_job_post_post_id", ["post_id"])

    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(f"ix_{table}_user_id")
            batch_op.drop_column("user_id")
