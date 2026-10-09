"""
Database setup for WebFEA.

PostgreSQL is the production database (set DATABASE_URL, e.g.
`postgresql://user:pass@host:5432/webfea`). SQLite remains the zero-config
default for quick local hacking and the automated tests.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

_url = settings.sqlalchemy_url
if _url.startswith("sqlite"):
    engine = create_engine(_url, connect_args={"check_same_thread": False})
else:
    # pool_pre_ping survives DB restarts / idle-connection culling.
    engine = create_engine(_url, pool_pre_ping=True, pool_size=10, max_overflow=10)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
