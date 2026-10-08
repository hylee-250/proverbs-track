import os
import re
from dataclasses import dataclass, field
from datetime import date
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

KST = ZoneInfo("Asia/Seoul")


def parse_members(raw: str) -> list[str]:
    seen: set[str] = set()
    members: list[str] = []
    for name in re.split(r"[,\n]", raw or ""):
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            members.append(name)
    return members


def normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _date(key: str, default: str) -> date:
    return date.fromisoformat(os.getenv(key, default).strip())


@dataclass(frozen=True)
class Settings:
    app_title: str = field(default_factory=lambda: os.getenv("APP_TITLE", "잠언 필사 챌린지"))
    members: list[str] = field(default_factory=lambda: parse_members(os.getenv("MEMBERS", "")))
    database_url: str = field(
        default_factory=lambda: normalize_db_url(os.getenv("DATABASE_URL", "sqlite:///./local.db"))
    )
    start_date: date = field(default_factory=lambda: _date("START_DATE", "2026-10-01"))
    end_date: date = field(default_factory=lambda: _date("END_DATE", "2026-11-30"))


settings = Settings()
