"""סוכן חיפוש מקורות. רץ פעם ביום ב-GitHub Actions, ומגיש את ההצעות לאישור.

טלגרם, בשני שלבים:
  1. קורא את הדפים הציבוריים של המקורות הפעילים ואוסף ערוצים שמוזכרים בהם
     (הודעות שהועברו, קישורי t.me, אזכורי @).
  2. בודק אותם, ומהערוצים שנמצאו מתאימים ממשיך לערוצים שהם עצמם מזכירים.
אתרים: לכל אתר ברשימה collector/site_seeds.json מוצא את פיד ה-RSS שלו (מה שהאתר מצהיר עליו
  בדף הבית, או כתובות מקובלות) ובודק את הידיעות.

כל מועמד נבדק באותו מנתח שבונה את האירועים באפליקציה. התוצאות נכתבות ל-data/candidates.json,
והצעות חדשות מוגשות לאישור (collector/proposals.py פותח עליהן issue ב-GitHub).
הסוכן לא מוסיף מקורות בעצמו.
"""
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from collector import sources_edit as se

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "candidates.json"
SEEDS = ROOT / "collector" / "site_seeds.json"
MAX_PROBE = 40            # ערוצים בשלב הראשון
TG_SEEDS = ROOT / "collector" / "scout_seeds.json"
MAX_PROBE_2 = 15          # ערוצים בשלב השני
NAME = r"[A-Za-z][A-Za-z0-9_]{4,31}"
LINK = re.compile(rf"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?({NAME})(?![A-Za-z0-9_])", re.I)
MENTION = re.compile(rf"(?<![A-Za-z0-9_.@/])@({NAME})(?![A-Za-z0-9_])")
RESERVED = {"joinchat", "addlist", "share", "proxy", "socks", "addstickers", "setlanguage", "contact", "boost",
            "addemoji", "iv", "login", "telegram", "durov", "username"}
FEED_PATHS = ["/feed", "/rss", "/rss.xml", "/feed.xml", "/rss/", "/feed/"]
PREFER = re.compile(r"מבזק|חדשות|news|flash|breaking|ראשי|כל הכתבות|all", re.I)


EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask(text: str) -> str:
    """בלי כתובות מייל ומספרי טלפון בקובץ ההצעות (הוא נשמר במאגר ציבורי)."""
    from app import ingest
    return ingest.mask_phones(EMAIL.sub("[מייל הוסתר]", text or ""))


def address(s: dict) -> str:
    return s["address"].rstrip("/").split("/")[-1].lstrip("@").lower()


def mentions(html: str) -> list[str]:
    found = [m.group(1) for m in LINK.finditer(html)] + [m.group(1) for m in MENTION.finditer(html)]
    return [n for n in found if n.lower() not in RESERVED and not n.lower().endswith("bot")]


def score(out: dict, msgs: list[dict]) -> dict:
    """אותו מנתח של האפליקציה: כמה מההודעות הן דיווחים על אירועים בישראל, כמה רעש."""
    from app import analyze, ingest
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
                out["samples"].append(ingest.excerpt(mask(text)))
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


def _blank(**kw) -> dict:
    return {"title": "", "description": "", "verified": False, "subscribers": None, "messages": 0, "newest": None,
            "age_hours": None, "noise_share": None, "report_share": None, "north_share": None, "regions": {},
            "samples": [], "verdict": "unsuitable", "reason": ""} | kw


def evaluate(username: str, fetch) -> dict:
    from app import telegram_web
    out = _blank(kind="telegram", key=se.key("telegram", username), username=username,
                 url=f"https://t.me/{username}", address=f"https://t.me/{username}", links=[])
    try:
        code, body = fetch(telegram_web.PREVIEW_URL.format(username=username))
        html = body.decode("utf-8", "replace")
        info = telegram_web.parse_channel_info(html)
        out.update({k: info.get(k, out[k]) for k in ("title", "description", "verified", "subscribers")})
        out["description"] = mask((out["description"] or "")[:160])
        out["links"] = mentions(html)
        msgs = telegram_web.parse_preview(html, username)
    except Exception as e:
        out["reason"] = "לא ניתן לקרוא את הדף: " + (str(e) if isinstance(e, (RuntimeError, ValueError)) else type(e).__name__)
        return out
    if not msgs:
        out["reason"] = "אין דף הודעות ציבורי (קבוצה, ערוץ פרטי או ריק)"
        return out
    return score(out, msgs)


def evaluate_site(site: dict, fetch) -> dict:
    """מוצא את הפיד של האתר ובודק אותו. אם יש כמה פידים, בוחר את זה עם הכי הרבה דיווחים."""
    from app import feeds
    home = site["url"]
    out = _blank(kind="rss", key="", username=urlsplit(home).hostname, url=home, address="", title=site.get("name", ""))
    feeds_found = []
    try:
        code, body = fetch(home)
        feeds_found = [u for _, u in sorted(feeds.discover_feeds(home, body), key=lambda x: not PREFER.search(x[0] + x[1]))]
    except Exception:
        pass
    feeds_found += [u for u in site.get("feeds", [])] + [urljoin(home, p) for p in FEED_PATHS]
    best, tried = None, 0
    for url in dict.fromkeys(feeds_found):
        if tried >= 5:
            break
        tried += 1
        try:
            items = feeds.fetch_feed(url, fetch)
        except Exception:
            continue
        r = score(_blank(kind="rss", key=se.key("rss", url), username=out["username"], url=home, address=url,
                         title=out["title"]), items)
        if best is None or (r["report_share"] or 0) > (best["report_share"] or 0):
            best = r
        time.sleep(1)
    if best is None:
        out["reason"] = "לא נמצא באתר פיד RSS שאפשר לקרוא"
        return out
    return best


def main(argv=None, fetch=None) -> dict:
    from app import net
    fetch = fetch or net.safe_fetch
    sources = json.loads(se.SOURCES.read_text(encoding="utf-8"))
    known = se.existing_keys() | se.ignored()
    active = [s for s in sources if s.get("enabled") and s["kind"] == "telegram"]

    # ---- טלגרם, שלב 1: ערוצים שהמקורות הפעילים מזכירים ----
    seen_by, count, spelled = defaultdict(set), defaultdict(int), {}

    def note(name, by):
        low = name.lower()
        if "tg:" + low in known:
            return
        seen_by[low].add(by)
        count[low] += 1
        spelled.setdefault(low, name)

    seeds = json.loads(TG_SEEDS.read_text(encoding="utf-8")) if TG_SEEDS.exists() else {}
    # ערוצי מדריך (רשימות של ערוצים) נסרקים כמו המקורות הפעילים, אבל לא מוצעים בעצמם
    scan_only = [{"name": f"מדריך {u}", "address": u} for u in seeds.get("scan", [])]
    for u in seeds.get("evaluate", []):             # ערוצים שהוכנסו ידנית לבדיקה
        if "tg:" + u.lower() not in known:
            seen_by[u.lower()].add("רשימת בדיקה ידנית")
            count[u.lower()] += 5
            spelled.setdefault(u.lower(), u)
    scanned = 0
    for s in active + scan_only:
        try:
            code, body = fetch(f"https://t.me/s/{address(s)}")
            scanned += 1
        except Exception:
            continue
        for name in mentions(body.decode("utf-8", "replace")):
            if name.lower() != address(s):
                note(name, s["name"])
        time.sleep(1.5)
    rows, done = [], set()

    def probe(names, limit):
        for low in sorted(names, key=lambda k: (-len(seen_by[k]), -count[k]))[:limit]:
            r = evaluate(spelled[low], fetch)
            r["mentioned_by"], r["mentions"] = sorted(seen_by[low]), count[low]
            rows.append(r)
            done.add(low)
            time.sleep(2)

    probe(list(seen_by), MAX_PROBE)
    # ---- טלגרם, שלב 2: ערוצים שהערוצים המתאימים מזכירים ----
    for r in [r for r in rows if r["verdict"] != "unsuitable"]:
        for name in r.get("links", []):
            if name.lower() != r["username"].lower():
                note(name, r["title"] or r["username"])
    probe([k for k in seen_by if k not in done], MAX_PROBE_2)

    # ---- אתרים ----
    sites = json.loads(SEEDS.read_text(encoding="utf-8")) if SEEDS.exists() else []
    site_rows = []
    for site in sites:
        r = evaluate_site(site, fetch)
        if r["key"] and r["key"] in known:
            continue                                    # הפיד כבר מקור (או נדחה)
        if not r["key"] and "rss:" + site["url"].lower() in known:
            continue
        r["mentioned_by"], r["mentions"] = ["רשימת אתרים לבדיקה"], 0
        site_rows.append(r)
        time.sleep(1.5)

    for r in rows:
        r.pop("links", None)
    rank = {"recommended": 0, "possible": 1, "unsuitable": 2}
    allrows = sorted(rows + site_rows, key=lambda r: (rank[r["verdict"]], -(r["report_share"] or 0)))
    result = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scanned_sources": scanned,
              "found": len(seen_by), "checked": len(rows), "sites_checked": len(site_rows), "candidates": allrows}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [f"## סוכן מקורות: נסרקו {scanned} מקורות, נמצאו {len(seen_by)} ערוצים, נבדקו {len(rows)} ערוצים ו-{len(site_rows)} אתרים",
             "", "| מקור | שם | המלצה | דיווחים | צפון | שעות מאז פרסום |", "|---|---|---|---|---|---|"]
    for r in allrows:
        lines.append(f"| {r['address'] or r['url']} | {r['title'][:30]} | {r['verdict']} | {r['report_share']} "
                     f"| {r['north_share']} | {r['age_hours'] if r['age_hours'] is not None else ''} |")
    print("\n".join(lines))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    main()
