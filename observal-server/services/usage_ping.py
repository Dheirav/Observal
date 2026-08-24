# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Privacy-bounded collection and delivery of aggregate installation usage."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from loguru import logger as optic
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

import services.dynamic_settings as ds
from config import settings
from models.agent import Agent
from models.download import AgentDownloadRecord
from models.hook import HookListing
from models.mcp import McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing
from models.team import Team
from models.usage_ping import UsagePingState
from models.user import User
from schemas.usage_ping import (
    UsagePingCounts,
    UsagePingIdentity,
    UsagePingInstance,
    UsagePingPayload,
    UsagePingStatus,
)
from services.ssrf_guard import is_private_url
from version import get_server_version

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_SCHEMA_VERSION = 1
_STATE_ID = 1
_PRODUCTION_COLLECTOR_URL = "https://telemetry.observal.io/api/v1/usage-pings"
_LOCAL_COLLECTOR_HOSTS = {"localhost", "127.0.0.1", "telemetry-api"}


def next_scheduled_at(now: datetime | None = None) -> datetime:
    """Return the next Monday at 06:30 UTC, matching the worker schedule."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    days = (7 - current.weekday()) % 7
    candidate = (current + timedelta(days=days)).replace(hour=6, minute=30, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=7)
    return candidate


def _reporting_week(value: datetime) -> str:
    monday = value.date() - timedelta(days=value.weekday())
    return monday.isoformat()


def _hostname(public_url: str) -> str:
    value = public_url.strip()
    if not value:
        return "not-configured"
    parsed = urlparse(value if "://" in value else f"//{value}")
    return (parsed.hostname or "not-configured").lower()


def _deployment_type() -> str:
    if settings.USAGE_PING_DEPLOYMENT_TYPE:
        return settings.USAGE_PING_DEPLOYMENT_TYPE
    return "development" if get_server_version() == "dev" else "self-managed"


async def _state(db: AsyncSession) -> UsagePingState:
    state = await db.get(UsagePingState, _STATE_ID)
    if state is None:
        state = UsagePingState(id=_STATE_ID)
        db.add(state)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            state = await db.get(UsagePingState, _STATE_ID)
            if state is None:
                raise
    return state


async def _safe_count(db: AsyncSession, model, *conditions) -> int:
    try:
        statement = select(func.count()).select_from(model)
        if conditions:
            statement = statement.where(*conditions)
        async with db.begin_nested():
            return int(await db.scalar(statement) or 0)
    except Exception as exc:
        optic.warning("usage ping counter failed table={}: {}", model.__tablename__, exc)
        return 0


async def _postgres_counts(db: AsyncSession) -> dict[str, int]:
    return {
        "users": await _safe_count(db, User, User.is_demo.is_(False)),
        "teams": await _safe_count(db, Team, Team.is_personal.is_(False)),
        "agents": await _safe_count(db, Agent, Agent.deleted_at.is_(None)),
        "mcp_servers": await _safe_count(db, McpListing),
        "skills": await _safe_count(db, SkillListing),
        "hooks": await _safe_count(db, HookListing),
        "prompts": await _safe_count(db, PromptListing),
        "sandboxes": await _safe_count(db, SandboxListing),
        "agent_installs": await _safe_count(db, AgentDownloadRecord),
    }


async def _session_counts() -> tuple[dict[str, int], dict[str, int]]:
    from services.clickhouse.client import _query

    totals = {"sessions_total": 0, "sessions_7d": 0, "sessions_30d": 0}
    harnesses: dict[str, int] = {}
    try:
        response = await _query(
            "SELECT uniqExact(session_id) AS sessions_total, "
            "uniqExactIf(session_id, last_event_time >= now() - INTERVAL 7 DAY) AS sessions_7d, "
            "uniqExactIf(session_id, last_event_time >= now() - INTERVAL 30 DAY) AS sessions_30d "
            "FROM session_stats_agg FORMAT JSON"
        )
        response.raise_for_status()
        rows = response.json().get("data", [])
        if rows:
            totals = {key: max(0, int(rows[0].get(key, 0))) for key in totals}
    except Exception as exc:
        optic.warning("usage ping session counters unavailable: {}", exc)

    try:
        response = await _query(
            "SELECT harness, uniqExact(session_id) AS sessions "
            "FROM session_stats_agg WHERE harness != '' GROUP BY harness "
            "ORDER BY sessions DESC LIMIT 32 FORMAT JSON"
        )
        response.raise_for_status()
        for row in response.json().get("data", [])[:32]:
            name = str(row.get("harness", ""))[:50]
            if name:
                harnesses[name] = max(0, int(row.get("sessions", 0)))
    except Exception as exc:
        optic.warning("usage ping harness counters unavailable: {}", exc)
    return totals, harnesses


async def build_usage_ping(db: AsyncSession, *, now: datetime | None = None) -> UsagePingPayload:
    """Build the exact aggregate payload shown in preview and sent upstream."""
    sent_at = (now or datetime.now(UTC)).astimezone(UTC)
    state = await _state(db)
    company_name = (await ds.get("usage_ping.company_name")).strip()
    public_url = await ds.get("deployment.public_url")
    postgres_counts = await _postgres_counts(db)
    session_counts, harnesses = await _session_counts()
    features = {
        "insights": await ds.get_bool("insights.batch_enabled"),
        "retention": await ds.get_bool("retention.enabled"),
        "sso": bool(
            await ds.get("oauth.client_id")
            or await ds.get("saml.idp_entity_id")
            or await ds.get("google.client_id")
            or await ds.get("github.client_id")
        ),
        "trace_privacy": await ds.get_bool("security.trace_privacy"),
        "registered_agents_only": await ds.get_bool("registry.registered_agents_only"),
    }
    ping_id = uuid.uuid5(state.installation_id, _reporting_week(sent_at))
    payload = UsagePingPayload(
        schema_version=_SCHEMA_VERSION,
        ping_id=ping_id,
        installation_id=state.installation_id,
        sent_at=sent_at,
        identity=UsagePingIdentity(company_name=company_name or "not-configured", hostname=_hostname(public_url)),
        instance=UsagePingInstance(version=get_server_version(), deployment_type=_deployment_type()),
        counts=UsagePingCounts(**postgres_counts, **session_counts),
        features=features,
        harnesses=harnesses,
    )
    await db.commit()
    return payload


async def usage_ping_status(db: AsyncSession) -> UsagePingStatus:
    state = await _state(db)
    enabled = await ds.get_bool("usage_ping.enabled")
    company_name = (await ds.get("usage_ping.company_name")).strip()
    public_url = (await ds.get("deployment.public_url")).strip()
    await db.commit()
    return UsagePingStatus(
        enabled=enabled,
        configured=bool(company_name and public_url),
        collector_url=_collector_url(),
        installation_id=state.installation_id,
        last_attempt_at=state.last_attempt_at,
        last_success_at=state.last_success_at,
        last_error=state.last_error,
        next_scheduled_at=next_scheduled_at(),
    )


def _collector_url() -> str:
    if settings.USAGE_PING_URL == _PRODUCTION_COLLECTOR_URL:
        return settings.USAGE_PING_URL
    parsed = urlparse(settings.USAGE_PING_URL)
    if settings.USAGE_PING_DEPLOYMENT_TYPE == "development" and parsed.hostname in _LOCAL_COLLECTOR_HOSTS:
        return settings.USAGE_PING_URL
    raise RuntimeError("Usage-ping collector override is only allowed for local development")


async def _deliver_payload(payload: UsagePingPayload) -> httpx.Response:
    """Deliver with bounded retries for transient transport and upstream failures."""
    collector_url = _collector_url()
    parsed = urlparse(collector_url)
    local_development = (
        settings.USAGE_PING_DEPLOYMENT_TYPE == "development" and parsed.hostname in _LOCAL_COLLECTOR_HOSTS
    )
    if not local_development and is_private_url(collector_url):
        raise RuntimeError("Usage-ping collector resolves to a private or internal address")

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=False) as client:
                response = await client.post(
                    collector_url,
                    json=payload.model_dump(mode="json"),
                    headers={"User-Agent": f"Observal/{payload.instance.version}"},
                )
                response.raise_for_status()
                return response
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
        except httpx.TransportError as exc:
            last_error = exc
        if attempt < 2:
            await asyncio.sleep(0.25 * (2**attempt))
    if last_error:
        raise last_error
    raise RuntimeError("Usage report delivery failed")


async def send_usage_ping(db: AsyncSession) -> str:
    """Send one usage ping. Disabled or incomplete installations are skipped."""
    if not await ds.get_bool("usage_ping.enabled"):
        return "disabled"
    company_name = (await ds.get("usage_ping.company_name")).strip()
    public_url = (await ds.get("deployment.public_url")).strip()
    if not company_name or not public_url:
        return "not-configured"

    payload = await build_usage_ping(db)
    state = await _state(db)
    state.last_attempt_at = datetime.now(UTC)
    state.last_payload = payload.model_dump(mode="json")
    try:
        response = await _deliver_payload(payload)
        state.last_success_at = datetime.now(UTC)
        state.last_error = None
        state.last_response = response.text[:500]
        result = "sent"
    except Exception as exc:
        state.last_error = str(exc)[:500]
        state.last_response = None
        result = "failed"
        optic.warning("usage ping delivery failed: {}", exc)
    await db.commit()
    return result
