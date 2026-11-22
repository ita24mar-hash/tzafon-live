"""קליטת הודעות גולמיות למסד, ויומן הודעות קבוע (JSONL) שנשמר בין הרצות."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import now_iso

FIELDS = ("external_id", "url", "published_at", "ingested_at", "edited_at", "content", "content_hash", "lang")
MAX_CONTENT = 8000          # תקרת אורך להודעה בודדת
FRESH_HOURS = 24            # רק הודעה שפורסמה ב-24 השעות האחרונות נחשבת עדכנית
PHONE = re.compile(r"(?<!\d)(?:\+972[-\s]?|0)(?:[23489]|5\d|7\d)[-\s]?\d{3}[-\s]?\d{4}(?!\d)")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def detect_lang(text: str) -> str | None:
    he = sum("֐" <= c <= "׿" for c in text)
    ar = sum("؀" <= c <= "ۿ" for c in text)
    if he == ar == 0:
        return None
    return "he" if he >= ar else "ar"


def mask_phones(text: str) -> str:
    """מסיר מספרי טלפון. מופעל לפני השמירה, כי היומן נשמר במאגר ציבורי."""
    return PHONE.sub("[מספר הוסר]", text)


def clean(text: str) -> str:
    return mask_phones(text)[:MAX_CONTENT]


def prune(con, max_per_source: int) -> int:
    """מגביל את גודל המאגר: שומר רק את N ההודעות החדשות ביותר מכל מקור."""
    n = 0
    for src in con.execute("SELECT id FROM sources").fetchall():
        n += con.execute(
            "DELETE FROM raw_reports WHERE source_id = ? AND is_demo = 0 AND id NOT IN ("
            " SELECT id FROM raw_reports WHERE source_id = ? ORDER BY published_at DESC, id DESC LIMIT ?)",
            (src["id"], src["id"], max_per_source)).rowcount
    return n


def upsert_report(con, source_id: int, msg: dict, ingested_at: str | None = None) -> str:
    """מחזיר 'new' / 'edited' / 'same'. אילוץ הייחודיות (source_id, external_id) מונע כפילות."""
    msg = msg | {"content": clean(msg["content"])}
    h = content_hash(msg["content"])
    row = con.execute("SELECT id, content_hash FROM raw_reports WHERE source_id = ? AND external_id = ?",
                      (source_id, msg["external_id"])).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO raw_reports(source_id, external_id, url, published_at, ingested_at, edited_at,"
            " content, content_hash, lang) VALUES (?,?,?,?,?,?,?,?,?)",
            (source_id, msg["external_id"], msg.get("url"), msg["published_at"],
             msg.get("ingested_at") or ingested_at or now_iso(), msg.get("edited_at"),
             msg["content"], h, msg.get("lang") or detect_lang(msg["content"])),
        )
        return "new"
    if row["content_hash"] != h:
        con.execute("UPDATE raw_reports SET content = ?, content_hash = ?, edited_at = ?, lang = ? WHERE id = ?",
                    (msg["content"], h, msg.get("edited_at") or now_iso(), detect_lang(msg["content"]), row["id"]))
        return "edited"
    return "same"


def mark_ingested(con, source_id: int) -> None:
    r = con.execute("SELECT COUNT(*) AS n, MAX(ingested_at) AS last FROM raw_reports WHERE source_id = ?",
                    (source_id,)).fetchone()
    if r["n"]:
        con.execute("UPDATE sources SET ingested_count = ?, last_ingest_at = ?, status = 'ingesting',"
                    " last_error = NULL WHERE id = ?", (r["n"], r["last"], source_id))


def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def is_historical(published_at: str, ingested_at: str) -> bool:
    """הודעה שכבר הייתה ישנה מ-24 שעות ברגע שנקלטה (למשל בהרצה הראשונה) היא היסטורית, לא דיווח חדש."""
    return _ts(ingested_at) - _ts(published_at) > timedelta(hours=FRESH_HOURS)


def detect_gap(con, source_id: int, messages: list[dict]) -> int:
    """כמה מספרי הודעות דילגנו עליהם מאז ההרצה הקודמת. 0 = אין פער (או הרצה ראשונה).

    הדף הציבורי מציג רק את ~20 ההודעות האחרונות; אם בין הרצות פורסמו יותר, חלק לא ייקלט.
    מספר גבוה יכול לנבוע גם מהודעות שנמחקו בערוץ, לכן זו אזהרה ולא שגיאה.
    """
    row = con.execute("SELECT MAX(CAST(external_id AS INTEGER)) AS m FROM raw_reports WHERE source_id = ?",
                      (source_id,)).fetchone()
    ids = [int(m["external_id"]) for m in messages if m["external_id"].isdigit()]
    if row["m"] is None or not ids:
        return 0
    return max(0, min(ids) - row["m"] - 1)


def source_freshness(con, now: datetime | None = None) -> dict[int, dict]:
    """לכל מקור: מועד ההודעה האחרונה שפורסמה בו, והאם הוא פרסם ב-24 השעות האחרונות."""
    now = now or datetime.now(timezone.utc)
    out = {}
    for r in con.execute("SELECT source_id, MAX(published_at) AS newest FROM raw_reports WHERE is_demo = 0"
                         " GROUP BY source_id"):
        out[r["source_id"]] = {"newest_published_at": r["newest"],
                               "fresh": now - _ts(r["newest"]) <= timedelta(hours=FRESH_HOURS)}
    return out


def list_raw_reports(con, limit: int = 200) -> list[dict]:
    rows = con.execute(
        "SELECT rr.id, rr.external_id, rr.url, rr.published_at, rr.ingested_at, rr.edited_at, rr.content,"
        " rr.lang, s.name AS source_name, s.kind AS source_kind, s.is_official"
        " FROM raw_reports rr JOIN sources s ON s.id = rr.source_id"
        " WHERE rr.is_demo = 0 ORDER BY rr.published_at DESC, rr.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) | {"is_official": bool(r["is_official"]),
                       "historical": is_historical(r["published_at"], r["ingested_at"])} for r in rows]


# ---------- יומן קבוע ----------
def load_log(con, path: Path, source_ids: dict[str, int]) -> int:
    """טוען הודעות שנשמרו בהרצות קודמות. source_ids: כתובת מנורמלת → מזהה מקור."""
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        sid = source_ids.get(rec["source"])
        if sid is not None:
            upsert_report(con, sid, rec)
            n += 1
    return n


def save_log(con, path: Path) -> int:
    """כותב את כל ההודעות האמיתיות בסדר קבוע, כך ש-Git רואה שינוי רק כשיש מידע חדש."""
    rows = con.execute(
        "SELECT s.address_norm AS source, rr.* FROM raw_reports rr JOIN sources s ON s.id = rr.source_id"
        " WHERE rr.is_demo = 0 ORDER BY s.address_norm, CAST(rr.external_id AS INTEGER), rr.external_id"
    ).fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            rec = {"source": r["source"]} | {k: r[k] for k in FIELDS}
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)
