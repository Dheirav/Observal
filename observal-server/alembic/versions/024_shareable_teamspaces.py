# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Add shareable teamspaces, membership requests, and private invites.

Revision ID: 024_shareable_teamspaces
Revises: 023_inbox
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "024_shareable_teamspaces"
down_revision = "023_inbox"
branch_labels = None
depends_on = None

JOIN_REQUEST_STATUSES = ("pending", "approved", "rejected", "cancelled")


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    return any(index["name"] == name for index in sa.inspect(op.get_bind()).get_indexes(table))


def _has_check(table: str, name: str) -> bool:
    return any(check["name"] == name for check in sa.inspect(op.get_bind()).get_check_constraints(table))


def upgrade() -> None:
    if not _has_column("teams", "is_private"):
        op.add_column(
            "teams",
            sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not _has_column("teams", "is_personal"):
        op.add_column(
            "teams",
            sa.Column("is_personal", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not _has_index("teams", "uq_teams_personal_created_by"):
        op.create_index(
            "uq_teams_personal_created_by",
            "teams",
            ["created_by"],
            unique=True,
            postgresql_where=sa.text("is_personal"),
            sqlite_where=sa.text("is_personal = 1"),
        )
    if not _has_check("teams", "ck_teams_personal_private"):
        op.create_check_constraint("ck_teams_personal_private", "teams", "NOT is_personal OR is_private")

    if not _has_table("team_invites"):
        op.create_table(
            "team_invites",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("token_encrypted", sa.Text(), nullable=True),
            sa.Column("name", sa.String(length=100), nullable=False, server_default="Invite link"),
            sa.Column(
                "team_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("teams.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "invited_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("max_uses", sa.Integer(), nullable=True),
            sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("token_hash", name="uq_team_invites_token_hash"),
        )
    else:
        if not _has_column("team_invites", "token_encrypted"):
            op.add_column("team_invites", sa.Column("token_encrypted", sa.Text(), nullable=True))
        if not _has_column("team_invites", "name"):
            op.add_column(
                "team_invites",
                sa.Column("name", sa.String(length=100), nullable=False, server_default="Invite link"),
            )
    if not _has_index("team_invites", "ix_team_invites_team_id"):
        op.create_index("ix_team_invites_team_id", "team_invites", ["team_id"])
    if not _has_index("team_invites", "ix_team_invites_invited_by"):
        op.create_index("ix_team_invites_invited_by", "team_invites", ["invited_by"])

    bind = op.get_bind()
    status_enum = sa.Enum(*JOIN_REQUEST_STATUSES, name="team_join_request_status")
    if bind.dialect.name == "postgresql":
        status_enum.create(bind, checkfirst=True)
        status_enum = postgresql.ENUM(*JOIN_REQUEST_STATUSES, name="team_join_request_status", create_type=False)

    if not _has_table("team_membership_requests"):
        op.create_table(
            "team_membership_requests",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "team_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("teams.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "invite_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("team_invites.id", ondelete="RESTRICT"),
                nullable=True,
            ),
            sa.Column("status", status_enum, nullable=False, server_default="pending"),
            sa.Column("message", sa.String(length=500), nullable=True),
            sa.Column(
                "decided_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_reason", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    elif not _has_column("team_membership_requests", "invite_id"):
        op.add_column(
            "team_membership_requests",
            sa.Column(
                "invite_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("team_invites.id", ondelete="RESTRICT"),
                nullable=True,
            ),
        )
    if not _has_index("team_membership_requests", "uq_team_membership_requests_pending"):
        op.create_index(
            "uq_team_membership_requests_pending",
            "team_membership_requests",
            ["team_id", "user_id"],
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
            sqlite_where=sa.text("status = 'pending'"),
        )
    if not _has_index("team_membership_requests", "ix_team_membership_requests_user_id"):
        op.create_index(
            "ix_team_membership_requests_user_id",
            "team_membership_requests",
            ["user_id"],
        )
    if not _has_index("team_membership_requests", "ix_team_membership_requests_invite_id"):
        op.create_index(
            "ix_team_membership_requests_invite_id",
            "team_membership_requests",
            ["invite_id"],
        )


def downgrade() -> None:
    if _has_table("team_membership_requests"):
        op.drop_table("team_membership_requests")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="team_join_request_status").drop(bind, checkfirst=True)

    if _has_table("team_invites"):
        op.drop_table("team_invites")

    if _has_check("teams", "ck_teams_personal_private"):
        op.drop_constraint("ck_teams_personal_private", "teams", type_="check")
    if _has_index("teams", "uq_teams_personal_created_by"):
        op.drop_index("uq_teams_personal_created_by", table_name="teams")
    if _has_column("teams", "is_personal"):
        op.drop_column("teams", "is_personal")
    if _has_column("teams", "is_private"):
        op.drop_column("teams", "is_private")
