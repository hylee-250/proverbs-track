from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    # Neon suspends idle computes, so stale pooled connections must be detected and recycled.
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(engine)
