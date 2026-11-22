"""גישה למסד הנתונים. כל ה-SQL מרוכז כאן וב-repo.py כדי להקל מעבר עתידי ל-PostgreSQL."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def db_path() -> str:
    return os.environ.get("DATABASE_PATH", "data/tzafon.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    path = db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    with connect() as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(SCHEMA)


def audit(con, actor: str, action: str, entity: str, entity_id=None, detail=None) -> None:
    con.execute(
        "INSERT INTO audit_logs(at, actor, action, entity, entity_id, detail) VALUES (?,?,?,?,?,?)",
        (now_iso(), actor, action, entity, entity_id, json.dumps(detail or {}, ensure_ascii=False)),
    )
