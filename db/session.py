import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


DEFAULT_SQLITE_URL = "sqlite:///./data/d2c_agent.db"


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)


class Base(DeclarativeBase):
    pass


def _build_engine():
    url = get_database_url()

    # Ensure SQLite folder exists
    if url.startswith("sqlite:///./"):
        db_path = url.replace("sqlite:///./", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    connect_args = {}
    if url.startswith("sqlite:"):
        connect_args = {"check_same_thread": False}

    return create_engine(
        url,
        future=True,
        echo=False,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """Create tables if they do not exist."""
    from db import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    print(f"[DB] Initialized database: {get_database_url()}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()