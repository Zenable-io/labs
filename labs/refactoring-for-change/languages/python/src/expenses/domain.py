# Copyright (c) 2026 Zenable, Inc.
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    tenant: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    actor: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    role: Literal["approver", "viewer"]


class Expense(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    tenant: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    account: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    cents: int = Field(gt=0, le=1_000_000)
    policy: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    request_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")


class Receipt(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    tenant: str
    actor: str
    expense: Expense
    paid_cents: int


class Snapshot(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    alpha: int
    beta: int
    events: int


class Refused(Exception):
    pass
