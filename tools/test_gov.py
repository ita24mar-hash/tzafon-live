"""בדיקה: פידי RSS של gov.il (משרד הבריאות ועוד). קריאה בלבד."""
import re
import requests
from app import feeds

H = {"User-Agent": "Mozilla/5.0 (compatible; TzafonLive/0.1; +https://ita24mar-hash.github.io/tzafon-live/)",
     "Accept": "text/html,application/xml,application/rss+xml,*/*"}
pages = ["https://www.gov.il/he/departments/ministry_of_health/RSS", "https://www.gov.il/he/Departments/ministry_of_energy/RSS",
         "https://www.gov.il/he/departments/ministry_of_environmental_protection/RSS"]
found = set()
for u in pages:
    try:
        r = requests.get(u, headers=H, timeout=30)
        links = set(re.findall(r"https?://www\.gov\.il/[^\"'<> ]*rss[^\"'<> ]*", r.text, re.I)) | \
                {"https://www.gov.il" + x for x in re.findall(r"\"(/he/api/[^\"]*rss[^\"]*)\"", r.text, re.I)}
        print("PAGE", u, r.status_code, len(r.text), "links", len(links), "| server", r.headers.get("server"), r.headers.get("cf-ray", ""))
        print("  HEAD", r.text[:200].replace("\n", " "))
        for l in sorted(links)[:15]:
            print("  LINK", l)
        found |= links
    except Exception as e:
        print("ERR", u, type(e).__name__, e)
tests = sorted(found)[:12] + ["https://www.gov.il/he/api/ServiceApi/rss/48eaee91-0c97-4ef3-b364-50ae52e3b56f"]
for u in tests:
    try:
        r = requests.get(u, headers=H, timeout=30)
        print("FEED", u, r.status_code, r.headers.get("content-type"), len(r.content))
        if r.ok:
            try:
                items = feeds.parse_feed(r.content)
                print("  ITEMS", len(items))
                for it in items[:3]:
                    print("  IT", it["published_at"], "|", it["content"][:140].replace("\n", " "))
            except Exception as e:
                print("  PARSE", type(e).__name__, str(e)[:80], "|", r.text[:150].replace("\n", " "))
    except Exception as e:
        print("ERR", u, type(e).__name__, e)
