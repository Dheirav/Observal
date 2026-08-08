# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add named, recoverable team invites and request audit links.

Revision ID: 029_named_team_invite_audit
Revises: 027_personal_teamspace
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "029_named_team_invite_audit"
down_revision = "027_personal_teamspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "team_invites",
        sa.Column("name", sa.String(length=100), nullable=False, server_default="Invite link"),
    )
    op.add_column("team_invites", sa.Column("token_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "team_membership_requests",
        sa.Column(
            "invite_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("team_invites.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_team_membership_requests_invite_id",
        "team_membership_requests",
        ["invite_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_team_membership_requests_invite_id", table_name="team_membership_requests")
    op.drop_column("team_membership_requests", "invite_id")
    op.drop_column("team_invites", "token_encrypted")
    op.drop_column("team_invites", "name")
