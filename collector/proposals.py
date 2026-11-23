"""הגשת הצעות הסוכן לאישור: פותח issue ב-GitHub עם רשימה לסימון. GitHub שולח עליו התראה לבעל המאגר.

אישור: מסמנים ✓ ליד מקור, או כותבים תגובה "אשר הכל" / "דחה הכל". את העיבוד עושה collector/approve.py.
"""
import json
import os
from pathlib import Path

import requests

from collector import sources_edit as se

ROOT = Path(__file__).resolve().parent.parent
PROPOSED = ROOT / "collector" / "scout_proposed.json"   # מפתח → פרטי המועמד ומצבו (proposed/approved/rejected)
TITLE = "הצעות מקורות מהסוכן"
REGION = {"galil-elyon": "גליל עליון וגולן", "galil-maaravi": "גליל מערבי", "kineret-amakim": "כנרת והעמקים",
          "haifa": "חיפה", "sharon": "שרון", "dan": "גוש דן", "shfela": "שפלה", "jerusalem": "ירושלים",
          "south": "דרום", "yosh": "יהודה ושומרון"}


def load() -> dict:
    return json.loads(PROPOSED.read_text(encoding="utf-8")) if PROPOSED.exists() else {}


def save(d: dict) -> None:
    PROPOSED.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def line(c: dict) -> str:
    regions = ", ".join(REGION.get(r, r) for r, _ in sorted(c["regions"].items(), key=lambda x: -x[1])[:3]) or "—"
    kind = "ערוץ טלגרם" if c["kind"] == "telegram" else "אתר"
    link = c["url"] if c["kind"] == "telegram" else c["address"]
    s = (f"- [ ] `{c['key']}` **{c['title'] or c['username']}** ({kind}, "
         f"{'מומלץ' if c['verdict'] == 'recommended' else 'אפשרי'}): "
         f"{round((c['report_share'] or 0) * 100)}% מההודעות דיווחים, אזורים: {regions}, "
         f"פרסום אחרון לפני {c['age_hours']} שעות. [פתיחה]({link})")
    for t in c.get("samples", [])[:1]:
        s += f"\n  > {t}"
    return s


def main() -> int:
    cands = json.loads((ROOT / "data" / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    prop = load()
    known = se.existing_keys() | se.ignored()
    new = [c for c in cands if c["verdict"] != "unsuitable" and c["key"] and c["key"] not in prop and c["key"] not in known]
    if not new:
        print("אין הצעות חדשות להגשה")
        return 0
    body = ("הסוכן מצא מקורות שנראים רלוונטיים. **סמן ✓ ליד כל מקור שאתה מאשר**: הוא ייכנס לאיסוף תוך דקות.\n"
            "אפשר גם לכתוב תגובה: **אשר הכל** או **דחה הכל**.\n"
            "כשתסגור את ההודעה הזו, מה שלא סומן לא יוצע שוב.\n\n" + "\n".join(line(c) for c in new) +
            "\n\n<sub>כל מקור שמאושר נכנס כ\"לא רשמי\". ההודעות שלו יופיעו רק אם הן דיווחים עם מקום וסוג אירוע.</sub>")
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    r = requests.post(f"https://api.github.com/repos/{repo}/issues", timeout=30,
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                      json={"title": f"{TITLE}: {len(new)} מקורות חדשים", "body": body,
                            "assignees": [repo.split("/")[0]]})
    if r.status_code == 422:      # אם אי אפשר לשייך – בלי שיוך
        r = requests.post(f"https://api.github.com/repos/{repo}/issues", timeout=30,
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                          json={"title": f"{TITLE}: {len(new)} מקורות חדשים", "body": body})
    r.raise_for_status()
    num = r.json()["number"]
    for c in new:
        prop[c["key"]] = {"status": "proposed", "issue": num, "candidate": c}
    save(prop)
    print(f"נפתחה הצעה #{num} עם {len(new)} מקורות")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
