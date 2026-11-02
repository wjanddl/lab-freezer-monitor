import logging
import sqlite3

from app.models.alert_settings import AlertSettings

log = logging.getLogger(__name__)


def load(db: sqlite3.Connection) -> AlertSettings:
    row = db.execute("SELECT json FROM settings WHERE id=1").fetchone()
    return AlertSettings.model_validate_json(row[0]) if row else AlertSettings()


def save(db: sqlite3.Connection, new: AlertSettings, old: AlertSettings) -> None:
    changes = {k: (v, getattr(new, k)) for k, v in old.model_dump().items() if v != getattr(new, k)}
    db.execute("INSERT OR REPLACE INTO settings (id, json) VALUES (1, ?)", (new.model_dump_json(),))
    db.commit()
    log.warning("settings changed (old, new): %s", changes)
