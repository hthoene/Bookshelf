"""Reading statistics from KOReader's ``statistics.sqlite3``, synced to Bookshelf via WebDAV.

KOReader owns the file: it downloads it, merges its local data and uploads it again. Bookshelf
only ever opens it read-only. Books are identified by ``book.md5``, which is the same partial
MD5 that Bookshelf stores as ``Book.partial_md5``.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from ..storage import Storage

log = logging.getLogger(__name__)

STATISTICS_FILE = "statistics.sqlite3"
CALENDAR_WEEKS = 53
RECENT_BOOKS_LIMIT = 12
_LEVEL_MINUTES = (15, 30, 60)  # thresholds for calendar intensity levels 2, 3 and 4


@dataclass(frozen=True)
class StatsBook:
    title: str
    authors: str | None
    md5: str | None
    seconds: int
    pages_read: int
    total_pages: int | None
    last_read: datetime  # naive UTC, like other datetimes in Bookshelf

    def seconds_left(self, fraction_read: float | None = None) -> int | None:
        """Estimated reading time left, based on this book's average time per page."""
        if not self.total_pages or self.pages_read <= 0:
            return None
        if fraction_read is None:
            fraction_read = min(self.pages_read / self.total_pages, 1.0)
        remaining_pages = max(self.total_pages * (1 - fraction_read), 0)
        return round(self.seconds / self.pages_read * remaining_pages)


@dataclass(frozen=True)
class CalendarDay:
    day: date
    seconds: int

    @property
    def level(self) -> int:
        """0 (nothing read) to 4 (an hour or more)."""
        if self.seconds <= 0:
            return 0
        minutes = self.seconds / 60
        return 1 + sum(minutes >= limit for limit in _LEVEL_MINUTES)


@dataclass(frozen=True)
class CalendarWeek:
    label: str  # month abbreviation on the first week of each month, else ""
    days: tuple[CalendarDay | None, ...]  # Monday … Sunday; None for future days


@dataclass(frozen=True)
class ReadingStats:
    total_seconds: int
    year_seconds: int
    week_seconds: int
    pages_read: int
    days_read: int
    streak_days: int
    calendar: tuple[CalendarWeek, ...]
    books: tuple[StatsBook, ...]


def statistics_path(storage: Storage, user_id: int) -> Path:
    return storage.user_files_dir(user_id) / STATISTICS_FILE


def last_synced(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).replace(tzinfo=None)
    except FileNotFoundError:
        return None


def load_stats(path: Path, tz: ZoneInfo, today: date | None = None) -> ReadingStats | None:
    """Overall statistics, or None if no (readable) statistics file has been synced yet."""
    if not path.is_file():
        return None
    stat = path.stat()
    today = today or datetime.now(tz).date()
    return _load_stats(str(path), stat.st_mtime_ns, stat.st_size, tz.key, today)


def book_stats(path: Path, md5: str) -> StatsBook | None:
    """Statistics for one book, matched by KOReader's partial MD5."""
    if not path.is_file():
        return None
    stat = path.stat()
    return _book_stats(str(path), stat.st_mtime_ns, stat.st_size, md5)


# The cache keys include mtime and size, so a newly synced file is picked up immediately.


@lru_cache(maxsize=32)
def _load_stats(
    path: str, _mtime_ns: int, _size: int, tz_key: str, today: date
) -> ReadingStats | None:
    tz = ZoneInfo(tz_key)
    try:
        with closing(_connect(Path(path))) as conn:
            days: dict[date, int] = defaultdict(int)
            # Aggregate per hour in SQL, then map hours to local days (handles DST correctly).
            for hour, seconds in conn.execute(
                "SELECT start_time / 3600, SUM(duration) FROM page_stat_data GROUP BY 1"
            ):
                days[datetime.fromtimestamp(hour * 3600, tz).date()] += seconds or 0
            pages_read = conn.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT id_book, page FROM page_stat_data)"
            ).fetchone()[0]
            books = tuple(
                _stats_book(row)
                for row in conn.execute(
                    f"""SELECT b.title, b.authors, b.md5, b.pages, SUM(p.duration),
                               COUNT(DISTINCT p.page), MAX(p.start_time + p.duration)
                        FROM book b JOIN page_stat_data p ON p.id_book = b.id
                        GROUP BY b.id ORDER BY 7 DESC LIMIT {RECENT_BOOKS_LIMIT}"""
                )
            )
    except sqlite3.Error:
        log.warning("Could not read statistics file %s", path, exc_info=True)
        return None

    week_start = today - timedelta(days=today.weekday())
    return ReadingStats(
        total_seconds=sum(days.values()),
        year_seconds=sum(s for d, s in days.items() if d.year == today.year and d <= today),
        week_seconds=sum(s for d, s in days.items() if week_start <= d <= today),
        pages_read=pages_read,
        days_read=sum(1 for s in days.values() if s > 0),
        streak_days=_streak(days, today),
        calendar=build_calendar(days, today),
        books=books,
    )


@lru_cache(maxsize=256)
def _book_stats(path: str, _mtime_ns: int, _size: int, md5: str) -> StatsBook | None:
    try:
        with closing(_connect(Path(path))) as conn:
            row = conn.execute(
                """SELECT MAX(b.title), MAX(b.authors), b.md5, MAX(b.pages), SUM(p.duration),
                          COUNT(DISTINCT p.id_book || ':' || p.page), MAX(p.start_time + p.duration)
                   FROM book b JOIN page_stat_data p ON p.id_book = b.id
                   WHERE b.md5 = ?""",
                (md5,),
            ).fetchone()
    except sqlite3.Error:
        log.warning("Could not read statistics file %s", path, exc_info=True)
        return None
    return _stats_book(row) if row and row[4] else None


def _connect(path: Path) -> sqlite3.Connection:
    # Read-only and "immutable": never create journals or locks next to KOReader's file.
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA trusted_schema = OFF")
    return conn


def _stats_book(row: tuple) -> StatsBook:
    title, authors, md5, total_pages, seconds, pages_read, last_read = row
    return StatsBook(
        title=title or "Untitled",
        authors=authors or None,
        md5=md5,
        seconds=int(seconds or 0),
        pages_read=int(pages_read or 0),
        total_pages=int(total_pages) if total_pages else None,
        last_read=datetime.fromtimestamp(last_read or 0, UTC).replace(tzinfo=None),
    )


def _streak(days: dict[date, int], today: date) -> int:
    """Consecutive reading days up to today (or yesterday, if nothing was read yet today)."""
    day = today if days.get(today, 0) > 0 else today - timedelta(days=1)
    streak = 0
    while days.get(day, 0) > 0:
        streak += 1
        day -= timedelta(days=1)
    return streak


def build_calendar(
    days: dict[date, int], today: date, weeks: int = CALENDAR_WEEKS
) -> tuple[CalendarWeek, ...]:
    """Weeks (Monday first) ending with the current one, for a GitHub-style heatmap."""
    first_monday = today - timedelta(days=today.weekday(), weeks=weeks - 1)
    result = []
    previous_month = None
    for week in range(weeks):
        monday = first_monday + timedelta(weeks=week)
        cells = tuple(
            CalendarDay(day, days.get(day, 0)) if day <= today else None
            for day in (monday + timedelta(days=offset) for offset in range(7))
        )
        label = monday.strftime("%b") if monday.month != previous_month else ""
        previous_month = monday.month
        result.append(CalendarWeek(label, cells))
    return tuple(result)
