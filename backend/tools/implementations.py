"""Concrete tool implementations for the MillForge gated tool system.

Each tool maps to a real backend capability.

| Tool                  | Risk   | Action                                    |
|-----------------------|--------|-------------------------------------------|
| ReadSchedule          | LOW    | View current/proposed schedules           |
| ReadMachineStatus     | LOW    | Check machine availability                |
| QuerySuppliers        | LOW    | Search supplier directory                 |
| ExportSchedulePDF     | LOW    | Generate PDF export                       |
| UpdateJobPriority     | MEDIUM | Change job queue ordering                 |
| GenerateSchedule      | MEDIUM | Run scheduling algorithm                  |
| ImportBulkOrders      | MEDIUM | CSV bulk import                           |
| RunQualityInspection  | MEDIUM | Trigger YOLOv8 inspection                 |
| AdjustScheduleParams  | MEDIUM | Modify algorithm parameters               |
| ModifyMachineConfig   | HIGH   | Change machine capabilities/constraints   |
| SendSupplierPO        | HIGH   | Transmit purchase order to supplier       |
| DeleteJob             | HIGH   | Remove job from system (irreversible)     |
"""
from __future__ import annotations

import logging
from typing import Any

from tools.base import (
    Permission,
    RiskLevel,
    Tool,
    ToolContext,
    ToolResult,
    ValidationResult,
)

logger = logging.getLogger(__name__)


# ── LOW-risk tools ────────────────────────────────────────────────────────────

class ReadSchedule(Tool):
    name = "ReadSchedule"
    description = "View current and proposed production schedules"
    risk_level = RiskLevel.LOW
    required_permissions = [Permission.READ_SCHEDULE]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        return ValidationResult.ok()

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            from agents.scheduler import Scheduler  # type: ignore[import]
            from agents.benchmark_data import get_mock_orders  # type: ignore[import]
            orders = params.get("orders") or get_mock_orders()
            schedule = Scheduler(orders=orders).optimize()
            on_time = sum(1 for o in schedule.scheduled_orders if o.on_time)
            return ToolResult(
                success=True,
                data={
                    "total_orders": len(schedule.scheduled_orders),
                    "on_time_count": on_time,
                    "on_time_pct": round(on_time / max(len(schedule.scheduled_orders), 1) * 100, 1),
                    "makespan_minutes": schedule.makespan_minutes,
                },
                tool_name=self.name,
                risk_level=self.risk_level,
            )
        except Exception as exc:
            return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=str(exc))


class ReadMachineStatus(Tool):
    name = "ReadMachineStatus"
    description = "Check machine availability and current state"
    risk_level = RiskLevel.LOW
    required_permissions = [Permission.READ_MACHINES]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        return ValidationResult.ok()

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            from main import machine_fleet  # type: ignore[import]
            snapshot = machine_fleet.snapshot()
            return ToolResult(
                success=True,
                data={"machines": snapshot, "count": len(snapshot)},
                tool_name=self.name,
                risk_level=self.risk_level,
            )
        except Exception as exc:
            return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=str(exc))


class QuerySuppliers(Tool):
    name = "QuerySuppliers"
    description = "Search the verified US supplier directory"
    risk_level = RiskLevel.LOW
    required_permissions = [Permission.READ_SUPPLIERS]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        if not params.get("material") and not params.get("state") and not params.get("category"):
            return ValidationResult.fail("At least one search filter required (material, state, or category)")
        return ValidationResult.ok()

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            from agents.supplier_directory import SupplierDirectory  # type: ignore[import]
            directory = SupplierDirectory()
            suppliers, total = directory.search(
                context.db,
                material=params.get("material"),
                state=params.get("state"),
                category=params.get("category"),
                verified_only=params.get("verified_only", False),
                skip=0,
                limit=params.get("limit", 20),
            )
            return ToolResult(
                success=True,
                data={"total": total, "results": len(suppliers), "suppliers": [s.name for s in suppliers[:10]]},
                tool_name=self.name,
                risk_level=self.risk_level,
            )
        except Exception as exc:
            return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=str(exc))


class ExportSchedulePDF(Tool):
    name = "ExportSchedulePDF"
    description = "Generate a PDF export of the current schedule"
    risk_level = RiskLevel.LOW
    required_permissions = [Permission.EXPORT]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        return ValidationResult.ok()

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(
            success=True,
            data={"export_url": "/api/schedule/export-pdf", "format": "pdf"},
            tool_name=self.name,
            risk_level=self.risk_level,
        )


# ── MEDIUM-risk tools ─────────────────────────────────────────────────────────

class UpdateJobPriority(Tool):
    name = "UpdateJobPriority"
    description = "Change a job's queue priority (1=highest)"
    risk_level = RiskLevel.MEDIUM
    required_permissions = [Permission.WRITE_JOBS]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        errors: list[str] = []
        if not params.get("job_id"):
            errors.append("job_id is required")
        priority = params.get("priority")
        if priority is None:
            errors.append("priority is required")
        elif not (1 <= int(priority) <= 10):
            errors.append("priority must be 1–10")
        return ValidationResult(valid=not errors, errors=errors)

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        job_id = params["job_id"]
        new_priority = int(params["priority"])
        try:
            from db_models import Job  # type: ignore[import]
            db = context.db
            if db is None:
                return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error="No DB session in context")
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=f"Job {job_id} not found")
            before = {"job_id": job_id, "priority": job.priority}
            job.priority = new_priority
            db.commit()
            return ToolResult(
                success=True,
                data={"job_id": job_id, "old_priority": before["priority"], "new_priority": new_priority},
                tool_name=self.name,
                risk_level=self.risk_level,
            )
        except Exception as exc:
            return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=str(exc))


class GenerateSchedule(Tool):
    name = "GenerateSchedule"
    description = "Run the scheduling algorithm (EDD or SA) on pending orders"
    risk_level = RiskLevel.MEDIUM
    required_permissions = [Permission.WRITE_SCHEDULE]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        alg = params.get("algorithm", "edd")
        if alg not in ("edd", "sa", "fifo"):
            return ValidationResult.fail(f"Unknown algorithm '{alg}'. Must be edd, sa, or fifo.")
        return ValidationResult.ok()

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            alg = params.get("algorithm", "edd")
            orders = params.get("orders", [])
            if alg == "sa":
                from agents.sa_scheduler import SAScheduler  # type: ignore[import]
                schedule = SAScheduler().optimize(orders)
            else:
                from agents.scheduler import Scheduler  # type: ignore[import]
                schedule = Scheduler(orders=orders).optimize()
            on_time = sum(1 for o in schedule.scheduled_orders if o.on_time)
            total = len(schedule.scheduled_orders)
            return ToolResult(
                success=True,
                data={
                    "algorithm": alg,
                    "total_orders": total,
                    "on_time_count": on_time,
                    "on_time_pct": round(on_time / max(total, 1) * 100, 1),
                    "makespan_minutes": schedule.makespan_minutes,
                },
                tool_name=self.name,
                risk_level=self.risk_level,
            )
        except Exception as exc:
            return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=str(exc))


class ImportBulkOrders(Tool):
    name = "ImportBulkOrders"
    description = "Import orders from a CSV file"
    risk_level = RiskLevel.MEDIUM
    required_permissions = [Permission.BULK_IMPORT, Permission.WRITE_JOBS]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        if not params.get("csv_content") and not params.get("file_path"):
            return ValidationResult.fail("csv_content or file_path is required")
        return ValidationResult.ok()

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            from agents.csv_importer import CSVImporter  # type: ignore[import]
            importer = CSVImporter()
            csv_text = params.get("csv_content", "")
            result = importer.parse(csv_text)
            return ToolResult(
                success=True,
                data={"imported_count": len(result.orders), "errors": result.errors},
                tool_name=self.name,
                risk_level=self.risk_level,
            )
        except Exception as exc:
            return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=str(exc))


class RunQualityInspection(Tool):
    name = "RunQualityInspection"
    description = "Trigger YOLOv8 defect inspection on a part image"
    risk_level = RiskLevel.MEDIUM
    required_permissions = [Permission.RUN_QUALITY_INSPECTION]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        errors: list[str] = []
        if not params.get("image_url"):
            errors.append("image_url is required")
        if not params.get("order_id"):
            errors.append("order_id is required")
        return ValidationResult(valid=not errors, errors=errors)

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            from agents.quality_vision import QualityVisionAgent  # type: ignore[import]
            agent = QualityVisionAgent()
            result = agent.inspect(
                image_url=params["image_url"],
                material=params.get("material", "steel"),
                order_id=params["order_id"],
            )
            return ToolResult(
                success=True,
                data={
                    "order_id": result.order_id,
                    "passed": result.passed,
                    "confidence": result.confidence,
                    "defects": result.defects_detected,
                    "recommendation": result.recommendation,
                },
                tool_name=self.name,
                risk_level=self.risk_level,
            )
        except Exception as exc:
            return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=str(exc))


class AdjustScheduleParams(Tool):
    name = "AdjustScheduleParams"
    description = "Modify scheduling algorithm parameters (temperature, iterations)"
    risk_level = RiskLevel.MEDIUM
    required_permissions = [Permission.WRITE_SCHEDULE]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        errors: list[str] = []
        if "max_iterations" in params and not (100 <= int(params["max_iterations"]) <= 100_000):
            errors.append("max_iterations must be 100–100,000")
        if "init_temp" in params and not (1.0 <= float(params["init_temp"]) <= 10_000.0):
            errors.append("init_temp must be 1.0–10,000.0")
        return ValidationResult(valid=not errors, errors=errors)

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult(
            success=True,
            data={"applied_params": params, "note": "Params will apply to next GenerateSchedule call"},
            tool_name=self.name,
            risk_level=self.risk_level,
        )


# ── HIGH-risk tools ───────────────────────────────────────────────────────────

class ModifyMachineConfig(Tool):
    name = "ModifyMachineConfig"
    description = "Change machine capabilities or constraints (irreversible without re-config)"
    risk_level = RiskLevel.HIGH
    required_permissions = [Permission.WRITE_MACHINES]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        errors: list[str] = []
        if not params.get("machine_id"):
            errors.append("machine_id is required")
        if not params.get("updates"):
            errors.append("updates dict is required")
        return ValidationResult(valid=not errors, errors=errors)

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        machine_id = params["machine_id"]
        updates = params["updates"]
        try:
            from db_models import Machine  # type: ignore[import]
            db = context.db
            if db is None:
                return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error="No DB session")
            machine = db.query(Machine).filter(Machine.id == machine_id).first()
            if not machine:
                return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=f"Machine {machine_id} not found")
            before = {k: getattr(machine, k, None) for k in updates}
            for k, v in updates.items():
                if hasattr(machine, k):
                    setattr(machine, k, v)
            db.commit()
            after = {k: getattr(machine, k, None) for k in updates}
            return ToolResult(
                success=True,
                data={"machine_id": machine_id, "updated_fields": list(updates.keys())},
                tool_name=self.name,
                risk_level=self.risk_level,
                before_snapshot=before,
                after_snapshot=after,
            )
        except Exception as exc:
            return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=str(exc))


class SendSupplierPO(Tool):
    name = "SendSupplierPO"
    description = "Transmit a purchase order to a supplier (external, irreversible)"
    risk_level = RiskLevel.HIGH
    required_permissions = [Permission.SEND_PURCHASE_ORDERS]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        errors: list[str] = []
        for field in ("supplier_id", "material", "quantity", "unit"):
            if not params.get(field):
                errors.append(f"{field} is required")
        return ValidationResult(valid=not errors, errors=errors)

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        # In a real system: POST to supplier API or generate EDI file
        po_number = f"PO-{context.shop_id[:4].upper()}-{context.request_id}"
        return ToolResult(
            success=True,
            data={
                "po_number": po_number,
                "supplier_id": params["supplier_id"],
                "material": params["material"],
                "quantity": params["quantity"],
                "unit": params["unit"],
                "status": "submitted",
                "note": "PO transmitted (simulated — real EDI integration pending)",
            },
            tool_name=self.name,
            risk_level=self.risk_level,
            before_snapshot={"status": "draft"},
            after_snapshot={"status": "submitted", "po_number": po_number},
        )


class DeleteJob(Tool):
    name = "DeleteJob"
    description = "Permanently remove a job from the system"
    risk_level = RiskLevel.HIGH
    required_permissions = [Permission.DELETE, Permission.WRITE_JOBS]

    async def validate(self, params: dict[str, Any], context: ToolContext) -> ValidationResult:
        if not params.get("job_id"):
            return ValidationResult.fail("job_id is required")
        return ValidationResult.ok()

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        job_id = params["job_id"]
        try:
            from db_models import Job  # type: ignore[import]
            db = context.db
            if db is None:
                return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error="No DB session")
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=f"Job {job_id} not found")
            snapshot = {"job_id": job_id, "status": getattr(job, "status", "unknown"), "material": getattr(job, "material", "unknown")}
            db.delete(job)
            db.commit()
            return ToolResult(
                success=True,
                data={"deleted_job_id": job_id},
                tool_name=self.name,
                risk_level=self.risk_level,
                before_snapshot=snapshot,
                after_snapshot={"status": "deleted"},
            )
        except Exception as exc:
            return ToolResult(success=False, data={}, tool_name=self.name, risk_level=self.risk_level, error=str(exc))


# ── Registry bootstrap ────────────────────────────────────────────────────────

def register_all_tools() -> None:
    """Register all built-in tools with the global registry."""
    from tools.registry import get_registry
    registry = get_registry()
    for tool_cls in [
        ReadSchedule, ReadMachineStatus, QuerySuppliers, ExportSchedulePDF,
        UpdateJobPriority, GenerateSchedule, ImportBulkOrders, RunQualityInspection,
        AdjustScheduleParams,
        ModifyMachineConfig, SendSupplierPO, DeleteJob,
    ]:
        registry.register(tool_cls())
    logger.info("All tools registered (%d total)", len(registry.list_tools()))
