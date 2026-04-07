"""
Shop Floor Logbook Agent — Digital shift notes with AI summaries.

Handles creation of logbook entries, photo attachment management,
machine auto-tagging from free text, and AI-generated shift summaries
via Ollama LLM.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("millforge.logbook")


class LogbookAgent:
    """Shop floor logbook with AI shift summary generation."""

    def __init__(self) -> None:
        pass

    def create_entry(self, db: Session, *, author_id: int, title: str, body: str,
                     category: str, severity: Optional[str] = None,
                     machine_id: Optional[int] = None, job_id: Optional[int] = None,
                     shift_date: Optional[datetime] = None,
                     photos: Optional[list[str]] = None,
                     tags: Optional[list[str]] = None) -> dict:
        """Create a logbook entry. Auto-detects machine references in body text."""
        from db_models import LogbookEntry

        if shift_date is None:
            shift_date = datetime.now(timezone.utc).replace(tzinfo=None)

        # Auto-tag machine if not explicitly provided
        if machine_id is None:
            auto_ids = self.auto_tag_machines(body, db)
            if auto_ids:
                machine_id = auto_ids[0]

        entry = LogbookEntry(
            author_id=author_id,
            machine_id=machine_id,
            job_id=job_id,
            shift_date=shift_date,
            category=category,
            severity=severity,
            title=title,
            body=body,
            photos_json=json.dumps(photos or []),
            tags_json=json.dumps(tags or []),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)

        return {
            "id": entry.id,
            "author_id": entry.author_id,
            "machine_id": entry.machine_id,
            "job_id": entry.job_id,
            "shift_date": entry.shift_date.isoformat(),
            "category": entry.category,
            "severity": entry.severity,
            "title": entry.title,
            "body": entry.body,
            "photos": entry.photos,
            "tags": entry.tags,
            "created_at": entry.created_at.isoformat(),
        }

    def generate_shift_summary(self, db: Session, shift_date: datetime,
                               shift_number: int) -> dict:
        """Generate AI summary of all entries for a given shift.

        Shift numbers: 1 = day (06:00-14:00), 2 = swing (14:00-22:00), 3 = night (22:00-06:00)
        """
        from db_models import LogbookEntry, LogbookAISummary, Machine

        # Query entries for this shift date
        entries = db.query(LogbookEntry).filter(
            LogbookEntry.shift_date >= shift_date.replace(hour=0, minute=0, second=0),
            LogbookEntry.shift_date < shift_date.replace(hour=23, minute=59, second=59),
        ).all()

        if not entries:
            return {
                "shift_date": shift_date.isoformat(),
                "shift_number": shift_number,
                "summary_text": "No entries logged for this shift.",
                "entries_count": 0,
                "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            }

        # Build entry dicts with machine names
        entry_dicts = []
        for e in entries:
            machine_name = None
            if e.machine_id:
                machine = db.query(Machine).filter(Machine.id == e.machine_id).first()
                machine_name = machine.name if machine else f"Machine #{e.machine_id}"
            entry_dicts.append({
                "category": e.category,
                "severity": e.severity,
                "title": e.title,
                "body": e.body,
                "machine_name": machine_name or "N/A",
            })

        # Generate AI summary
        from services.llm_service import summarize_shift
        summary_text = summarize_shift(entry_dicts)

        # Persist summary
        summary = LogbookAISummary(
            shift_date=shift_date,
            shift_number=shift_number,
            summary_text=summary_text,
            metadata_json=json.dumps({
                "entries_count": len(entries),
                "issues_count": sum(1 for e in entries if e.category == "issue"),
                "machines_mentioned": list(set(
                    str(e.machine_id) for e in entries if e.machine_id
                )),
            }),
        )
        db.add(summary)
        db.commit()
        db.refresh(summary)

        return {
            "shift_date": shift_date.isoformat(),
            "shift_number": shift_number,
            "summary_text": summary_text,
            "entries_count": len(entries),
            "generated_at": summary.generated_at.isoformat(),
        }

    def search_entries(self, db: Session, *, machine_id: Optional[int] = None,
                       category: Optional[str] = None,
                       date_from: Optional[datetime] = None,
                       date_to: Optional[datetime] = None,
                       q: Optional[str] = None,
                       skip: int = 0, limit: int = 50) -> list[dict]:
        """Search and filter logbook entries."""
        from db_models import LogbookEntry, User, Machine

        query = db.query(LogbookEntry)
        if machine_id is not None:
            query = query.filter(LogbookEntry.machine_id == machine_id)
        if category:
            query = query.filter(LogbookEntry.category == category)
        if date_from:
            query = query.filter(LogbookEntry.shift_date >= date_from)
        if date_to:
            query = query.filter(LogbookEntry.shift_date <= date_to)
        if q:
            query = query.filter(
                LogbookEntry.title.ilike(f"%{q}%") |
                LogbookEntry.body.ilike(f"%{q}%")
            )

        query = query.order_by(LogbookEntry.created_at.desc())
        entries = query.offset(skip).limit(limit).all()

        results = []
        for e in entries:
            author = db.query(User).filter(User.id == e.author_id).first()
            machine = None
            if e.machine_id:
                machine = db.query(Machine).filter(Machine.id == e.machine_id).first()
            results.append({
                "id": e.id,
                "author_id": e.author_id,
                "author_name": author.name if author else None,
                "machine_id": e.machine_id,
                "machine_name": machine.name if machine else None,
                "job_id": e.job_id,
                "shift_date": e.shift_date.isoformat(),
                "category": e.category,
                "severity": e.severity,
                "title": e.title,
                "body": e.body,
                "photos": e.photos,
                "tags": e.tags,
                "created_at": e.created_at.isoformat(),
            })
        return results

    def auto_tag_machines(self, body: str, db: Session) -> list[int]:
        """Extract machine references from free text, return machine IDs."""
        from db_models import Machine

        machines = db.query(Machine).all()
        matched_ids = []
        body_lower = body.lower()

        for machine in machines:
            # Match by name
            if machine.name.lower() in body_lower:
                matched_ids.append(machine.id)
                continue
            # Match by "machine #N" or "machine N" patterns
            pattern = rf"machine\s*#?\s*{machine.id}\b"
            if re.search(pattern, body_lower):
                matched_ids.append(machine.id)

        return matched_ids
