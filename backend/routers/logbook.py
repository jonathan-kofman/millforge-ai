"""
Shop Floor Logbook router — create, search, and summarize shift log entries.

Prefix: /api/logbook
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from db_models import LogbookEntry, LogbookAISummary, AS9100AuditTrail, AS9100ComplianceStatus
from agents.logbook_agent import LogbookAgent
from auth.dependencies import get_current_user
from models.quality_models import (
    LogbookEntryCreate, LogbookEntryResponse, LogbookEntryUpdate,
    ShiftSummaryResponse,
)

logger = logging.getLogger("millforge.logbook_router")

router = APIRouter(prefix="/api/logbook", tags=["Shop Floor Logbook"])

_agent = LogbookAgent()

_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "logbook")
os.makedirs(_UPLOAD_DIR, exist_ok=True)


def _as9100_enabled(db: Session, user_id: int) -> bool:
    return db.query(AS9100ComplianceStatus).filter(
        AS9100ComplianceStatus.user_id == user_id
    ).first() is not None


def _record_audit_trail(db: Session, user_id: int, event_type: str,
                        source_table: str, source_id: int, description: str) -> None:
    if not _as9100_enabled(db, user_id):
        return
    trail = AS9100AuditTrail(
        user_id=user_id, event_type=event_type,
        source_table=source_table, source_id=source_id,
        description=description,
    )
    db.add(trail)
    db.commit()


@router.post("/entries", response_model=LogbookEntryResponse, status_code=201)
def create_entry(req: LogbookEntryCreate, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Create a new logbook entry."""
    result = _agent.create_entry(
        db,
        author_id=current_user.id,
        title=req.title,
        body=req.body,
        category=req.category.value,
        severity=req.severity.value if req.severity else None,
        machine_id=req.machine_id,
        job_id=req.job_id,
        shift_date=req.shift_date,
        tags=req.tags,
    )

    # AS9100 audit trail for issues
    if req.category.value == "issue":
        _record_audit_trail(
            db, user_id=result["author_id"],
            event_type="logbook_issue",
            source_table="logbook_entries",
            source_id=result["id"],
            description=f"Issue logged: {req.title}",
        )

    return LogbookEntryResponse(**result)


@router.get("/entries", response_model=list[LogbookEntryResponse])
def list_entries(
    machine_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    q: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List/search logbook entries."""
    results = _agent.search_entries(
        db, machine_id=machine_id, category=category,
        date_from=date_from, date_to=date_to, q=q,
        skip=skip, limit=limit,
    )
    return [LogbookEntryResponse(**r) for r in results]


@router.get("/entries/{entry_id}", response_model=LogbookEntryResponse)
def get_entry(entry_id: int, db: Session = Depends(get_db)):
    """Get a single logbook entry."""
    entry = db.query(LogbookEntry).filter(LogbookEntry.id == entry_id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")

    from db_models import User, Machine
    author = db.query(User).filter(User.id == entry.author_id).first()
    machine = db.query(Machine).filter(Machine.id == entry.machine_id).first() if entry.machine_id else None

    return LogbookEntryResponse(
        id=entry.id,
        author_id=entry.author_id,
        author_name=author.name if author else None,
        machine_id=entry.machine_id,
        machine_name=machine.name if machine else None,
        job_id=entry.job_id,
        shift_date=entry.shift_date.isoformat(),
        category=entry.category,
        severity=entry.severity,
        title=entry.title,
        body=entry.body,
        photos=entry.photos,
        tags=entry.tags,
        created_at=entry.created_at.isoformat(),
    )


@router.put("/entries/{entry_id}", response_model=LogbookEntryResponse)
def update_entry(entry_id: int, req: LogbookEntryUpdate, db: Session = Depends(get_db)):
    """Update a logbook entry."""
    entry = db.query(LogbookEntry).filter(LogbookEntry.id == entry_id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")

    if req.title is not None:
        entry.title = req.title
    if req.body is not None:
        entry.body = req.body
    if req.category is not None:
        entry.category = req.category.value
    if req.severity is not None:
        entry.severity = req.severity.value
    if req.tags is not None:
        entry.tags_json = json.dumps(req.tags)
    db.commit()
    db.refresh(entry)

    return LogbookEntryResponse(
        id=entry.id, author_id=entry.author_id,
        shift_date=entry.shift_date.isoformat(),
        category=entry.category, severity=entry.severity,
        title=entry.title, body=entry.body,
        photos=entry.photos, tags=entry.tags,
        created_at=entry.created_at.isoformat(),
    )


@router.post("/entries/{entry_id}/photo")
async def upload_photo(entry_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a photo attachment to a logbook entry."""
    entry = db.query(LogbookEntry).filter(LogbookEntry.id == entry_id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")

    contents = await file.read()
    filename = f"{entry_id}_{file.filename}"
    filepath = os.path.join(_UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(contents)

    photos = entry.photos
    photos.append(filename)
    entry.photos_json = json.dumps(photos)
    db.commit()

    return {"status": "uploaded", "filename": filename}


@router.get("/summary", response_model=ShiftSummaryResponse)
def get_shift_summary(
    shift_date: datetime = Query(...),
    shift_number: int = Query(1, ge=1, le=3),
    db: Session = Depends(get_db),
):
    """Get AI-generated shift summary. Returns cached if available."""
    existing = db.query(LogbookAISummary).filter(
        LogbookAISummary.shift_date == shift_date,
        LogbookAISummary.shift_number == shift_number,
    ).first()
    if existing:
        metadata = json.loads(existing.metadata_json)
        return ShiftSummaryResponse(
            shift_date=existing.shift_date.isoformat(),
            shift_number=existing.shift_number,
            summary_text=existing.summary_text,
            entries_count=metadata.get("entries_count", 0),
            generated_at=existing.generated_at.isoformat(),
        )
    raise HTTPException(status_code=404, detail="No summary for this shift. Use POST /summary/generate.")


@router.post("/summary/generate", response_model=ShiftSummaryResponse)
def generate_shift_summary(
    shift_date: datetime = Query(...),
    shift_number: int = Query(1, ge=1, le=3),
    db: Session = Depends(get_db),
):
    """Force-generate an AI summary for a shift."""
    result = _agent.generate_shift_summary(db, shift_date, shift_number)
    return ShiftSummaryResponse(**result)
