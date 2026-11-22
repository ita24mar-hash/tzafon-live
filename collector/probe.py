"""בדיקת מקורות מועמדים. רץ ב-GitHub Actions (קריאה בלבד, לא שומר כלום במאגר).

לכל מועמד: האם הדף הציבורי קיים, שם ותיאור הערוץ, תג מאומת, מנויים, מספר ההודעות
שניתן לקרוא, מועד ההודעה האחרונה, וכמה מההודעות מזכירות את הצפון.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NORTH = re.compile(r"צפון|גליל|צפת|כרמיאל|קריית שמונה|קרית שמונה|מירון|קו העימות|ראש פינה|חצור|נהריה|"
                   r"טבריה|גולן|מטולה|עכו|כביש (?:89|85|90|866)|ספסופה|בר יוחאי|אור הגנוז|קצרין|שלומי")


def probe(username: str, fetch=None) -> dict:
    from app import net, telegram_web
    fetch = fetch or net.safe_fetch
    out = {"username": username, "reachable": False, "public_preview": False, "title": "", "description": "",
           "verified": False, "subscribers": None, "messages": 0, "newest": None, "oldest": None,
           "north_share": None, "error": None}
    try:
        code, body = fetch(telegram_web.PREVIEW_URL.format(username=username))
        html = body.decode("utf-8", "replace")
        out["reachable"] = code == 200
        out.update(telegram_web.parse_channel_info(html))
        msgs = telegram_web.parse_preview(html, username)
        if msgs:
            out["public_preview"] = True
            out["messages"] = len(msgs)
            times = sorted(m["published_at"] for m in msgs)
            out["oldest"], out["newest"] = times[0], times[-1]
            out["north_share"] = round(sum(bool(NORTH.search(m["content"])) for m in msgs) / len(msgs), 2)
        elif code == 200:
            out["error"] = "הדף נפתח אבל אין בו הודעות (תצוגה ציבורית כבויה, ערוץ ריק או לא קיים)"
        else:
            out["error"] = f"קוד {code}"
    except Exception as e:
        out["error"] = str(e) if isinstance(e, (RuntimeError, ValueError)) else type(e).__name__
    return out


def age_hours(iso):
    return None if not iso else round((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600, 1)


def main():
    cands = json.loads((ROOT / "collector" / "candidates.json").read_text(encoding="utf-8"))
    rows = []
    for c in cands:
        r = probe(c["username"]) | {k: c[k] for k in ("claimed", "category", "claims_official", "evidence")}
        r["age_hours"] = age_hours(r["newest"])
        rows.append(r)
        time.sleep(2)   # לא להעמיס על טלגרם
    print("PROBE_JSON_BEGIN")
    print(json.dumps(rows, ensure_ascii=False))
    print("PROBE_JSON_END")
    lines = ["## בדיקת מקורות מועמדים", "",
             "| ערוץ | שם בדף | מאומת | מנויים | הודעות בדף | הודעה אחרונה | שעות מאז | צפון | שגיאה |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['username']} | {r['title'][:40]} | {'✔' if r['verified'] else ''} | {r['subscribers'] or ''} "
                     f"| {r['messages']} | {r['newest'] or ''} | {r['age_hours'] if r['age_hours'] is not None else ''} "
                     f"| {r['north_share'] if r['north_share'] is not None else ''} | {r['error'] or ''} |")
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
    sys.exit(0)
