"""Подключение к БД. Движок создаётся динамически: до прохождения мастера его нет."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

ALEMBIC_DIR = Path(__file__).parent.parent / "migrations"


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # noqa: ANN001
            # Встроенный lower() в SQLite понимает только ASCII — заменяем на Python,
            # чтобы поиск по кириллице был регистронезависимым.
            dbapi_conn.create_function(
                "lower", 1, lambda s: s.lower() if isinstance(s, str) else s, deterministic=True
            )
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)


def test_connection(url: str) -> None:
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def run_migrations(engine: Engine) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def init_db(url: str) -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(url)
    run_migrations(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    _backfill_nutrition()


def _backfill_nutrition() -> None:
    """Продукты без КБЖУ, которые есть во встроенном справочнике, получают примерные значения."""
    from sqlalchemy import select

    from .models import Product
    from .nutrition import fill_from_seed

    with _SessionLocal() as session:
        changed = False
        for product in session.scalars(select(Product).where(Product.kcal.is_(None))):
            changed |= fill_from_seed(product)
        if changed:
            session.commit()


def is_configured() -> bool:
    return _SessionLocal is not None


def get_db() -> Iterator[Session]:
    if _SessionLocal is None:
        raise HTTPException(status_code=503, detail="База данных не настроена")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def startup() -> None:
    if settings.database_url:
        init_db(settings.database_url)
