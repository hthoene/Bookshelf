"""Reading progress records as stored by the KOReader sync protocol."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ReadingProgress


def get_progress(db: Session, user_id: int, document: str) -> ReadingProgress | None:
    return db.get(ReadingProgress, (user_id, document))


def progress_by_document(db: Session, user_id: int) -> dict[str, ReadingProgress]:
    records = db.scalars(select(ReadingProgress).where(ReadingProgress.user_id == user_id))
    return {record.document: record for record in records}


def save_progress(
    db: Session,
    user_id: int,
    document: str,
    *,
    progress: str,
    percentage: float,
    device: str,
    device_id: str,
) -> ReadingProgress:
    record = get_progress(db, user_id, document)
    if record is None:
        record = ReadingProgress(user_id=user_id, document=document)
        db.add(record)
    record.progress = progress
    record.percentage = min(max(percentage, 0.0), 1.0)
    record.device = device[:200]
    record.device_id = device_id[:200]
    record.timestamp = int(time.time())
    db.commit()
    return record
