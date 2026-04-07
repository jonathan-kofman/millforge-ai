"""Tool registry with permission checking, approval routing, and audit trail."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.base import (
    Permission,
    PermissionMode,
    RiskLevel,
    Tool,
    ToolContext,
    ToolResult,
    ValidationResult,
)

logger = logging.getLogger(__name__)

_AUDIT_LOG = Path("data/audit/tool_invocations.jsonl")


def _write_audit(entry: dict[str, Any]) -> None:
    """Append one JSON line to the audit log. Never raises."""
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:
        logger.warning("Audit write failed: %s", exc)


class ToolRegistry:
    """
    Central registry for all gated tools.

    Usage::

        registry = ToolRegistry()
        registry.register(ReadSchedule())
        registry.register(DeleteJob())

        result = await registry.invoke("ReadSchedule", params={}, context=ctx)
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s [%s]", tool.name, tool.risk_level.value)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "risk_level": t.risk_level.value,
                "required_permissions": [p.value for p in t.required_permissions],
            }
            for t in self._tools.values()
        ]

    # ── Permission check ──────────────────────────────────────────────────

    def _check_permissions(self, tool: Tool, context: ToolContext) -> ValidationResult:
        """Verify the context holds all required permissions for this tool."""
        granted = context.metadata.get("granted_permissions", [])
        missing = [p.value for p in tool.required_permissions if p.value not in granted]
        if missing:
            return ValidationResult.fail(f"Missing permissions: {', '.join(missing)}")
        return ValidationResult.ok()

    def _approval_required(self, tool: Tool, context: ToolContext) -> bool:
        """Return True if the current mode requires explicit user approval."""
        mode = context.permission_mode
        risk = tool.risk_level

        if mode == PermissionMode.READ_ONLY:
            # Only LOW is allowed at all; MEDIUM/HIGH blocked entirely
            return risk != RiskLevel.LOW
        if mode == PermissionMode.FULL_AUTO:
            return False
        if mode == PermissionMode.AUTO_APPROVE:
            return risk == RiskLevel.HIGH
        # INTERACTIVE: prompt for MEDIUM and HIGH
        return risk in (RiskLevel.MEDIUM, RiskLevel.HIGH)

    def _mode_allows(self, tool: Tool, context: ToolContext) -> bool:
        """Return True if this tool is allowed at all under the current mode."""
        if context.permission_mode == PermissionMode.READ_ONLY:
            return tool.risk_level == RiskLevel.LOW
        return True

    # ── Main invoke ───────────────────────────────────────────────────────

    async def invoke(
        self,
        tool_name: str,
        params: dict[str, Any],
        context: ToolContext,
        *,
        approval_token: str | None = None,
    ) -> ToolResult:
        """
        Invoke a tool through the permission gate.

        approval_token: caller passes this when they have received explicit
        user approval (e.g. from a UI prompt). Required for MEDIUM/HIGH tools
        in INTERACTIVE and AUTO_APPROVE modes.
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                data={},
                tool_name=tool_name,
                risk_level=RiskLevel.LOW,
                error=f"Unknown tool: {tool_name}",
            )

        # Mode gate
        if not self._mode_allows(tool, context):
            result = ToolResult(
                success=False,
                data={},
                tool_name=tool_name,
                risk_level=tool.risk_level,
                error=f"Tool {tool_name} ({tool.risk_level.value}) not allowed in {context.permission_mode.value} mode",
                approval_method="blocked",
            )
            _write_audit({
                "invocation_id": result.invocation_id,
                "tool": tool_name,
                "risk": tool.risk_level.value,
                "user_id": context.user_id,
                "shop_id": context.shop_id,
                "params": params,
                "outcome": "blocked_by_mode",
                "timestamp": result.executed_at.isoformat(),
            })
            return result

        # Permission check
        perm_check = self._check_permissions(tool, context)
        if not perm_check.valid:
            result = ToolResult(
                success=False,
                data={},
                tool_name=tool_name,
                risk_level=tool.risk_level,
                error=perm_check.errors[0],
                approval_method="permission_denied",
            )
            _write_audit({
                "invocation_id": result.invocation_id,
                "tool": tool_name,
                "risk": tool.risk_level.value,
                "user_id": context.user_id,
                "shop_id": context.shop_id,
                "params": params,
                "outcome": "permission_denied",
                "errors": perm_check.errors,
                "timestamp": result.executed_at.isoformat(),
            })
            return result

        # Approval gate
        needs_approval = self._approval_required(tool, context)
        if needs_approval and not approval_token:
            result = ToolResult(
                success=False,
                data={"approval_required": True, "risk_level": tool.risk_level.value},
                tool_name=tool_name,
                risk_level=tool.risk_level,
                error=f"Approval required for {tool.risk_level.value} action. Re-invoke with approval_token.",
                approval_method="pending",
            )
            _write_audit({
                "invocation_id": result.invocation_id,
                "tool": tool_name,
                "risk": tool.risk_level.value,
                "user_id": context.user_id,
                "shop_id": context.shop_id,
                "params": params,
                "outcome": "approval_pending",
                "timestamp": result.executed_at.isoformat(),
            })
            return result

        # Validation
        validation = await tool.validate(params, context)
        if not validation.valid:
            result = ToolResult(
                success=False,
                data={},
                tool_name=tool_name,
                risk_level=tool.risk_level,
                error="; ".join(validation.errors),
                approval_method="validation_failed",
            )
            _write_audit({
                "invocation_id": result.invocation_id,
                "tool": tool_name,
                "risk": tool.risk_level.value,
                "user_id": context.user_id,
                "shop_id": context.shop_id,
                "params": params,
                "outcome": "validation_failed",
                "errors": validation.errors,
                "timestamp": result.executed_at.isoformat(),
            })
            return result

        # Execute
        approval_method = (
            "user_approved" if approval_token
            else "auto_approved"
        )
        result = await tool.execute(params, context)
        result.approval_method = approval_method

        # Audit trail (HIGH-risk includes before/after snapshot)
        audit_entry: dict[str, Any] = {
            "invocation_id": result.invocation_id,
            "tool": tool_name,
            "risk": tool.risk_level.value,
            "user_id": context.user_id,
            "shop_id": context.shop_id,
            "params": params,
            "outcome": "success" if result.success else "error",
            "approval_method": approval_method,
            "timestamp": result.executed_at.isoformat(),
        }
        if result.error:
            audit_entry["error"] = result.error
        if tool.risk_level == RiskLevel.HIGH:
            audit_entry["before_snapshot"] = result.before_snapshot
            audit_entry["after_snapshot"] = result.after_snapshot

        _write_audit(audit_entry)
        logger.info(
            "Tool invoked: %s [%s] user=%s success=%s",
            tool_name, tool.risk_level.value, context.user_id, result.success,
        )
        return result


# Module-level singleton
_registry = ToolRegistry()

def get_registry() -> ToolRegistry:
    return _registry
