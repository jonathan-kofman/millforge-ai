"""FastAPI router for the customer discovery module.

Prefix: /api/discovery
All write endpoints require JWT auth (httpOnly cookie).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from auth.dependencies import get_current_user
from database import get_db
from discovery.models import DiscoveryPattern, Insight, Interview
from discovery import agent as discovery_agent

router = APIRouter(prefix="/api/discovery", tags=["Discovery"])


# ---------------------------------------------------------------------------
# Pydantic schemas (local — discovery-only, no need to pollute models/schemas.py)
# ---------------------------------------------------------------------------

class InterviewCreate(BaseModel):
    contact_name: str
    shop_name: str
    shop_size: str   # 1-5 | 6-20 | 21-100 | 100+
    role: str        # owner | ops_manager | estimator | machinist | other
    date: str        # YYYY-MM-DD
    raw_transcript: str


class InsightOut(BaseModel):
    id: int
    category: str
    content: str
    severity: int
    quote: Optional[str]

    class Config:
        from_attributes = True


class InterviewOut(BaseModel):
    id: int
    contact_name: str
    shop_name: str
    shop_size: str
    role: str
    date: str
    created_at: str
    insight_count: int

    class Config:
        from_attributes = True


class InterviewDetail(BaseModel):
    id: int
    contact_name: str
    shop_name: str
    shop_size: str
    role: str
    date: str
    raw_transcript: str
    created_at: str
    insights: list[InsightOut]

    class Config:
        from_attributes = True


class PatternOut(BaseModel):
    id: int
    label: str
    insight_ids: list
    frequency: float
    evidence_quotes: list
    feature_tag: str
    created_at: str

    class Config:
        from_attributes = True


class NextQuestion(BaseModel):
    question: str
    rationale: str
    follow_up: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _interview_to_out(iv: Interview) -> dict:
    return {
        "id": iv.id,
        "contact_name": iv.contact_name,
        "shop_name": iv.shop_name,
        "shop_size": iv.shop_size,
        "role": iv.role,
        "date": iv.date,
        "created_at": iv.created_at.isoformat(),
        "insight_count": len(iv.insights),
    }


def _insight_to_out(ins: Insight) -> dict:
    return {
        "id": ins.id,
        "category": ins.category,
        "content": ins.content,
        "severity": ins.severity,
        "quote": ins.quote,
    }


def _pattern_to_out(p: DiscoveryPattern) -> dict:
    return {
        "id": p.id,
        "label": p.label,
        "insight_ids": p.insight_ids or [],
        "frequency": p.frequency,
        "evidence_quotes": p.evidence_quotes or [],
        "feature_tag": p.feature_tag,
        "created_at": p.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/interviews")
def create_interview(
    body: InterviewCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Log a new interview, extract insights via Claude, persist both."""
    iv = Interview(
        contact_name=body.contact_name,
        shop_name=body.shop_name,
        shop_size=body.shop_size,
        role=body.role,
        date=body.date,
        raw_transcript=body.raw_transcript,
    )
    db.add(iv)
    db.flush()  # get iv.id before commit

    raw_insights = discovery_agent.extract_insights(
        body.raw_transcript,
        {"shop_name": body.shop_name, "role": body.role, "shop_size": body.shop_size},
    )

    insight_records = []
    for ri in raw_insights:
        ins = Insight(
            interview_id=iv.id,
            category=ri.get("category", "pain_point"),
            content=ri.get("content", ""),
            severity=int(ri.get("severity", 1)),
            quote=ri.get("quote"),
        )
        db.add(ins)
        insight_records.append(ins)

    db.commit()
    db.refresh(iv)

    return {
        "interview": _interview_to_out(iv),
        "insights": [_insight_to_out(i) for i in iv.insights],
    }


@router.get("/interviews")
def list_interviews(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all interviews with insight counts."""
    interviews = db.query(Interview).order_by(Interview.created_at.desc()).all()
    return [_interview_to_out(iv) for iv in interviews]


@router.get("/interviews/{interview_id}")
def get_interview(
    interview_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Full interview with all extracted insights."""
    iv = db.query(Interview).filter(Interview.id == interview_id).first()
    if not iv:
        raise HTTPException(status_code=404, detail="Interview not found")
    return {
        "id": iv.id,
        "contact_name": iv.contact_name,
        "shop_name": iv.shop_name,
        "shop_size": iv.shop_size,
        "role": iv.role,
        "date": iv.date,
        "raw_transcript": iv.raw_transcript,
        "created_at": iv.created_at.isoformat(),
        "insights": [_insight_to_out(i) for i in iv.insights],
    }


@router.delete("/interviews/{interview_id}", status_code=204)
def delete_interview(
    interview_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete an interview and all its insights (cascade)."""
    iv = db.query(Interview).filter(Interview.id == interview_id).first()
    if not iv:
        raise HTTPException(status_code=404, detail="Interview not found")
    db.delete(iv)
    db.commit()


@router.post("/synthesize")
def synthesize(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Run pattern synthesis across all insights, persist results, return patterns."""
    all_insights = db.query(Insight).all()
    interview_count = db.query(Interview).count()

    if not all_insights:
        return {"patterns": [], "interviews_analyzed": 0, "insights_analyzed": 0}

    insights_payload = [
        {
            "id": i.id,
            "interview_id": i.interview_id,
            "category": i.category,
            "content": i.content,
            "severity": i.severity,
            "quote": i.quote,
        }
        for i in all_insights
    ]

    raw_patterns = discovery_agent.synthesize_patterns(insights_payload, interview_count)

    # Clear old patterns and replace with fresh synthesis
    db.query(DiscoveryPattern).delete()
    pattern_records = []
    for rp in raw_patterns:
        p = DiscoveryPattern(
            label=rp.get("label", "Unnamed pattern"),
            insight_ids=rp.get("insight_ids", []),
            frequency=float(rp.get("frequency", 0.0)),
            evidence_quotes=rp.get("evidence_quotes", []),
            feature_tag=rp.get("feature_tag", "other"),
        )
        db.add(p)
        pattern_records.append(p)

    db.commit()
    for p in pattern_records:
        db.refresh(p)

    return {
        "patterns": [_pattern_to_out(p) for p in pattern_records],
        "interviews_analyzed": interview_count,
        "insights_analyzed": len(all_insights),
    }


@router.get("/patterns")
def get_patterns(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all patterns ordered by frequency descending."""
    patterns = (
        db.query(DiscoveryPattern)
        .order_by(DiscoveryPattern.frequency.desc())
        .all()
    )
    return [_pattern_to_out(p) for p in patterns]


@router.get("/next-questions")
def next_questions(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate 5 targeted interview questions based on current pattern gaps."""
    interview_count = db.query(Interview).count()
    patterns = (
        db.query(DiscoveryPattern)
        .order_by(DiscoveryPattern.frequency.desc())
        .all()
    )
    patterns_payload = [
        {
            "label": p.label,
            "frequency": p.frequency,
            "feature_tag": p.feature_tag,
            "evidence_quotes": p.evidence_quotes or [],
        }
        for p in patterns
    ]
    questions = discovery_agent.generate_next_questions(patterns_payload, interview_count)
    return {
        "questions": questions,
        "interviews_analyzed": interview_count,
    }
