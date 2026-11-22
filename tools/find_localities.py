"""חיפוש מאגר היישובים הרשמי ב-data.gov.il (רץ ב-GitHub Actions, קריאה בלבד)."""
import json
import requests

H = {"User-Agent": "TzafonLive/0.1 (gazetteer discovery)"}
for q in ["יישובים", "רשימת יישובים", "שמות יישובים", "localities"]:
    try:
        r = requests.get("https://data.gov.il/api/3/action/package_search", params={"q": q, "rows": 8}, headers=H, timeout=30)
        print(f"=== q={q} status={r.status_code}")
        for pkg in r.json()["result"]["results"]:
            print("PKG", pkg["name"], "|", pkg.get("title"), "|", pkg.get("organization", {}).get("title"))
            for res in pkg.get("resources", []):
                print("   RES", res.get("id"), res.get("format"), res.get("datastore_active"), "|", res.get("name"), "|", res.get("url"))
    except Exception as e:
        print("ERR", q, type(e).__name__, e)
