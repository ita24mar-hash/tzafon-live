"""סוכן חיפוש מקורות. רץ פעם ביום ב-GitHub Actions.

1. קורא את הדפים הציבוריים של המקורות הפעילים ואוסף ערוצי טלגרם שמוזכרים בהם
   (הודעות שהועברו מערוץ אחר, קישורי t.me ואזכורי @).
2. בודק כל ערוץ כזה: האם הוא פעיל, כמה מנויים, וכמה מההודעות שלו הן דיווחים על אירועים בישראל
   (באותו מנתח שבונה את האירועים באפליקציה).
3. כותב את התוצאות ל-data/candidates.json. הסוכן רק מציע: מקור נכנס לאיסוף רק אחרי אישור,
   כשמוסיפים אותו ל-collector/sources.json.
"""
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "candidates.json"
IGNORE = ROOT / "collector" / "scout_ignore.json"     # ערוצים שנדחו: לא להציע שוב
MAX_PROBE = 30                                       # כמה מועמדים לבדוק בכל הרצה
NAME = r"[A-Za-z][A-Za-z0-9_]{4,31}"
LINK = re.compile(rf"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?({NAME})(?![A-Za-z0-9_])", re.I)
MENTION = re.compile(rf"(?<![A-Za-z0-9_.@/])@({NAME})(?![A-Za-z0-9_])")
RESERVED = {"joinchat", "addlist", "share", "proxy", "socks", "addstickers", "setlanguage", "contact", "boost",
            "addemoji", "iv", "login", "telegram", "durov", "username"}


def address(s: dict) -> str:
    return s["address"].rstrip("/").split("/")[-1].lstrip("@").lower()


def mentions(html: str) -> list[str]:
    found = [m.group(1) for m in LINK.finditer(html)] + [m.group(1) for m in MENTION.finditer(html)]
    return [n for n in found if n.lower() not in RESERVED and not n.lower().endswith("bot")]


def evaluate(username: str, fetch) -> dict:
    from app import analyze, ingest, telegram_web
    out = {"username": username, "url": f"https://t.me/{username}", "title": "", "description": "",
           "verified": False, "subscribers": None, "messages": 0, "newest": None, "age_hours": None,
           "noise_share": None, "report_share": None, "north_share": None, "regions": {}, "samples": [],
           "verdict": "unsuitable", "reason": ""}
    try:
        code, body = fetch(telegram_web.PREVIEW_URL.format(username=username))
        html = body.decode("utf-8", "replace")
        info = telegram_web.parse_channel_info(html)
        out.update({k: info.get(k, out[k]) for k in ("title", "description", "verified", "subscribers")})
        out["description"] = (out["description"] or "")[:160]
        msgs = telegram_web.parse_preview(html, username)
    except Exception as e:
        out["reason"] = "לא ניתן לקרוא את הדף: " + (str(e) if isinstance(e, (RuntimeError, ValueError)) else type(e).__name__)
        return out
    if not msgs:
        out["reason"] = "אין דף הודעות ציבורי (קבוצה, ערוץ פרטי או ריק)"
        return out
    n = len(msgs)
    newest = max(m["published_at"] for m in msgs)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(newest)).total_seconds() / 3600
    noise = reports = north = 0
    regions = defaultdict(int)
    for m in msgs:
        text = ingest.clean(m["content"])
        if ingest.classify_noise(text):
            noise += 1
            continue
        a = analyze.analyze(text)
        if a["relevant"]:
            reports += 1
            north += a["north"]
            for r in a["regions"]:
                regions[r] += 1
            if len(out["samples"]) < 2:
                out["samples"].append(ingest.excerpt(ingest.mask_phones(text)))
    out.update({"messages": n, "newest": newest, "age_hours": round(age, 1), "noise_share": round(noise / n, 2),
                "report_share": round(reports / n, 2), "north_share": round(north / n, 2), "regions": dict(regions)})
    if age > 24 * 7:
        out["reason"] = "לא פרסם בשבוע האחרון"
    elif out["noise_share"] >= 0.5:
        out["reason"] = "רוב ההודעות פרסומות, בקשות או רעש"
    elif out["report_share"] >= 0.15 and age <= 48 and n >= 10:
        out["verdict"], out["reason"] = "recommended", "פעיל, וחלק ניכר מההודעות הן דיווחים על אירועים בישראל"
    elif out["report_share"] >= 0.05:
        out["verdict"], out["reason"] = "possible", "יש בו דיווחים, אבל מעטים או לא עדכניים"
    else:
        out["reason"] = "כמעט אין בו דיווחים על אירועים בישראל"
    return out


def main(argv=None, fetch=None) -> dict:
    from app import net
    fetch = fetch or net.safe_fetch
    sources = json.loads((ROOT / "collector" / "sources.json").read_text(encoding="utf-8"))
    known = {address(s) for s in sources}
    ignore = {x.lower() for x in json.loads(IGNORE.read_text(encoding="utf-8"))} if IGNORE.exists() else set()
    active = [s for s in sources if s.get("enabled") and s["kind"] == "telegram"]

    seen_by = defaultdict(set)        # ערוץ מועמד → אילו מקורות הזכירו אותו
    count = defaultdict(int)
    spelled = {}
    scanned = 0
    for s in active:
        try:
            code, body = fetch(f"https://t.me/s/{address(s)}")
            scanned += 1
        except Exception:
            continue
        own = address(s)
        for name in mentions(body.decode("utf-8", "replace")):
            low = name.lower()
            if low == own or low in known or low in ignore:
                continue
            seen_by[low].add(s["name"])
            count[low] += 1
            spelled.setdefault(low, name)
        time.sleep(1.5)

    # קודם ערוצים שהוזכרו בכמה מקורות שונים, אחר כך לפי מספר האזכורים
    order = sorted(seen_by, key=lambda k: (-len(seen_by[k]), -count[k]))[:MAX_PROBE]
    rows = []
    for low in order:
        r = evaluate(spelled[low], fetch)
        r["mentioned_by"] = sorted(seen_by[low])
        r["mentions"] = count[low]
        rows.append(r)
        time.sleep(2)
    rank = {"recommended": 0, "possible": 1, "unsuitable": 2}
    rows.sort(key=lambda r: (rank[r["verdict"]], -(r["report_share"] or 0)))
    result = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scanned_sources": scanned,
              "found": len(seen_by), "checked": len(rows), "candidates": rows}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [f"## סוכן מקורות: נסרקו {scanned} מקורות, נמצאו {len(seen_by)} ערוצים, נבדקו {len(rows)}", "",
             "| ערוץ | שם | המלצה | דיווחים | צפון | מנויים | שעות מאז הודעה | הוזכר ע\"י |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['username']} | {r['title'][:30]} | {r['verdict']} | {r['report_share']} | {r['north_share']} "
                     f"| {r['subscribers'] or ''} | {r['age_hours'] if r['age_hours'] is not None else ''} "
                     f"| {len(r['mentioned_by'])} |")
    print("\n".join(lines))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    main()
    sys.exit(0)
