import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import KST, settings
from .models import ChapterNote, ChapterProgress
from .proverbs import TOTAL_CHAPTERS, TOTAL_VERSES, VERSE_COUNTS


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst() -> date:
    return now_kst().date()


def to_kst(dt: datetime) -> datetime:
    # SQLite drops tzinfo; every stored timestamp is written in UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST)


@dataclass
class Period:
    start: date
    end: date
    today: date

    @property
    def total_days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def elapsed_days(self) -> int:
        return max(0, min(self.total_days, (self.today - self.start).days + 1))

    @property
    def remaining_days(self) -> int:
        return max(0, (self.end - self.today).days + 1) if self.today >= self.start else self.total_days

    @property
    def status(self) -> str:
        if self.today < self.start:
            return "before"
        if self.today > self.end:
            return "after"
        return "active"

    @property
    def d_day_label(self) -> str:
        if self.status == "before":
            return f"시작까지 D-{(self.start - self.today).days}"
        if self.status == "after":
            return "기간 종료"
        left = (self.end - self.today).days
        return "오늘 마감" if left == 0 else f"D-{left}"

    @property
    def expected_ratio(self) -> float:
        return self.elapsed_days / self.total_days

    @property
    def expected_chapters(self) -> int:
        return min(TOTAL_CHAPTERS, math.ceil(TOTAL_CHAPTERS * self.expected_ratio))

    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.total_days)]


def current_period() -> Period:
    return Period(settings.start_date, settings.end_date, today_kst())


@dataclass
class Badge:
    key: str
    title: str
    desc: str
    earned: bool


@dataclass
class MemberStats:
    member: str
    completed: dict[int, datetime]
    note_chapters: set[int] = field(default_factory=set)

    @property
    def count(self) -> int:
        return len(self.completed)

    @property
    def verses_done(self) -> int:
        return sum(VERSE_COUNTS[c] for c in self.completed)

    @property
    def percent(self) -> float:
        return round(self.verses_done / TOTAL_VERSES * 100, 1)

    @property
    def percent_int(self) -> int:
        return int(self.verses_done * 100 // TOTAL_VERSES)

    @property
    def is_finished(self) -> bool:
        return self.count == TOTAL_CHAPTERS

    @property
    def next_chapter(self) -> int | None:
        for c in range(1, TOTAL_CHAPTERS + 1):
            if c not in self.completed:
                return c
        return None

    @property
    def last_completed_at(self) -> datetime | None:
        return max(self.completed.values()) if self.completed else None

    def daily_counts(self) -> dict[date, int]:
        counts: dict[date, int] = {}
        for dt in self.completed.values():
            d = dt.date()
            counts[d] = counts.get(d, 0) + 1
        return counts

    def streaks(self, today: date) -> tuple[int, int]:
        days = sorted(self.daily_counts())
        if not days:
            return 0, 0
        best = run = 1
        for prev, cur in zip(days, days[1:]):
            run = run + 1 if (cur - prev).days == 1 else 1
            best = max(best, run)
        day_set = set(days)
        cursor = today if today in day_set else today - timedelta(days=1)
        current = 0
        while cursor in day_set:
            current += 1
            cursor -= timedelta(days=1)
        return current, best

    def pace(self, period: Period) -> dict:
        expected = period.expected_chapters
        diff = self.count - expected
        left = TOTAL_CHAPTERS - self.count
        per_day = left / period.remaining_days if period.remaining_days and left else 0
        if self.is_finished:
            label, tone = "완주했어요!", "done"
        elif period.status == "before":
            label, tone = "곧 시작해요", "neutral"
        elif diff > 0:
            label, tone = f"계획보다 {diff}장 앞서 있어요", "ahead"
        elif diff == 0:
            label, tone = "계획대로 잘 가고 있어요", "ontrack"
        else:
            label, tone = f"계획보다 {-diff}장 뒤처져 있어요", "behind"
        return {
            "expected": expected,
            "diff": diff,
            "left": left,
            "per_day": round(per_day, 1),
            "label": label,
            "tone": tone,
        }

    def badges(self, today: date) -> list[Badge]:
        _, best = self.streaks(today)
        p = self.percent
        return [
            Badge("first", "첫 걸음", "첫 장 완료", self.count >= 1),
            Badge("q1", "25% 돌파", "4분의 1 지점", p >= 25),
            Badge("half", "반환점", "절반 완료", p >= 50),
            Badge("q3", "75% 돌파", "결승선이 보여요", p >= 75),
            Badge("streak3", "3일 연속", "3일 연속 필사", best >= 3),
            Badge("streak7", "7일 연속", "일주일 연속 필사", best >= 7),
            Badge("wisdom8", "지혜의 찬가", "8장 완료", 8 in self.completed),
            Badge("finish", "잠언 완주", "31장 모두 완료", self.is_finished),
        ]


def load_all_stats(session: Session, members: list[str]) -> dict[str, MemberStats]:
    stats = {m: MemberStats(m, {}) for m in members}
    for row in session.scalars(select(ChapterProgress)):
        if row.member in stats:
            stats[row.member].completed[row.chapter] = to_kst(row.completed_at)
    for member, chapter in session.execute(select(ChapterNote.member, ChapterNote.chapter)):
        if member in stats:
            stats[member].note_chapters.add(chapter)
    return stats


def load_member_stats(session: Session, member: str) -> MemberStats:
    stats = MemberStats(member, {})
    for row in session.scalars(select(ChapterProgress).where(ChapterProgress.member == member)):
        stats.completed[row.chapter] = to_kst(row.completed_at)
    stats.note_chapters = set(
        session.scalars(select(ChapterNote.chapter).where(ChapterNote.member == member))
    )
    return stats


def calendar_months(period: Period, counts: dict[date, int]) -> list[dict]:
    """Sunday-first month grids covering the challenge period."""
    months: list[dict] = []
    cursor = period.start.replace(day=1)
    while cursor <= period.end:
        nxt = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        cells: list[dict | None] = [None] * ((cursor.weekday() + 1) % 7)
        d = cursor
        while d < nxt:
            cells.append(
                {
                    "date": d,
                    "count": counts.get(d, 0),
                    "in_period": period.start <= d <= period.end,
                    "is_today": d == period.today,
                    "is_future": d > period.today,
                }
            )
            d += timedelta(days=1)
        months.append({"label": f"{cursor.year}년 {cursor.month}월", "cells": cells})
        cursor = nxt
    return months


def team_summary(stats: dict[str, MemberStats], period: Period) -> dict:
    values = list(stats.values())
    n = len(values) or 1
    chapter_counts = {c: 0 for c in range(1, TOTAL_CHAPTERS + 1)}
    today_count = 0
    active_today: set[str] = set()
    for s in values:
        for c, dt in s.completed.items():
            chapter_counts[c] += 1
            if dt.date() == period.today:
                today_count += 1
                active_today.add(s.member)
    return {
        "avg_percent": round(sum(s.percent for s in values) / n, 1),
        "avg_chapters": round(sum(s.count for s in values) / n, 1),
        "finished": sum(1 for s in values if s.is_finished),
        "started": sum(1 for s in values if s.count > 0),
        "on_track": sum(1 for s in values if s.count >= period.expected_chapters),
        "total_chapters_done": sum(s.count for s in values),
        "chapter_counts": chapter_counts,
        "today_count": today_count,
        "active_today": len(active_today),
        "member_count": len(values),
    }
