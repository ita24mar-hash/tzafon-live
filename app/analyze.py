"""ניתוח הודעות לפי כללים (שלב ראשון, לפני AI).

analyze(text) מחזיר מילון באותו מבנה שמנתח AI יחזיר בעתיד, כך שאפשר להחליף מנתח בלי לשנות
את שאר המערכת. הכללים שקופים ופשוטים; הם לא "מבינים" טקסט, ולכן כל אירוע מסומן
"נותח אוטומטית לפי כללים".
"""
import re

from .gazetteer import PLACES

VERSION = "rules-1"
HEB = "֐-׿"

TYPE_RULES = [  # הסדר קובע עדיפות כשיש כמה התאמות
    ("security", r"צבע אדום|ירי רקטות|רקטות|טילים|טיל |כטב\"ם|כלי טיס עוין|חדירת מחבלים|חשש לחדירת|מחבל|פיגוע|"
                 r"יירוט|יירוטים|נפילה|נפילות|אזעק|התרעה מפיקוד העורף|התרעות|שיגור|רסיסים|חפץ חשוד|אמל\"ח|"
                 r"מרחב (?:ה)?מוגן|למרחב המוגן|הוסר החשש|פיצוצים|שובלים|עדכון ביטחוני|הנחיות התגוננות"),
    ("fire", r"שריפ|שרפה|בוער|בוערת|עלה באש|עלתה באש|לוחמי אש|צוותי כיבוי|כבאות והצלה"),
    ("accident", r"תאונ|התנגש|התהפכ|פגע וברח|הולך רגל|הולכת רגל|נפגע מרכב|נפגעה מרכב|רוכב אופנוע|קורקינט|אופניים חשמליים"),
    ("closure", r"חסימ|נחסם|נחסמה|חסום|חסומה|נסגר לתנועה|נסגרה לתנועה|הסדרי תנועה|עומסי תנועה|פקק"),
    ("infrastructure", r"הפסקת חשמל|הפסקות חשמל|הפסקת מים|תקלה ב(?:חשמל|מים|תקשורת)|חברת החשמל|ביוב|פיצוץ צנרת|"
                       r"מי השתיה|מי השתייה|מי שתייה|הרתיחו|עבודות תשתית|עבודות ב(?:רחוב|כביש)"),
    ("weather", r"סערה|שיטפון|שיטפונות|הצפה|הצפות|שלג|ברד|רעידת אדמה|גשם כבד|אזהרת מזג"),
    ("hazard", r"חומ\"ס|חומרים מסוכנים|דליפ|זיהום|מפגע|נפילת עץ|קריסת"),
    ("medical", r"מד\"א|פצוע|פצועה|פצועים|נפגע|נפגעה|נפגעים|מחוסר הכרה|החייאה|נקבע מותו|נקבע מותה"),
]
SEVERE = re.compile(r"נהרג|נהרגה|הרוג|נקבע מות|אנוש|במצב קשה|פצוע קשה|פצועה קשה|פגיעה ישירה")
MEDIUM = re.compile(r"בינוני|לכודים|לכוד|נלכד|פצועים|נפגעים|חדירת מחבלים|ירי רקטות")
ENDED = re.compile(r"האירוע הסתיים|הסתיים|הוסר החשש|נפתח לתנועה|נפתחה לתנועה|כובתה|נשלטה|הושלט|יכולים לצאת")


def _pattern(name: str) -> re.Pattern:
    # תחיליות עבריות נפוצות: ב, ל, מ, ו, ה, ש, כ (עד שתיים), ולא חלק ממילה ארוכה יותר
    body = re.escape(name).replace("\\ ", r"[\s\-–]+")
    return re.compile(rf"(?<![{HEB}\w])(?:[ובלמהשכ]{{0,2}}){body}(?![{HEB}\w])")


_INDEX = []
for kind, name, aliases, lat, lon in PLACES:
    for n in [name, *aliases]:
        _INDEX.append((kind, name, _pattern(n)))
KIND_RANK = {"junction": 0, "locality": 1, "road": 2, "region": 3}   # מהמדויק לכללי


def find_places(text: str) -> list[dict]:
    hits = {}
    for kind, name, pat in _INDEX:
        m = pat.search(text)
        if m and (name not in hits or m.start() < hits[name]["pos"]):
            hits[name] = {"name": name, "kind": kind, "pos": m.start()}
    return sorted(hits.values(), key=lambda h: (KIND_RANK[h["kind"]], h["pos"]))


# מקום שמוזכר רק כיעד פינוי לבית חולים אינו מקום האירוע ("פונה לבית החולים בנהריה")
HOSPITAL = re.compile(r"(?:ל|ב|ה|ו)?(?:בית ה?חולים|בי[\"״]ח|ביה[\"״]ח|מרכז ה?רפואי|מרכז ה?רפואה|"
                      r"מלר\"ד|המיון|חדר ה?מיון)[^.,;\n]{0,45}")


# הודעה שעוסקת בזירה מחוץ לישראל. בה, אזכור כללי של "הצפון" אינו מקום האירוע.
ABROAD = re.compile(r"לבנון|לבנוני|בלבנון|חיזבאללה|הכפר השיעי|בכפר השיעי|סוריה|בסוריה|סורי|"
                    r"רצועת עזה|ברצועה|בעזה|דיווחים ערביים|כלי תקשורת בלבנון")
GENERIC = {"צפון הארץ"}


def analyze(text: str) -> dict:
    t = re.sub(r"\s+", " ", text or "")
    places = find_places(HOSPITAL.sub(" ", t))
    if places and ABROAD.search(t) and all(p["name"] in GENERIC for p in places):
        places = []   # למשל "פיצוצים בכפר בלבנון ... ליד גבול הצפון": האירוע בלבנון, לא בצפון
    etype = next((name for name, rx in TYPE_RULES if re.search(rx, t)), None)
    severity = 3 if SEVERE.search(t) else 2 if MEDIUM.search(t) else 1
    return {
        "v": VERSION,
        "north": bool(places),
        "places": [p["name"] for p in places],
        "location": places[0]["name"] if places else None,
        "type": etype,
        "severity": severity,
        "ended": bool(ENDED.search(t)),
        # ההחלטה אם להציג: דיווח (לא רעש) + מקום בצפון + סוג אירוע מזוהה
        "relevant": bool(places) and etype is not None,
    }
