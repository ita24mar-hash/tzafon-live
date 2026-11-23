"""בניית אירועים מהודעות מנותחות.

רץ מחדש בכל הרצת איסוף על כל ההודעות, כך שהתוצאה תלויה רק בהודעות ובכללים, לא בהיסטוריה.
אירוע נוצר רק מהודעה שאינה רעש ושהמנתח סימן כרלוונטית (מקום בישראל + סוג אירוע).

איחוד הודעות לאותו אירוע (כללים, לא AI):
  1. אותו סוג אירוע ואותו מקום, בהפרש של עד 3 שעות; או
  2. אותו מקור ואותו סוג, בהפרש של עד 20 דקות (למשל כמה התרעות באותו גל); או
  3. הודעת "האירוע הסתיים" מאותו מקור ובאותו סוג, עד שעה אחרי הודעה פתוחה.
"""
import json
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

from .gazetteer import PLACES

KINDS = {name: kind for kind, name, *_ in PLACES}

TITLE = {"security": "אירוע ביטחוני", "accident": "תאונת דרכים", "fire": "שריפה", "closure": "חסימה או שיבוש תנועה",
         "infrastructure": "תקלת תשתית", "weather": "מזג אוויר חריג", "hazard": "מפגע", "medical": "אירוע רפואי",
         "other": "אירוע"}
SAME_PLACE = timedelta(hours=3)
RECAP_WINDOW = timedelta(hours=24)
SAME_SOURCE = timedelta(minutes=20)
ENDED_UPDATE = timedelta(hours=1)


def _in(place: str) -> str:
    """'ב' + שם מקום: "בכרמיאל", "בכביש 89", "בגליל העליון" (ה' הידיעה נבלעת)."""
    return "ב" + (place[1:] if place.startswith("ה") else place)


def _ts(iso):
    return datetime.fromisoformat(iso)


def _matches(cluster, r) -> str | None:
    """מחזיר את סוג הקשר (report/update/copy) אם ההודעה שייכת לאירוע, אחרת None."""
    a, last = r["analysis"], cluster["reports"][-1]
    if a["type"] != cluster["type"]:
        return None
    gap = _ts(r["published_at"]) - _ts(last["published_at"])
    if any(x["content_hash"] == r["content_hash"] and x["source_id"] != r["source_id"] for x in cluster["reports"]):
        return "copy"                                   # אותו טקסט בדיוק ממקור אחר = העתקה, לא אימות
    if a["location"] in cluster["places"] and gap <= SAME_PLACE:
        return "update" if a["ended"] else "report"
    same_source = any(x["source_id"] == r["source_id"] for x in cluster["reports"])
    # אותו מקור ואותו סוג תוך דקות: לרוב אותו אירוע – אלא אם ההודעות מציינות יישובים שונים בלי שום מקום משותף
    # (ערוץ כבאות שמדווח על שריפות בנתניה ובטירה = שני אירועים; התרעה בזרעית ובשומרה, "קו העימות" = אירוע אחד)
    specific = lambda p: KINDS.get(p) in ("locality", "junction")
    if (specific(a["location"]) and any(specific(p) for p in cluster["places"])
            and not set(a["places"]) & set(cluster["places"])):
        return None
    if same_source and gap <= SAME_SOURCE:
        return "report"
    if same_source and a["ended"] and gap <= ENDED_UPDATE:
        return "update"
    return None


NIGHT_WORDS = {"הלילה", "לפנות בוקר", "במהלך הלילה", "בשעות הלילה", "בשעת לילה", "בשעות הבוקר המוקדמות"}
IL = ZoneInfo("Asia/Jerusalem")


def is_recap(r) -> bool:
    """הודעה שמספרת בדיעבד על אירוע ("הלילה רכב עלה באש" שפורסם ב-09:20). "הלילה" שפורסם בלילה הוא דיווח חי."""
    word = r["analysis"].get("recap")
    if not word:
        return False
    if word in NIGHT_WORDS:
        hour = _ts(r["published_at"]).astimezone(IL).hour
        return 6 <= hour < 20
    return True


def _recap_target(clusters, r):
    a = r["analysis"]
    for c in reversed(clusters):
        if (c["type"] == a["type"] and a["location"] in c["places"]
                and _ts(r["published_at"]) - _ts(c["reports"][-1]["published_at"]) <= RECAP_WINDOW):
            return c
    return None


def build_events(con) -> int:
    con.execute("DELETE FROM events WHERE is_demo = 0")
    rows = con.execute(
        "SELECT rr.id, rr.source_id, rr.published_at, rr.content, rr.content_hash, rr.ai_result, s.is_official"
        " FROM raw_reports rr JOIN sources s ON s.id = rr.source_id"
        " WHERE rr.is_demo = 0 AND rr.noise IS NULL AND rr.ai_result IS NOT NULL ORDER BY rr.published_at, rr.id"
    ).fetchall()
    clusters = []
    for row in rows:
        r = dict(row) | {"analysis": json.loads(row["ai_result"])}
        if not r["analysis"].get("relevant"):
            continue
        if is_recap(r):
            # סיכום בדיעבד: מצורף לאירוע המקורי בלי להקפיץ אותו כחדש; בלי אירוע מקורי – לא נוצר אירוע
            c = _recap_target(clusters, r)
            if c:
                c["reports"].append(r | {"relation": "recap"})
            continue
        for c in reversed(clusters):
            rel = _matches(c, r)
            if rel:
                c["reports"].append(r | {"relation": rel})
                for p in r["analysis"]["places"]:
                    if p not in c["places"]:
                        c["places"].append(p)
                break
        else:
            clusters.append({"type": r["analysis"]["type"], "places": list(r["analysis"]["places"]),
                             "reports": [r | {"relation": "report"}]})

    loc_ids = {x["name_he"]: x["id"] for x in con.execute("SELECT id, name_he FROM locations")}
    for c in clusters:
        reps = c["reports"]
        a0 = reps[0]["analysis"]
        main_place = a0["location"]
        sources = {x["source_id"] for x in reps if x["relation"] != "copy"}
        if any(x["is_official"] for x in reps):
            verification = "official"
        elif len(sources) >= 2:
            verification = "multi_source"
        else:
            verification = "single_source"
        others = [p for p in c["places"] if p != main_place and KINDS.get(p) != "region"]
        more = "" if not others else " ועוד מקום אחד" if len(others) == 1 else f" ועוד {len(others)} מקומות"
        title = f"{TITLE[c['type']]} {_in(main_place)}{more}"
        first = next((x for x in reps if x["is_official"]), reps[0])
        live = [x for x in reps if x["relation"] != "recap"]
        status = "ended" if live[-1]["analysis"]["ended"] or len(live) < len(reps) else "unknown"
        cur = con.execute(
            "INSERT INTO events(title, summary, event_type, status, verification, severity, location_id,"
            " location_precision, occurred_at, first_reported_at, updated_at, published, places, analyzer)"
            " VALUES (?,?,?,?,?,?,?,?,NULL,?,?,1,?,?)",
            (title, first["content"], c["type"], status, verification,
             max(x["analysis"]["severity"] for x in reps), loc_ids.get(main_place),
             "approx" if loc_ids.get(main_place) else "unknown",
             reps[0]["published_at"], live[-1]["published_at"], json.dumps(c["places"], ensure_ascii=False),
             a0["v"]))
        for x in reps:
            con.execute("INSERT INTO event_reports(event_id, raw_report_id, relation) VALUES (?,?,?)",
                        (cur.lastrowid, x["id"], x["relation"]))
    return len(clusters)
