"""Setup SQLAlchemy: engine, SessionLocal, Base, dan helper inisialisasi DB."""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False}
    if config.DATABASE_URL.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def init_db() -> None:
    """Buat semua tabel. Dijalankan sekali saat aplikasi start."""
    from . import models  # noqa: F401  (daftarkan model ke Base.metadata)

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — satu session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()