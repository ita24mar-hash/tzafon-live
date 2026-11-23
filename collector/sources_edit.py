"""הוספת מקור לרשימה (collector/sources.json, אובייקט אחד בכל שורה) ורשימת הדחויים של הסוכן."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "collector" / "sources.json"
IGNORE = ROOT / "collector" / "scout_ignore.json"


def key(kind: str, address: str) -> str:
    """מזהה אחיד למקור: tg:<ערוץ> או rss:<כתובת>."""
    if kind == "telegram":
        return "tg:" + address.rstrip("/").split("/")[-1].lstrip("@").lower()
    return "rss:" + address.strip().lower()


def existing_keys() -> set[str]:
    return {key(s["kind"], s["address"]) for s in json.loads(SOURCES.read_text(encoding="utf-8"))}


def add_source(entry: dict) -> bool:
    """מוסיף מקור אם אינו קיים. מחזיר True אם נוסף."""
    if key(entry["kind"], entry["address"]) in existing_keys():
        return False
    lines = SOURCES.read_text(encoding="utf-8").rstrip().splitlines()
    assert lines[-1].strip() == "]"
    if not lines[-2].rstrip().endswith(","):
        lines[-2] = lines[-2].rstrip() + ","
    lines.insert(-1, "  " + json.dumps(entry, ensure_ascii=False))
    SOURCES.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json.loads(SOURCES.read_text(encoding="utf-8"))          # לוודא שהקובץ עדיין תקין
    return True


def ignore(k: str) -> None:
    cur = json.loads(IGNORE.read_text(encoding="utf-8")) if IGNORE.exists() else []
    if k not in cur:
        cur.append(k)
        IGNORE.write_text(json.dumps(cur, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")


def ignored() -> set[str]:
    if not IGNORE.exists():
        return set()
    # תאימות לאחור: שמות ערוצים בלי קידומת
    return {x if ":" in x else "tg:" + x.lower() for x in json.loads(IGNORE.read_text(encoding="utf-8"))}


def entry_from_candidate(c: dict, how: str) -> dict:
    tg = c["kind"] == "telegram"
    stats = f"בבדיקת הסוכן: {round((c.get('report_share') or 0) * 100)}% מההודעות היו דיווחים"
    return {"name": f"{(c.get('title') or c['username'] if tg else c.get('title') or c['address']).strip()} (לא רשמי)",
            "kind": c["kind"], "address": c["url"] if tg else c["address"], "is_official": False, "enabled": True,
            "category": "חדשות", "identity": "unofficial",
            "evidence": ("ערוץ טלגרם" if tg else "פיד של אתר") + " שהסוכן מצא; לא נבדק מול גוף רשמי",
            "note": f"{how}. {stats}"}
