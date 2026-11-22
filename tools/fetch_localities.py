"""הורדת רשימת היישובים הרשמית (רשות האוכלוסין, data.gov.il) לקובץ app/localities.json."""
import collections
import json
from pathlib import Path

import requests

RES = "5c78e9fa-c2e2-4771-93ff-7f400a12f7ba"   # רשימת ישובים בישראל - מתעדכן
H = {"User-Agent": "TzafonLive/0.1 (gazetteer)"}
r = requests.get("https://data.gov.il/api/3/action/datastore_search", params={"resource_id": RES, "limit": 32000},
                 headers=H, timeout=60)
r.raise_for_status()
res = r.json()["result"]
recs = res["records"]
print("FIELDS", [f["id"] for f in res["fields"]])
print("TOTAL", res.get("total"), "GOT", len(recs))
for x in recs[:4]:
    print("SAMPLE", json.dumps(x, ensure_ascii=False))
keys = list(recs[0].keys())
nafa_key = next((k for k in keys if "נפה" in k and "שם" in k), None)
print("NAFA_KEY", nafa_key)
if nafa_key:
    for k, v in collections.Counter((x.get(nafa_key) or "").strip() for x in recs).most_common():
        print("NAFA", repr(k), v)
out = Path("app/localities.json")
out.write_text(json.dumps({"source": "data.gov.il resource " + RES, "fields": keys, "records": recs},
                          ensure_ascii=False, indent=0), encoding="utf-8")
print("WROTE", out, out.stat().st_size)
