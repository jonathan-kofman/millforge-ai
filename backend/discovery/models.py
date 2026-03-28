"""SQLAlchemy ORM models for the customer discovery module."""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Interview(Base):
    __tablename__ = "discovery_interviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 1-5 | 6-20 | 21-100 | 100+
    shop_size: Mapped[str] = mapped_column(String(20), nullable=False)
    # owner | ops_manager | estimator | machinist | other
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    date: Mapped[str] = mapped_column(String(20), nullable=False)  # YYYY-MM-DD
    raw_transcript: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    insights: Mapped[List["Insight"]] = relationship(
        "Insight", back_populates="interview", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Interview id={self.id} shop={self.shop_name}>"


class Insight(Base):
    __tablename__ = "discovery_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    interview_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("discovery_interviews.id"), nullable=False, index=True
    )
    # pain_point | current_tool | wtp_signal | workflow | quote
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 1 = mild, 2 = moderate, 3 = critical
    severity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    interview: Mapped["Interview"] = relationship("Interview", back_populates="insights")

    def __repr__(self) -> str:
        return f"<Insight id={self.id} category={self.category} severity={self.severity}>"


class DiscoveryPattern(Base):
    __tablename__ = "discovery_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    # JSON array of Insight IDs
    insight_ids: Mapped[list] = mapped_column(JSON, default=list)
    frequency: Mapped[float] = mapped_column(Float, nullable=False)
    # JSON array of quote strings
    evidence_quotes: Mapped[list] = mapped_column(JSON, default=list)
    # scheduling | quoting | supplier | defect_detection | energy | onboarding | other
    feature_tag: Mapped[str] = mapped_column(String(50), nullable=False, default="other")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def __repr__(self) -> str:
        return f"<DiscoveryPattern id={self.id} label={self.label} freq={self.frequency}>"
