"""Lab session timing helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import LabSession


def utcnow() -> datetime:
    return datetime.utcnow()


def go_live(session: LabSession, *, duration_minutes: int | None = None) -> None:
    mins = duration_minutes if duration_minutes is not None else session.duration_minutes
    if not mins or mins < 1:
        mins = 60
    session.duration_minutes = mins
    now = utcnow()
    session.starts_at = now
    session.ends_at = now + timedelta(minutes=mins)
    session.status = "active"


def ensure_timer(session: LabSession) -> None:
    """If live but missing ends_at, start the clock from now using duration."""
    if session.status != "active":
        return
    if session.ends_at:
        return
    mins = session.duration_minutes if session.duration_minutes and session.duration_minutes > 0 else 60
    session.duration_minutes = mins
    now = utcnow()
    if not session.starts_at:
        session.starts_at = now
    session.ends_at = session.starts_at + timedelta(minutes=mins)


def end_lab(session: LabSession) -> None:
    session.status = "closed"
    if session.ends_at is None or session.ends_at > utcnow():
        session.ends_at = utcnow()


def set_upcoming(session: LabSession) -> None:
    session.status = "draft"
    session.starts_at = None
    session.ends_at = None


def expire_if_needed(session: LabSession, db: Session | None = None) -> bool:
    """If live session passed ends_at, mark closed. Returns True if expired now."""
    if session.status != "active" or not session.ends_at:
        return False
    if utcnow() < session.ends_at:
        return False
    end_lab(session)
    if db is not None:
        db.commit()
    return True


def ends_at_iso(session: LabSession) -> str | None:
    if not session.ends_at:
        return None
    return session.ends_at.isoformat() + "Z"
