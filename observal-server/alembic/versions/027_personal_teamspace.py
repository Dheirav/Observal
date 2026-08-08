# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Mark each user's one personal teamspace.

Revision ID: 027_personal_teamspace
Revises: 026_team_visibility
"""

import sqlalchemy as sa

from alembic import op

revision = "027_personal_teamspace"
down_revision = "026_team_visibility"
branch_labels = None
depends_on = None


def _has_check(name: str) -> bool:
    return any(constraint["name"] == name for constraint in sa.inspect(op.get_bind()).get_check_constraints("teams"))


def upgrade() -> None:
    op.add_column(
        "teams",
        sa.Column("is_personal", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "uq_teams_personal_created_by",
        "teams",
        ["created_by"],
        unique=True,
        postgresql_where=sa.text("is_personal"),
        sqlite_where=sa.text("is_personal = 1"),
    )
    if not _has_check("ck_teams_personal_private"):
        op.create_check_constraint("ck_teams_personal_private", "teams", "NOT is_personal OR is_private")


def downgrade() -> None:
    if _has_check("ck_teams_personal_private"):
        op.drop_constraint("ck_teams_personal_private", "teams", type_="check")
    op.drop_index("uq_teams_personal_created_by", table_name="teams")
    op.drop_column("teams", "is_personal")
