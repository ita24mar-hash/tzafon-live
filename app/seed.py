"""נתוני בסיס: מיקומים (אמיתיים) + נתוני הדגמה (מסומנים is_demo=1).

חשוב: הקואורדינטות כאן משוערות (coord_quality='approx') ונכתבו ידנית.
בשלב ג יוחלפו בנתונים ממאגר רשמי (למשל קובץ היישובים של הלמ"ס / data.gov.il).
לצמתים ולכבישים אין קואורדינטות בשלב זה – ולכן לא יוצגו כנקודה על המפה.
"""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from .db import connect, now_iso

from .gazetteer import PLACES

LOCATIONS = [(kind, name, json.dumps(aliases, ensure_ascii=False), lat, lon) for kind, name, aliases, lat, lon in PLACES]

DEMO_EVENTS = [
    # title, summary, type, status, verification, severity, location, precision, minutes_ago, n_reports
    ("תאונה בין שני רכבים בכניסה לצפת", "דיווח הדגמה: תאונה קלה, נתיב אחד חסום.", "accident",
     "ongoing", "multi_source", 2, "צפת", "approx", 25, 2),
    ("חסימת כביש 89 לכיוון מערב", "דיווח הדגמה: הכביש נחסם זמנית לתנועה.", "closure",
     "new", "single_source", 2, "כביש 89", "approx", 50, 1),
    ("שריפת קוצים סמוך למירון", "דיווח הדגמה: צוותי כיבוי פועלים במקום.", "fire",
     "ongoing", "official", 3, "מירון", "approx", 90, 2),
    ("הפסקת חשמל בכרמיאל", "דיווח הדגמה: תקלה בשכונה אחת, הטיפול הסתיים.", "infrastructure",
     "ended", "official", 1, "כרמיאל", "approx", 300, 1),
    ("דיווח על מפגע בכביש – מיקום לא ידוע", "דיווח הדגמה ללא מיקום: לא יוצג על המפה.", "hazard",
     "unknown", "single_source", 1, None, "unknown", 140, 1),
]


def seed_locations(con) -> None:
    for kind, name, aliases, lat, lon in LOCATIONS:
        con.execute(
            "INSERT OR IGNORE INTO locations(kind, name_he, aliases, lat, lon, coord_quality)"
            " VALUES (?,?,?,?,?,?)",
            (kind, name, aliases, lat, lon, "approx" if lat is not None else "none"),
        )


def seed_demo(con) -> None:
    if con.execute("SELECT 1 FROM sources WHERE is_demo = 1").fetchone():
        return
    now = datetime.now(timezone.utc)
    src_ids = []
    for i in (1, 2):
        cur = con.execute(
            "INSERT INTO sources(name, kind, address, address_norm, status, enabled, is_demo, created_at)"
            " VALUES (?,?,?,?,?,?,1,?)",
            (f"מקור הדגמה {i} (לא אמיתי)", "other", f"demo-{i}", f"demo-{i}", "configured", 0, now_iso()),
        )
        src_ids.append(cur.lastrowid)
    for n, (title, summary, etype, status, verif, sev, loc, prec, mins, n_rep) in enumerate(DEMO_EVENTS):
        when = (now - timedelta(minutes=mins)).isoformat(timespec="seconds")
        loc_id = None
        if loc:
            loc_id = con.execute("SELECT id FROM locations WHERE name_he = ?", (loc,)).fetchone()["id"]
        cur = con.execute(
            "INSERT INTO events(title, summary, event_type, status, verification, severity, location_id,"
            " location_precision, occurred_at, first_reported_at, updated_at, is_demo)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
            (title, summary, etype, status, verif, sev, loc_id, prec, None, when, when),
        )
        for r in range(n_rep):
            content = f"[הדגמה] {title}"
            rc = con.execute(
                "INSERT INTO raw_reports(source_id, external_id, url, published_at, ingested_at, content,"
                " content_hash, lang, is_demo) VALUES (?,?,?,?,?,?,?,?,1)",
                (src_ids[r % 2], f"demo-{n}-{r}", None, when, when, content,
                 hashlib.sha256(content.encode()).hexdigest(), "he"),
            )
            con.execute("INSERT INTO event_reports(event_id, raw_report_id) VALUES (?,?)",
                        (cur.lastrowid, rc.lastrowid))


def run_seed() -> None:
    with connect() as con:
        seed_locations(con)
        if os.environ.get("SEED_DEMO", "1") == "1":
            seed_demo(con)
