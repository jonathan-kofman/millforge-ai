"""
Manufacturing Routing Engine
==============================
Selects the optimal process and machine assignment for a ManufacturingIntent.

Scoring model:
  Each candidate (process_family, machine) pair is evaluated by four factors:
    1. Cost fitness  — how well estimated cost fits within the cost_target_usd
    2. Time fitness  — reciprocal of cycle time (faster is better)
    3. Quality score — process achievable tolerance vs required tolerance class
    4. Energy score  — lower average power draw is better

  Factor weights are configurable at engine construction time and default to
  balanced values. The composite score is a weighted sum in [0, 1].

  All scores are normalized against the best option found in that evaluation
  round so the final score is always meaningful (not raw dollars or minutes).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .ontology import (
    ManufacturingIntent,
    ProcessFamily,
)
from .registry import MachineCapability, ProcessRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default scoring weights
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: Dict[str, float] = {
    "cost": 0.35,
    "time": 0.35,
    "quality": 0.20,
    "energy": 0.10,
}

# Tolerance class ordering — lower index = tighter tolerance (higher quality score)
TOLERANCE_CLASS_RANK: Dict[str, int] = {
    "ISO_2768_f": 0,    # fine
    "ISO_2768_m": 1,    # medium
    "ISO_2768_c": 2,    # coarse
    "ISO_2768_v": 3,    # very coarse
    "AS9100_D": 0,      # aerospace = tight
    "AWS_D1_1": 2,      # structural weld = medium/coarse
    "GD_T_ASME": 0,
}


# ---------------------------------------------------------------------------
# Result Models
# ---------------------------------------------------------------------------


class RouteOption(BaseModel):
    """
    A single candidate routing option — a (process, machine) pair with
    cost/time estimates and a composite fitness score.

    Attributes:
        process_family:               Which process family was selected
        machine:                      The machine that would execute it
        estimated_cycle_time_minutes: Per-unit cycle time
        estimated_cost_usd:           Total job cost (all units)
        setup_time_minutes:           Setup / changeover time
        score:                        Composite fitness score (higher = better, max 1.0)
        reasoning:                    Human-readable explanation of why this option scored as it did
    """
    process_family: ProcessFamily
    machine: MachineCapability
    estimated_cycle_time_minutes: float
    estimated_cost_usd: float
    setup_time_minutes: float
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""

    @property
    def total_time_minutes(self) -> float:
        return self.setup_time_minutes + self.estimated_cycle_time_minutes * 1  # per first unit

    @property
    def cost_per_unit_usd(self) -> float:
        return self.estimated_cost_usd


class RoutingResult(BaseModel):
    """
    Complete routing result for a ManufacturingIntent.

    Attributes:
        intent:    The original intent
        options:   All evaluated options, sorted best-first
        selected:  The top option (None if no viable routes found)
        warnings:  Non-fatal issues discovered during routing
    """
    intent: ManufacturingIntent
    options: List[RouteOption]
    selected: Optional[RouteOption] = None
    warnings: List[str] = Field(default_factory=list)

    @property
    def has_viable_route(self) -> bool:
        return self.selected is not None


# ---------------------------------------------------------------------------
# Routing Engine
# ---------------------------------------------------------------------------


class RoutingEngine:
    """
    Evaluates all capable (process, machine) pairs for a ManufacturingIntent
    and returns them ranked by composite fitness score.

    Thread-safe: the engine itself is stateless; all state lives in the
    registry (which is already thread-safe).
    """

    def __init__(
        self,
        registry: ProcessRegistry,
        weights: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Args:
            registry: The ProcessRegistry to query for adapters and machines.
            weights:  Scoring weight dict with keys: "cost", "time", "quality", "energy".
                      Values should sum to 1.0. Defaults to DEFAULT_WEIGHTS.
        """
        self.registry = registry
        self.weights = self._normalise_weights(weights or DEFAULT_WEIGHTS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, intent: ManufacturingIntent) -> RoutingResult:
        """
        Find and score all viable (process, machine) options for the intent.

        Steps:
          1. Determine candidate process families (from required/preferred lists,
             or all registered processes if unspecified).
          2. For each candidate process family, run adapter.validate_intent().
          3. Find capable machines for each valid process family.
          4. Estimate cycle time and cost via the adapter.
          5. Score and rank options.

        Returns:
            RoutingResult with options sorted best-first and selected = options[0].
        """
        warnings: List[str] = []
        candidates = self._gather_candidates(intent, warnings)

        raw_options: List[Dict[str, Any]] = []

        for process_family, machine in candidates:
            adapter = self.registry.get_adapter(process_family)
            if adapter is None:
                continue

            # Validate
            errors = adapter.validate_intent(intent)
            if errors:
                logger.debug(
                    "Process %s rejected intent %s: %s",
                    process_family.value,
                    intent.part_id,
                    errors,
                )
                continue

            # Check dimension compatibility
            if not self._check_dimension_compatibility(process_family, machine, intent):
                warnings.append(
                    f"{machine.machine_id} ({process_family.value}): part may exceed work envelope"
                )
                continue

            try:
                cycle_time = adapter.estimate_cycle_time(intent, machine)
                cost = adapter.estimate_cost(intent, machine)
                setup_time = adapter.estimate_setup_time(intent, machine)
                energy = adapter.get_energy_profile(intent, machine)
            except Exception as exc:
                logger.warning(
                    "Adapter %s raised during estimation for %s: %s",
                    process_family.value,
                    intent.part_id,
                    exc,
                    exc_info=True,
                )
                warnings.append(
                    f"{process_family.value} on {machine.machine_id}: estimation error — {exc}"
                )
                continue

            raw_options.append(
                {
                    "process_family": process_family,
                    "machine": machine,
                    "cycle_time": cycle_time,
                    "cost": cost,
                    "setup_time": setup_time,
                    "energy_kw": energy.average_power_kw,
                    "energy": energy,
                }
            )

        if not raw_options:
            return RoutingResult(
                intent=intent,
                options=[],
                selected=None,
                warnings=warnings
                + [f"No viable route found for part '{intent.part_id}'."],
            )

        # Score and rank
        route_options = self._score_and_rank(raw_options, intent)

        # Check forbidden processes
        if intent.forbidden_processes:
            forbidden = set(intent.forbidden_processes)
            before = len(route_options)
            route_options = [o for o in route_options if o.process_family not in forbidden]
            removed = before - len(route_options)
            if removed:
                warnings.append(
                    f"Removed {removed} option(s) matching forbidden process list."
                )

        selected = route_options[0] if route_options else None

        return RoutingResult(
            intent=intent,
            options=route_options,
            selected=selected,
            warnings=warnings,
        )

    def route_multi_step(
        self,
        intent: ManufacturingIntent,
        required_steps: List[ProcessFamily],
    ) -> List[RoutingResult]:
        """
        Route a multi-step manufacturing process. Returns one RoutingResult
        per required step. Each step is routed independently; inter-step
        constraints (machine proximity, material hand-off) are not yet modelled.

        Args:
            intent:         The original intent (shared across all steps).
            required_steps: Ordered list of process families to route.

        Returns:
            List[RoutingResult] in the same order as required_steps.
        """
        results: List[RoutingResult] = []
        for step_family in required_steps:
            # Temporarily override intent to require only this step
            step_intent = intent.model_copy(
                update={"required_processes": [step_family]}
            )
            results.append(self.route(step_intent))
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gather_candidates(
        self, intent: ManufacturingIntent, warnings: List[str]
    ) -> List[tuple[ProcessFamily, MachineCapability]]:
        """
        Build the list of (process_family, machine) pairs to evaluate.

        Priority:
          1. If intent.required_processes is set, only those families are considered.
          2. If intent.preferred_processes is set, those are added first.
          3. Fall back to all registered processes.
        """
        if intent.required_processes:
            families = list(intent.required_processes)
        elif intent.preferred_processes:
            preferred = list(intent.preferred_processes)
            all_registered = self.registry.list_supported_processes()
            rest = [p for p in all_registered if p not in preferred]
            families = preferred + rest
        else:
            families = self.registry.list_supported_processes()

        candidates: List[tuple[ProcessFamily, MachineCapability]] = []
        material_name = intent.material.normalized_name

        for family in families:
            machines = self.registry.find_capable_machines(family, material_name)
            if not machines:
                # Try without material filter (adapter will validate)
                machines = self.registry.find_capable_machines_any_material(family)
                if machines:
                    warnings.append(
                        f"{family.value}: no machines registered for material "
                        f"'{material_name}'; falling back to all {family.value} machines."
                    )
            for machine in machines:
                candidates.append((family, machine))

        return candidates

    def _score_and_rank(
        self, raw: List[Dict[str, Any]], intent: ManufacturingIntent
    ) -> List[RouteOption]:
        """
        Normalise raw estimates and compute composite scores.
        Returns RouteOption list sorted best-first.
        """
        if not raw:
            return []

        # Normalisation bounds
        costs = [r["cost"] for r in raw]
        times = [r["cycle_time"] for r in raw]
        energies = [r["energy_kw"] for r in raw]

        min_cost = min(costs) or 1e-9
        max_cost = max(costs) or 1e-9
        min_time = min(times) or 1e-9
        max_time = max(times) or 1e-9
        min_energy = min(energies) or 1e-9
        max_energy = max(energies) or 1e-9

        options: List[RouteOption] = []
        for r in raw:
            score, reasoning = self._score_option(
                r, intent,
                min_cost, max_cost,
                min_time, max_time,
                min_energy, max_energy,
            )
            options.append(
                RouteOption(
                    process_family=r["process_family"],
                    machine=r["machine"],
                    estimated_cycle_time_minutes=r["cycle_time"],
                    estimated_cost_usd=r["cost"],
                    setup_time_minutes=r["setup_time"],
                    score=round(score, 4),
                    reasoning=reasoning,
                )
            )

        options.sort(key=lambda o: o.score, reverse=True)

        # --- LLM agent advisory pass ---
        # Ask the manufacturing agent to review scores and adjust ranking
        try:
            from manufacturing.agent import advise_routing
            intent_data = {
                "part_id": intent.part_id,
                "material": {
                    "material_name": intent.material.material_name,
                    "material_family": intent.material.material_family,
                },
                "quantity": intent.quantity,
                "tolerance_class": intent.tolerance_class,
                "priority": intent.priority,
                "cost_target_usd": intent.cost_target_usd,
            }
            candidates_data = [
                {
                    "index": i,
                    "process": o.process_family.value,
                    "machine": o.machine.machine_id,
                    "score": o.score,
                    "cycle_time_min": o.estimated_cycle_time_minutes,
                    "cost_usd": o.estimated_cost_usd,
                    "reasoning": o.reasoning,
                }
                for i, o in enumerate(options[:5])  # top 5 only
            ]
            advice = advise_routing(
                json.dumps(intent_data),
                json.dumps(candidates_data),
            )
            if advice and "recommended_option_index" in advice:
                rec_idx = advice["recommended_option_index"]
                if 0 <= rec_idx < len(options):
                    # Boost recommended option's score
                    rec = options[rec_idx]
                    rec_reasoning = advice.get("rationale", "")
                    boosted = RouteOption(
                        process_family=rec.process_family,
                        machine=rec.machine,
                        estimated_cycle_time_minutes=rec.estimated_cycle_time_minutes,
                        estimated_cost_usd=rec.estimated_cost_usd,
                        setup_time_minutes=rec.setup_time_minutes,
                        score=min(1.0, rec.score + 0.05),
                        reasoning=f"[AI] {rec_reasoning} | {rec.reasoning}",
                    )
                    options[rec_idx] = boosted
                    options.sort(key=lambda o: o.score, reverse=True)
                    logger.info(
                        "LLM routing advisor recommended option %d: %s",
                        rec_idx, rec_reasoning[:80],
                    )
                # Attach warnings from agent
                if advice.get("warnings"):
                    for w in advice["warnings"]:
                        logger.info("LLM routing warning: %s", w)
        except Exception as exc:
            logger.debug("LLM routing advisory skipped: %s", exc)

        return options

    def _score_option(
        self,
        raw: Dict[str, Any],
        intent: ManufacturingIntent,
        min_cost: float,
        max_cost: float,
        min_time: float,
        max_time: float,
        min_energy: float,
        max_energy: float,
    ) -> tuple[float, str]:
        """
        Compute a composite fitness score in [0, 1] for a single option.

        Returns:
            (score, reasoning_string)
        """
        reasons: List[str] = []

        # --- Cost score ---
        cost = raw["cost"]
        cost_range = max_cost - min_cost
        if cost_range > 0:
            cost_score = 1.0 - (cost - min_cost) / cost_range
        else:
            cost_score = 1.0

        # Hard penalty if over budget
        if intent.cost_target_usd is not None and cost > intent.cost_target_usd:
            cost_score *= 0.5
            reasons.append(f"over budget (${cost:.0f} > ${intent.cost_target_usd:.0f})")
        reasons.append(f"cost score {cost_score:.2f}")

        # --- Time score ---
        cycle = raw["cycle_time"]
        time_range = max_time - min_time
        if time_range > 0:
            time_score = 1.0 - (cycle - min_time) / time_range
        else:
            time_score = 1.0
        reasons.append(f"time score {time_score:.2f}")

        # --- Quality score ---
        # Check if process tolerance meets the tightest required tolerance class
        quality_score = self._quality_score(raw["process_family"], raw["machine"], intent)
        reasons.append(f"quality score {quality_score:.2f}")

        # --- Energy score ---
        energy = raw["energy_kw"]
        energy_range = max_energy - min_energy
        if energy_range > 0:
            energy_score = 1.0 - (energy - min_energy) / energy_range
        else:
            energy_score = 1.0
        reasons.append(f"energy score {energy_score:.2f}")

        composite = (
            self.weights["cost"] * cost_score
            + self.weights["time"] * time_score
            + self.weights["quality"] * quality_score
            + self.weights["energy"] * energy_score
        )

        reasoning = (
            f"{raw['process_family'].value} on {raw['machine'].machine_id}: "
            + ", ".join(reasons)
            + f" → composite {composite:.3f}"
        )
        return composite, reasoning

    def _quality_score(
        self,
        process_family: ProcessFamily,
        machine: MachineCapability,
        intent: ManufacturingIntent,
    ) -> float:
        """
        Return a quality score in [0, 1] based on how well the process's
        achievable tolerance aligns with the intent's requirements.
        """
        cap = machine.get_capability(process_family)
        if cap is None:
            return 0.5  # unknown = neutral

        # Check if required tolerance class matches process capability
        if not intent.quality_requirements:
            return 0.8  # no requirements = high score (not penalised)

        process_tol_mm = cap.tolerances.get("position_mm", 0.1)

        # Check each quality requirement
        scores: List[float] = []
        for qr in intent.quality_requirements:
            req_rank = TOLERANCE_CLASS_RANK.get(qr.tolerance_class, 2)
            # Tight tolerance = rank 0. Translate to a process achievability check.
            # Fine (rank 0) → needs process_tol_mm ≤ 0.05
            # Medium (rank 1) → needs ≤ 0.1
            # Coarse (rank 2) → needs ≤ 0.5
            required_tol = [0.05, 0.10, 0.50, 1.0][min(req_rank, 3)]
            if process_tol_mm <= required_tol:
                scores.append(1.0)
            elif process_tol_mm <= required_tol * 2:
                scores.append(0.6)
            else:
                scores.append(0.2)

        return sum(scores) / len(scores) if scores else 0.5

    def _check_material_compatibility(
        self, process_family: ProcessFamily, material: str
    ) -> bool:
        """
        Check if any registered machine can handle the material for this process.
        """
        machines = self.registry.find_capable_machines(process_family, material)
        return len(machines) > 0

    def _check_dimension_compatibility(
        self,
        process_family: ProcessFamily,
        machine: MachineCapability,
        intent: ManufacturingIntent,
    ) -> bool:
        """
        Check if the part can physically fit in the machine's work envelope.
        Returns True if dimensions are unknown or if the machine has no envelope limits.
        """
        cap = machine.get_capability(process_family)
        if cap is None or cap.max_part_dimensions_mm is None:
            return True

        mat = intent.material
        part_dims: List[Optional[float]] = [mat.length_mm, mat.width_mm, mat.thickness_mm]
        known_dims = [d for d in part_dims if d is not None]

        if not known_dims:
            return True  # No geometry info — allow and let operator decide

        # Align known dims with envelope (largest dim to X, etc.)
        known_dims.sort(reverse=True)
        envelope = sorted(cap.max_part_dimensions_mm, reverse=True)

        return all(d <= e for d, e in zip(known_dims, envelope))

    @staticmethod
    def _normalise_weights(weights: Dict[str, float]) -> Dict[str, float]:
        """Ensure weights sum to 1.0, filling missing keys with zero."""
        keys = ["cost", "time", "quality", "energy"]
        filled = {k: weights.get(k, 0.0) for k in keys}
        total = sum(filled.values())
        if total <= 0:
            # Uniform fallback
            return {k: 0.25 for k in keys}
        return {k: v / total for k, v in filled.items()}
