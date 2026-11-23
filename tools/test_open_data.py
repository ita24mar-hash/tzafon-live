"""בדיקה: מקורות מידע פתוחים – רעידות אדמה (USGS, EMSC) וטיסות (data.gov.il). קריאה בלבד."""
import json
from datetime import datetime, timedelta, timezone
import requests

H = {"User-Agent": "TzafonLive/0.1 (open data check)"}
since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
box = dict(minlatitude=29.3, maxlatitude=33.5, minlongitude=33.8, maxlongitude=36.2)

print("=== USGS")
try:
    r = requests.get("https://earthquake.usgs.gov/fdsnws/event/1/query", headers=H, timeout=40,
                     params=dict(format="geojson", starttime=since, minmagnitude=2, orderby="time", **box))
    f = r.json()["features"]
    print("STATUS", r.status_code, "COUNT_60D", len(f))
    for x in f[:5]:
        p = x["properties"]
        print("EQ", datetime.fromtimestamp(p["time"] / 1000, timezone.utc).isoformat()[:16], p["mag"], p["place"])
except Exception as e:
    print("ERR", type(e).__name__, e)

print("=== EMSC")
try:
    r = requests.get("https://www.seismicportal.eu/fdsnws/event/1/query", headers=H, timeout=40,
                     params=dict(format="json", start=since, minmag=1.5, limit=200, minlat=29.3, maxlat=33.5, minlon=33.8, maxlon=36.2))
    f = r.json()["features"]
    print("STATUS", r.status_code, "COUNT_60D", len(f))
    for x in f[:5]:
        p = x["properties"]
        print("EQ", p["time"][:16], p["mag"], p.get("flynn_region"))
except Exception as e:
    print("ERR", type(e).__name__, e)

print("=== data.gov.il flights")
for q in ["טיסות", "flights", "רשות שדות התעופה", "flydata"]:
    try:
        r = requests.get("https://data.gov.il/api/3/action/package_search", params={"q": q, "rows": 5}, headers=H, timeout=30)
        for pkg in r.json()["result"]["results"]:
            print("PKG", q, "|", pkg["name"], "|", pkg.get("title"), "|", pkg.get("metadata_modified", "")[:10])
            for res in pkg.get("resources", [])[:3]:
                print("   RES", res.get("id"), res.get("format"), res.get("datastore_active"), "|", res.get("name"), "|", res.get("last_modified"))
    except Exception as e:
        print("ERR", q, type(e).__name__, e)
for rid in ["e83f763b-b7d7-479e-b172-ae981ddc6de5"]:
    try:
        r = requests.get("https://data.gov.il/api/3/action/datastore_search", params={"resource_id": rid, "limit": 3}, headers=H, timeout=30)
        res = r.json().get("result", {})
        print("FLY", rid, r.status_code, "TOTAL", res.get("total"))
        for x in res.get("records", [])[:3]:
            print("   REC", json.dumps(x, ensure_ascii=False)[:300])
    except Exception as e:
        print("ERR fly", type(e).__name__, e)
