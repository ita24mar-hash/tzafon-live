"""תקציר כסיפור קצר לכל אזור, נכתב בעזרת מודל AI.

הערה: GitHub Models נסגר ביולי 2026, ולכן כרגע אין ספק מוגדר והתקציר מוצג כרשימה. ספק חדש יחובר כאן.

כללי בטיחות:
- המודל מקבל רק את האירועים עצמם (סוג, מקום, שעה, חומרה, כותרת) ומתבקש לא להוסיף שום דבר.
- כל סיפור נבדק: כל מספר וכל שם יישוב שמופיעים בו חייבים להופיע באירועים. אם לא – הסיפור נזרק,
  והאפליקציה מציגה את התקציר הרגיל (רשימה לפי תחומים).
- המכסה החינמית מוגבלת, ולכן יש לכל היותר קריאה אחת ל-AI כל 20 דקות, רק כשמשהו השתנה,
  וכל האזורים נכתבים באותה קריאה. התוצאה נשמרת ב-data/stories.json בין הרצות.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "stories.json"
TZ = ZoneInfo("Asia/Jerusalem")
MODEL = os.environ.get("STORY_MODEL", "openai/gpt-4.1-mini")
API = "https://models.github.ai/inference/chat/completions"
MIN_GAP = timedelta(minutes=20)       # לא יותר מקריאה אחת בכל 20 דקות
MAX_AGE = timedelta(hours=3)          # סיפור ישן מזה לא מוצג, גם אם לא היה שינוי
WINDOW = timedelta(hours=24)
MAX_EVENTS = 12                       # לכל אזור: האירועים החשובים ביותר
ALL = "all"

TYPE_HE = {"security": "ביטחון", "accident": "תאונה", "fire": "שריפה", "closure": "חסימת כביש",
           "infrastructure": "תשתיות", "weather": "מזג אוויר", "hazard": "מפגע", "medical": "אירוע רפואי",
           "earthquake": "רעידת אדמה", "cyber": "סייבר", "health": "בריאות הציבור", "other": "אחר"}
SEV_HE = {3: "קריטי", 2: "בינוני", 1: "נמוך"}
VERIF_HE = {"single_source": "דיווח ראשוני ממקור אחד", "multi_source": "דווח בכמה מקורות",
            "official": "אומת ע\"י גורם רשמי", "retracted": "הוכחש"}

SYSTEM = (
    "אתה עורך חדשות בחדר מצב. כתוב בעברית תקציר קצר כסיפור – 2 עד 4 משפטים, עד 380 תווים – של מה שקורה באזור, "
    "לפי רשימת האירועים בלבד. התחל מהחשוב ביותר (קריטי, ואז מה שעדיין פעיל), ציין מקום ושעה, וחבר את האירועים למשפטים "
    "זורמים. כללים מחייבים: אל תוסיף שום עובדה, מספר, שם או מקום שלא מופיעים באירועים. אל תנחש סיבות או השלכות. "
    "דיווח ממקור אחד תאר כ'דיווח ראשוני'. אירוע שהסתיים תאר בלשון עבר. בלי המלצות, בלי סימני קריאה, בלי אימוג'י. "
    "אם יש רק אירועים בחומרה נמוכה – כתוב משפט אחד שהאזור שקט יחסית ומה הדבר הבולט. "
    "החזר JSON בלבד: {\"stories\": {\"<מזהה אזור>\": \"<תקציר>\"}} עם מפתח לכל אזור שקיבלת."
)


def _ts(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _place(e: dict) -> str:
    return (e.get("location") or {}).get("name") or (e.get("places") or [""])[0] or ""


def _national(e: dict, n_regions: int) -> bool:
    return "כל הארץ" in (e.get("places") or []) or len(e.get("regions") or []) >= n_regions


def facts_for(events: list[dict], region: str, now: datetime, n_regions: int) -> list[dict]:
    """האירועים שהמודל יקבל לאזור אחד, בצורה קומפקטית"""
    out = []
    for e in events:
        t = _ts(e.get("updated_at"))
        if e.get("is_demo") or not t or now - t > WINDOW:
            continue
        if region != ALL and (region not in (e.get("regions") or []) or _national(e, n_regions)):
            continue
        out.append(e)
    out.sort(key=lambda e: (-(e.get("severity") or 1), e.get("status") == "ended", -_ts(e["updated_at"]).timestamp()))
    rows = []
    for e in out[:MAX_EVENTS]:
        first = _ts(e.get("first_reported_at")) or _ts(e["updated_at"])
        text = (e.get("title") or e.get("summary") or "").strip()
        rows.append({
            "סוג": TYPE_HE.get(e.get("event_type"), "אחר"), "מקום": _place(e),
            "שעה": first.astimezone(TZ).strftime("%H:%M"), "יום": "היום" if first.astimezone(TZ).date() == now.astimezone(TZ).date() else "אתמול",
            "חומרה": SEV_HE.get(e.get("severity") or 1, "נמוך"), "מצב": "הסתיים" if e.get("status") == "ended" else "פעיל",
            "אימות": VERIF_HE.get(e.get("verification"), ""), "תיאור": text[:220],
        })
    return rows


def fingerprint(rows: list[dict]) -> str:
    key = json.dumps([[r["סוג"], r["מקום"], r["שעה"], r["חומרה"], r["מצב"]] for r in rows], ensure_ascii=False)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def check(story: str, rows: list[dict], place_names: set[str]) -> str | None:
    """מחזיר סיבה לפסילה, או None אם הסיפור עבר את הבדיקה"""
    if not isinstance(story, str) or not story.strip():
        return "ריק"
    if len(story) > 600:
        return "ארוך מדי"
    src = json.dumps(rows, ensure_ascii=False)
    for num in re.findall(r"\d+", story):
        if num not in src:
            return f"מספר שלא מופיע באירועים: {num}"
    for name in place_names:
        if len(name) >= 4 and name in story and name not in src:
            return f"מקום שלא מופיע באירועים: {name}"
    return None


def call_model(regions_rows: dict[str, list[dict]], region_titles: dict[str, str]) -> dict[str, str]:
    import requests
    token = os.environ.get("STORY_AI_TOKEN")
    if not token:
        raise RuntimeError("אין STORY_AI_TOKEN")
    payload = {rid: {"שם האזור": region_titles.get(rid, "כל הארץ"), "אירועים": rows} for rid, rows in regions_rows.items()}
    r = requests.post(API, timeout=60, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                          "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
                      json={"model": MODEL, "temperature": 0.2, "max_tokens": 2500,
                            "response_format": {"type": "json_object"},
                            "messages": [{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]})
    if r.status_code != 200:
        raise RuntimeError(f"GitHub Models החזיר {r.status_code}: {r.text[:200]}")
    content = (r.json()["choices"][0]["message"].get("content") or "").strip()
    m = re.search(r"\{.*\}", content, re.S)              # לפעמים המודל עוטף ב-```json
    if not m:
        raise RuntimeError(f"תשובה בלי JSON: {content[:200]!r}")
    data = json.loads(m.group(0))
    return data.get("stories", data)


def update(events: list[dict], region_titles: dict[str, str], place_names: set[str],
           now: datetime | None = None, call=call_model, state_path: Path = STATE) -> dict:
    """מעדכן את הסיפורים אם צריך, ומחזיר את מה שיוצג באתר: {region: {text, at}}"""
    now = now or datetime.now(timezone.utc)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    stories = state.get("stories", {})
    last_call = _ts(state.get("last_call"))
    n = len(region_titles)
    wanted, prints = {}, {}
    for rid in [ALL, *region_titles]:
        rows = facts_for(events, rid, now, n)
        if not rows:
            stories.pop(rid, None)                 # אין אירועים – אין סיפור; האפליקציה מציגה "שקט"
            continue
        fp = fingerprint(rows)
        prints[rid] = fp
        old = stories.get(rid)
        if not old or old.get("fp") != fp or now - _ts(old["at"]) > MAX_AGE - MIN_GAP:
            wanted[rid] = rows
    log = []
    enabled = call is not call_model or bool(os.environ.get("STORY_AI_TOKEN"))
    if wanted and not enabled:
        wanted = {}                                 # אין ספק AI מוגדר – האפליקציה מציגה את הרשימה הרגילה
    if wanted and (not last_call or now - last_call >= MIN_GAP):
        state["last_call"] = now.isoformat(timespec="seconds")
        try:
            got = call(wanted, region_titles)
            for rid, rows in wanted.items():
                text = (got.get(rid) or "").strip()
                why = check(text, rows, place_names)
                if why:
                    log.append(f"{rid}: נפסל ({why})")
                    stories.pop(rid, None)
                else:
                    stories[rid] = {"text": text, "at": now.isoformat(timespec="seconds"), "fp": prints[rid]}
        except Exception as err:                    # תקלה ב-AI לא מפילה את האיסוף
            log.append(f"AI לא זמין: {err}")
    elif wanted:
        log.append("ממתין – עברו פחות מ-20 דקות מהקריאה הקודמת")
    # לא מציגים סיפור שכבר לא תואם לאירועים, או ישן מדי
    stories = {rid: s for rid, s in stories.items() if rid in prints and now - _ts(s["at"]) <= MAX_AGE}
    state["stories"] = stories
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for line in log:
        print("story:", line)
    return {rid: {"text": s["text"], "at": s["at"], "current": s["fp"] == prints.get(rid)} for rid, s in stories.items()}
