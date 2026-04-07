"""
Tool Wear Monitoring — REST endpoints.

Prefix: /api/toolwear

Endpoints:
  POST   /api/toolwear/tools              register a tool
  GET    /api/toolwear/tools              list all tools (fleet status)
  GET    /api/toolwear/tools/{tool_id}    single tool status
  POST   /api/toolwear/readings           ingest a sensor reading
  GET    /api/toolwear/readings/{tool_id} recent readings for a tool
  POST   /api/toolwear/recommend          change recommendation for a job
  POST   /api/toolwear/reset/{tool_id}    reset after physical tool change
  POST   /api/toolwear/simulate/{tool_id} inject synthetic wear for demo
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agents.tool_wear_agent import ToolWearAgent
from database import get_db
from db_models import ToolRecord, SensorReading
from models.tool_models import (
    SimulateResponse,
    SpectralReading,
    ToolChangeRecommendation,
    ToolRegisterRequest,
    ToolStatus,
    WearReading,
)

router = APIRouter(prefix="/api/toolwear", tags=["Tool Wear"])

# Module-level singleton — shared across requests
_agent = ToolWearAgent()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_tools_from_db(db: Session) -> None:
    """Restore in-memory agent state from DB on startup."""
    records = db.query(ToolRecord).all()
    for rec in records:
        if _agent.get_tool(rec.tool_id) is None:
            _agent.register_tool(
                tool_id=rec.tool_id,
                machine_id=rec.machine_id,
                tool_type=rec.tool_type,
                material=rec.material,
                expected_life_minutes=rec.expected_life_minutes,
            )
            # Re-ingest stored readings to rebuild wear state
            readings = (
                db.query(SensorReading)
                .filter(SensorReading.tool_id == rec.tool_id)
                .order_by(SensorReading.recorded_at)
                .all()
            )
            for r in readings:
                _agent.ingest_reading(rec.tool_id, r.features, r.recorded_at)


def _sync_tool_record(db: Session, tool_id: str) -> None:
    """Update ToolRecord with latest agent state."""
    status = _agent.tool_status(tool_id)
    if status is None:
        return
    rec = db.query(ToolRecord).filter(ToolRecord.tool_id == tool_id).first()
    if rec is None:
        return
    rec.wear_score = status["wear_score"]
    rec.alert_level = status["alert_level"]
    rec.rul_minutes = status["rul_minutes"]
    db.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/tools", response_model=ToolStatus, status_code=201)
def register_tool(req: ToolRegisterRequest, db: Session = Depends(get_db)):
    """Register a new tool. Idempotent — returns existing state if already registered."""
    existing = db.query(ToolRecord).filter(ToolRecord.tool_id == req.tool_id).first()
    if existing is None:
        rec = ToolRecord(
            tool_id=req.tool_id,
            machine_id=req.machine_id,
            tool_type=req.tool_type,
            material=req.material,
            expected_life_minutes=req.expected_life_minutes,
        )
        db.add(rec)
        db.commit()

    _agent.register_tool(
        tool_id=req.tool_id,
        machine_id=req.machine_id,
        tool_type=req.tool_type,
        material=req.material,
        expected_life_minutes=req.expected_life_minutes,
    )
    status = _agent.tool_status(req.tool_id)
    return ToolStatus(**status)


@router.get("/tools", response_model=List[ToolStatus])
def list_tools(db: Session = Depends(get_db)):
    """Fleet status — all registered tools."""
    _load_tools_from_db(db)
    return [ToolStatus(**s) for s in _agent.fleet_status()]


@router.get("/tools/{tool_id}", response_model=ToolStatus)
def get_tool(tool_id: str, db: Session = Depends(get_db)):
    """Status for a single tool."""
    _load_tools_from_db(db)
    status = _agent.tool_status(tool_id)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not registered")
    return ToolStatus(**status)


@router.post("/readings", response_model=ToolStatus)
def ingest_reading(payload: WearReading, db: Session = Depends(get_db)):
    """Ingest one spectral sensor snapshot for a tool."""
    _load_tools_from_db(db)
    ts = payload.timestamp or _now()
    features = payload.reading.model_dump()
    score = _agent.ingest_reading(payload.tool_id, features, ts)
    if score is None:
        raise HTTPException(status_code=404, detail=f"Tool '{payload.tool_id}' not registered")

    # Persist reading
    db.add(SensorReading(
        tool_id=payload.tool_id,
        features=features,
        wear_score=score,
        recorded_at=ts,
    ))
    db.commit()
    _sync_tool_record(db, payload.tool_id)

    status = _agent.tool_status(payload.tool_id)
    return ToolStatus(**status)


@router.get("/readings/{tool_id}")
def get_readings(tool_id: str, limit: int = 50, db: Session = Depends(get_db)):
    """Recent sensor readings for a tool (newest first)."""
    readings = (
        db.query(SensorReading)
        .filter(SensorReading.tool_id == tool_id)
        .order_by(SensorReading.recorded_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "tool_id": r.tool_id,
            "wear_score": r.wear_score,
            "recorded_at": r.recorded_at.isoformat(),
        }
        for r in readings
    ]


@router.post("/recommend", response_model=ToolChangeRecommendation)
def change_recommendation(
    tool_id: str,
    job_duration_minutes: float,
    db: Session = Depends(get_db),
):
    """Should this tool be changed before a job of the given duration?"""
    _load_tools_from_db(db)
    rec = _agent.change_recommendation(tool_id, job_duration_minutes)
    if rec.get("reason") == "tool_not_found":
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not registered")
    return ToolChangeRecommendation(**rec)


@router.post("/reset/{tool_id}", response_model=ToolStatus)
def reset_tool(tool_id: str, db: Session = Depends(get_db)):
    """
    Reset a tool after a physical tool change.
    Clears wear history and restarts baseline learning.
    """
    if not _agent.reset_tool(tool_id):
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not registered")

    # Clear DB readings
    db.query(SensorReading).filter(SensorReading.tool_id == tool_id).delete()
    rec = db.query(ToolRecord).filter(ToolRecord.tool_id == tool_id).first()
    if rec:
        rec.wear_score = 0.0
        rec.alert_level = "GREEN"
        rec.rul_minutes = None
    db.commit()

    status = _agent.tool_status(tool_id)
    return ToolStatus(**status)


@router.post("/simulate/{tool_id}", response_model=SimulateResponse)
def simulate_wear(
    tool_id: str,
    steps: int = 30,
    db: Session = Depends(get_db),
):
    """
    Inject synthetic wear progression for demo purposes.
    Registers the tool if not already present.
    steps: number of sensor readings to simulate (10-100).
    """
    steps = max(10, min(100, steps))
    scores = _agent.simulate_wear_progression(tool_id, steps=steps)

    # Persist the resulting state
    state = _agent.get_tool(tool_id)
    if state is not None:
        # Upsert ToolRecord
        rec = db.query(ToolRecord).filter(ToolRecord.tool_id == tool_id).first()
        if rec is None:
            rec = ToolRecord(
                tool_id=tool_id,
                machine_id=state.machine_id,
                tool_type=state.tool_type,
                material=state.material,
            )
            db.add(rec)
        rec.wear_score = state.wear_score_ema
        rec.alert_level = state.alert_level
        rul, _ = state.rul_minutes()
        rec.rul_minutes = rul
        db.commit()

    status = _agent.tool_status(tool_id)
    return SimulateResponse(
        tool_id=tool_id,
        wear_scores=scores,
        final_wear_score=status["wear_score"] if status else scores[-1],
        final_alert_level=status["alert_level"] if status else "UNKNOWN",
        message=f"Simulated {steps} readings. Tool is now {status['alert_level'] if status else 'UNKNOWN'}.",
    )
