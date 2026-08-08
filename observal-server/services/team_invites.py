# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Validation for private-team invitation tokens."""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.team_invite import TeamInvite


def invite_state(invite: TeamInvite, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    expires = invite.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if invite.revoked_at is not None:
        return "revoked"
    if expires <= now:
        return "expired"
    if invite.max_uses is not None and invite.use_count >= invite.max_uses:
        return "exhausted"
    return "active"


async def team_invite_by_token(
    db: AsyncSession,
    token: str,
    *,
    team_id=None,
    for_update: bool = False,
) -> TeamInvite | None:
    stmt = select(TeamInvite).where(TeamInvite.token_hash == hashlib.sha256(token.encode()).hexdigest())
    if team_id is not None:
        stmt = stmt.where(TeamInvite.team_id == team_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def redeemable_team_invite(
    db: AsyncSession,
    token: str,
    *,
    team_id=None,
    for_update: bool = False,
) -> TeamInvite | None:
    invite = await team_invite_by_token(db, token, team_id=team_id, for_update=for_update)
    return invite if invite is not None and invite_state(invite) == "active" else None
