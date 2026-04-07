"""Base classes, enums, and typed contracts for the MillForge tool system."""
from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    LOW = "LOW"       # read-only
    MEDIUM = "MEDIUM" # modifications with undo
    HIGH = "HIGH"     # destructive / irreversible


class Permission(str, Enum):
    READ_SCHEDULE = "READ_SCHEDULE"
    READ_MACHINES = "READ_MACHINES"
    READ_SUPPLIERS = "READ_SUPPLIERS"
    WRITE_JOBS = "WRITE_JOBS"
    WRITE_SCHEDULE = "WRITE_SCHEDULE"
    WRITE_MACHINES = "WRITE_MACHINES"
    SEND_PURCHASE_ORDERS = "SEND_PURCHASE_ORDERS"
    DELETE = "DELETE"
    BULK_IMPORT = "BULK_IMPORT"
    RUN_QUALITY_INSPECTION = "RUN_QUALITY_INSPECTION"
    EXPORT = "EXPORT"


class PermissionMode(str, Enum):
    INTERACTIVE = "interactive"     # prompt MEDIUM + HIGH
    AUTO_APPROVE = "auto_approve"   # auto LOW + MEDIUM; prompt HIGH
    FULL_AUTO = "full_auto"         # auto-approve everything
    READ_ONLY = "read_only"         # only LOW operations allowed


@dataclass
class ToolContext:
    """Scoped context passed to every tool invocation."""
    user_id: str
    shop_id: str
    permission_mode: PermissionMode
    db: Any | None = None           # SQLAlchemy session (read or write depending on tool risk)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def ok(cls) -> "ValidationResult":
        return cls(valid=True)

    @classmethod
    def fail(cls, *errors: str) -> "ValidationResult":
        return cls(valid=False, errors=list(errors))


@dataclass
class ToolResult:
    success: bool
    data: dict[str, Any]
    tool_name: str
    risk_level: RiskLevel
    error: str | None = None
    before_snapshot: dict[str, Any] | None = None  # HIGH-risk only
    after_snapshot: dict[str, Any] | None = None
    approval_method: str = "auto"
    invocation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Tool(ABC):
    """
    Abstract base class for all MillForge gated tools.

    Subclasses must set:
      name             — unique tool identifier
      description      — one-line description for UI/logging
      risk_level       — LOW / MEDIUM / HIGH
      required_permissions — list of Permission values

    And implement:
      validate()   — check params and context before execution
      execute()    — perform the action; return ToolResult
    """

    name: str
    description: str
    risk_level: RiskLevel
    required_permissions: list[Permission]

    @abstractmethod
    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        ...

    @abstractmethod
    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        ...

    def __repr__(self) -> str:
        return f"<Tool {self.name} risk={self.risk_level.value}>"
