"""קואורדינטות ליישובים מ-OpenStreetMap (Overpass API, רישיון ODbL). שומר app/locality_coords.json."""
import json, re
from pathlib import Path
import requests

Q = """[out:json][timeout:170];
nwr["place"~"^(city|town|village|hamlet|suburb|isolated_dwelling|locality|neighbourhood)$"]["name:he"](29.45,34.20,33.35,35.92);
out center tags;"""
H = {"User-Agent": "TzafonLive/0.1 (coordinates for a civic info app)"}
for url in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]:
    try:
        r = requests.post(url, data={"data": Q}, headers=H, timeout=180)
        print("URL", url, r.status_code); r.raise_for_status(); els = r.json()["elements"]; break
    except Exception as e:
        print("ERR", url, e)
else:
    raise SystemExit(1)
print("OSM_NODES", len(els))

norm = lambda s: re.sub(r"[\s\-–'׳\"״()]+", "", (s or "").replace("קריית", "קרית"))
rank = {"city": 0, "town": 1, "village": 2, "hamlet": 3, "isolated_dwelling": 4, "locality": 5, "suburb": 6, "neighbourhood": 7}
osm = {}
for e in els:
    t = e["tags"]
    for key in ("name:he", "name", "alt_name:he", "old_name:he"):
        for n in (t.get(key) or "").split(";"):
            k = norm(n)
            if k and (k not in osm or rank[t["place"]] + (0 if e["type"] == "node" else 0.5) < osm[k][2]):
                lat, lon = (e["lat"], e["lon"]) if "lat" in e else (e["center"]["lat"], e["center"]["lon"])
                r_ = rank[t["place"]] + (0 if e["type"] == "node" else 0.5)
                osm[k] = (round(lat, 5), round(lon, 5), r_)
recs = json.loads(Path("app/localities.json").read_text(encoding="utf-8"))["records"]
out, miss = {}, []
for x in recs:
    name = re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", "", x["שם_ישוב"])).strip()
    cands = [name] + [p.strip() for p in name.split(" - ")]
    hit = next((osm[norm(c)] for c in cands if norm(c) in osm), None)
    if hit: out[name] = hit[:2]
    else: miss.append(name)
print("MATCHED", len(out), "OF", len(recs), "MISSING", len(miss))
print("MISS_SAMPLE", " | ".join(miss[:80]))
Path("app/locality_coords.json").write_text(json.dumps(
    {"source": "OpenStreetMap contributors (ODbL), via Overpass API", "coords": out}, ensure_ascii=False), encoding="utf-8")
