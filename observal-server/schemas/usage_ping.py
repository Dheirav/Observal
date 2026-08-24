# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Versioned usage-ping payloads and administrator-facing status schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UsagePingIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=160)
    hostname: str = Field(min_length=1, max_length=253)

    @field_validator("company_name", "hostname")
    @classmethod
    def strip_identity(cls, value: str) -> str:
        return value.strip()


class UsagePingInstance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=64)
    deployment_type: Literal["self-managed", "cloud", "development"]


class UsagePingCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    users: int = Field(ge=0)
    teams: int = Field(ge=0)
    agents: int = Field(ge=0)
    mcp_servers: int = Field(ge=0)
    skills: int = Field(ge=0)
    hooks: int = Field(ge=0)
    prompts: int = Field(ge=0)
    sandboxes: int = Field(ge=0)
    agent_installs: int = Field(ge=0)
    sessions_total: int = Field(ge=0)
    sessions_7d: int = Field(ge=0)
    sessions_30d: int = Field(ge=0)


class UsagePingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    ping_id: UUID
    installation_id: UUID
    sent_at: datetime
    identity: UsagePingIdentity
    instance: UsagePingInstance
    counts: UsagePingCounts
    features: dict[str, bool] = Field(default_factory=dict, max_length=32)
    harnesses: dict[str, int] = Field(default_factory=dict, max_length=32)


class UsagePingStatus(BaseModel):
    enabled: bool
    configured: bool
    collector_url: str
    installation_id: UUID | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    next_scheduled_at: datetime


class UsagePingAdminResponse(BaseModel):
    status: UsagePingStatus
    payload: UsagePingPayload | None = None
