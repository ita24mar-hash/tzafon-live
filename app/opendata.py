"""מקורות מידע פתוחים (לא טלגרם): רעידות אדמה ושיבושי טיסות בנתב"ג.

כל מקור מחזיר "הודעות" באותו פורמט של טלגרם (external_id, url, published_at, content), כך שהן עוברות
את אותו ניתוח ואותה בניית אירועים. הטקסט נכתב כאן, בעברית, מתוך הנתונים – אין כאן תוכן של צד שלישי.
"""
import json
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from . import net

IL = ZoneInfo("Asia/Jerusalem")
QUAKE_MIN_MAG = 3.0            # מתחת לזה לא מדווחים (לא מורגש בדרך כלל)
QUAKE_BOX = dict(minlat=29.3, maxlat=33.5, minlon=33.8, maxlon=36.2)
QUAKE_DAYS = 3
FLIGHTS_RESOURCE = "e83f763b-b7d7-479e-b172-ae981ddc6de5"   # "מאגר טיסות", רשות שדות התעופה (data.gov.il)
FLIGHTS_WINDOW_H = 3
FLIGHTS_MIN = 10               # פחות טיסות מזה בחלון – לא מסיקים כלום
CANCEL_SHARE = 0.25            # שיבוש: לפחות רבע מהטיסות בוטלו
DELAY_SHARE = 0.5              # או לפחות חצי מתעכבות ביותר משעה
AIRPORT = "נמל התעופה בן גוריון"


def _hhmm(iso_utc: str) -> str:
    return datetime.fromisoformat(iso_utc).astimezone(IL).strftime("%H:%M")


def _km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2 +
         math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def _nearest_locality(lat: float, lon: float):
    from .gazetteer import COORDS
    best = min(((name, _km(lat, lon, la, lo)) for name, (la, lo) in COORDS.items()), key=lambda x: x[1], default=None)
    return best


REGION_HE = {"DEAD SEA REGION": "באזור ים המלח", "LEBANON - SYRIA REGION": "באזור גבול לבנון-סוריה",
             "ISRAEL": "בישראל", "JORDAN": "בירדן", "EGYPT": "במצרים", "SINAI PENINSULA": "בחצי האי סיני",
             "EASTERN MEDITERRANEAN SEA": "במזרח הים התיכון", "CYPRUS REGION": "באזור קפריסין",
             "WESTERN SAUDI ARABIA": "בצפון-מערב ערב הסעודית", "GULF OF AQABA": "במפרץ אילת",
             "LEBANON": "בלבנון", "SYRIA": "בסוריה", "WEST BANK": "ביהודה ושומרון"}


def quakes(fetch=net.safe_fetch, now=None) -> list[dict]:
    """רעידות אדמה מהמרכז הסייסמולוגי האירופי-ים תיכוני (EMSC), בעוצמה 3 ומעלה, בשלושת הימים האחרונים."""
    now = now or datetime.now(timezone.utc)
    q = dict(format="json", start=(now - timedelta(days=QUAKE_DAYS)).strftime("%Y-%m-%dT%H:%M:%S"),
             minmag=QUAKE_MIN_MAG, limit=50, **QUAKE_BOX)
    status, body = fetch("https://www.seismicportal.eu/fdsnws/event/1/query?" + urlencode(q))
    if status == 204:
        return []                                        # אין רעידות בתקופה
    if status != 200:
        raise RuntimeError(f"EMSC החזיר קוד {status}")
    out = []
    for f in json.loads(body).get("features", []):
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        when = datetime.fromisoformat(p["time"].replace("Z", "+00:00")).astimezone(timezone.utc)
        mag = round(float(p["mag"]), 1)
        where = REGION_HE.get((p.get("flynn_region") or "").upper(), "")
        near = _nearest_locality(lat, lon)
        dist = f", כ-{round(near[1])} ק\"מ מ{near[0]}" if near and near[1] <= 120 else ""
        text = (f"רעידת אדמה בעוצמה {mag:.1f} {where}{dist}, בשעה {_hhmm(when.isoformat())}. "
                "מקור: המרכז הסייסמולוגי האירופי-ים תיכוני (EMSC).")
        out.append({"external_id": p.get("unid") or p.get("source_id") or when.isoformat(),
                    "url": f"https://www.seismicportal.eu/eventdetails.html?unid={p.get('unid', '')}",
                    "published_at": when.isoformat(timespec="seconds"), "content": text})
    return out


def flights(fetch=net.safe_fetch, now=None) -> list[dict]:
    """שיבושים בנתב"ג: הודעה רק אם בשלוש השעות הקרובות הרבה טיסות בוטלו או מתעכבות. אחרת – אין הודעה."""
    now = (now or datetime.now(timezone.utc)).astimezone(IL)
    status, body = fetch("https://data.gov.il/api/3/action/datastore_search?" +
                         urlencode({"resource_id": FLIGHTS_RESOURCE, "limit": 5000}))
    if status != 200:
        raise RuntimeError(f"data.gov.il החזיר קוד {status}")
    recs = json.loads(body)["result"]["records"]
    end = now + timedelta(hours=FLIGHTS_WINDOW_H)
    total = cancelled = delayed = 0
    for r in recs:
        try:
            sched = datetime.fromisoformat(r["CHSTOL"]).replace(tzinfo=IL)
        except (KeyError, TypeError, ValueError):
            continue
        if not now <= sched <= end:
            continue
        total += 1
        st = (r.get("CHRMINE") or "").upper()
        if "CANCEL" in st:
            cancelled += 1
            continue
        try:
            actual = datetime.fromisoformat(r["CHPTOL"]).replace(tzinfo=IL)
            if actual - sched >= timedelta(hours=1):
                delayed += 1
        except (KeyError, TypeError, ValueError):
            pass
    if total < FLIGHTS_MIN or (cancelled / total < CANCEL_SHARE and delayed / total < DELAY_SHARE):
        return []
    bucket = now.replace(minute=0, second=0, microsecond=0)
    parts = []
    if cancelled:
        parts.append(f"{cancelled} מתוך {total} הטיסות המתוכננות בשלוש השעות הקרובות בוטלו")
    if delayed:
        parts.append(f"{delayed} מתעכבות ביותר משעה")
    text = (f"שיבושים בטיסות ב{AIRPORT}: " + ", ".join(parts) +
            ". מקור: לוח הטיסות של רשות שדות התעופה. בדקו את מצב הטיסה שלכם מול חברת התעופה.")
    return [{"external_id": "flights-" + bucket.strftime("%Y%m%d%H"),
             "url": "https://www.iaa.gov.il/airports/ben-gurion/flight-board/",
             "published_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"), "content": text}]


ADAPTERS = {"opendata:quakes": quakes, "opendata:flights": flights}
