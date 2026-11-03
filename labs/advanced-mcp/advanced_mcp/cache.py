# Copyright (c) 2026 Zenable, Inc.
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

READ = "deploy:read"
PROD = "deploy:prod"


class Identity(BaseModel):
    model_config = ConfigDict(frozen=True)
    tenant: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=64)


class AuthorizationContext(Identity):
    scopes: frozenset[str]

    def partition(self) -> str:
        identity = [self.tenant, self.subject, sorted(self.scopes)]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise PermissionError(f"Missing scope: {scope}")


class DeploymentStatus(BaseModel):
    tenant: str
    subject: str
    release: str


class CachedStatus(BaseModel):
    value: DeploymentStatus
    expires_at: float


class ResultCache(BaseModel):
    mode: Literal["off", "broken", "fixed"] = "off"
    entries: dict[tuple[str, ...], CachedStatus] = Field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def read(
        self,
        caller: AuthorizationContext,
        now: float,
        load: Callable[[], DeploymentStatus],
    ) -> DeploymentStatus:
        caller.require(READ)
        key = (
            ("status",)
            if self.mode == "broken"
            else (caller.tenant, caller.subject, caller.partition(), "status")
        )
        cached = self.entries.get(key)
        if self.mode != "off" and cached and now < cached.expires_at:
            self.hits += 1
            return cached.value.model_copy(deep=True)
        self.misses += 1
        value = load()
        if self.mode != "off":
            self.entries[key] = CachedStatus(
                value=value.model_copy(deep=True), expires_at=now + 30
            )
        return value

    def invalidate(self, tenant: str) -> None:
        self.entries = {
            key: entry
            for key, entry in self.entries.items()
            if entry.value.tenant != tenant
        }


class ManualClock(BaseModel):
    now: float = 0


ALICE = Identity(tenant="blue", subject="alice")
BOB = Identity(tenant="red", subject="bob")
