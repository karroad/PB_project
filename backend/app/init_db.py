import logging

from sqlalchemy import inspect, select, text

from . import models  # noqa: F401 — register tables
from .config import settings
from .database import Base, SessionLocal, engine
from .models import User
from .security import hash_password

log = logging.getLogger("siteforge")


def _add_missing_columns() -> None:
    """Lightweight forward migration: adds new nullable columns to existing tables so an existing
    database keeps working after an upgrade. (Renames/drops still need a real migration tool.)"""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing and col.nullable:
                    ddl = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}'))
                    log.warning("Migrated: added column %s.%s", table.name, col.name)


def init_db() -> None:
    """Creates tables, applies additive column migrations and creates the bootstrap admin."""
    Base.metadata.create_all(engine)
    _add_missing_columns()
    db = SessionLocal()
    try:
        if not db.scalar(select(User).limit(1)):
            db.add(User(email=settings.ADMIN_EMAIL.lower(), name="Administrator", role="admin", password_hash=hash_password(settings.ADMIN_PASSWORD)))
            db.commit()
            log.warning("Created bootstrap admin %s — change the password!", settings.ADMIN_EMAIL)
    finally:
        db.close()
