"""Versioned operations policy. Physical inputs and release gates stay explicit."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    enabled: bool = False
    raw_days: int = Field(default=30, ge=1, le=3650)
    clip_days: int = Field(default=30, ge=1, le=3650)
    audit_policy: Literal["retain"] = "retain"
    # Approved training/incident exceptions: session ID -> responsible owner/reason.
    holds: dict[str, str] = Field(default_factory=dict, max_length=10000)


class OperationsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    min_free_bytes: int = Field(default=1024**3, ge=0)
    integrity_interval_seconds: float = Field(default=30, ge=1, le=3600)

