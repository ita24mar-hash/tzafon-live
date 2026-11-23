"""בדיקה: מקורות לאזהרות מזג אוויר – פידים של השירות המטאורולוגי ו-Open-Meteo. קריאה בלבד."""
import requests
from app import feeds

H = {"User-Agent": "Mozilla/5.0 (TzafonLive weather check)"}
for url in ["https://ims.gov.il/sites/default/files/ims_data/rss/alert/rssAlert_general_country_he.xml",
            "https://ims.gov.il/sites/default/files/ims_data/rss/alert/rssAlert_general_country_en.xml",
            "https://ims.gov.il/sites/default/files/ims_data/rss/forecast_country/rssForecastCountry_he.xml",
            "https://ims.gov.il/he/rss", "https://ims.gov.il/he/RSS_ForecastAlerts"]:
    try:
        r = requests.get(url, headers=H, timeout=30)
        print("URL", url, r.status_code, r.headers.get("content-type"), len(r.content))
        if r.ok:
            try:
                items = feeds.parse_feed(r.content)
                print("  ITEMS", len(items))
                for it in items[:4]:
                    print("  IT", it["published_at"], "|", it["content"][:200].replace("\n", " "))
            except Exception as e:
                print("  PARSE", type(e).__name__, str(e)[:100], "|", r.text[:200].replace("\n", " "))
    except Exception as e:
        print("ERR", url, type(e).__name__, e)
r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=30, params={
    "latitude": "33.2,32.8,31.8,31.25", "longitude": "35.57,35.0,35.2,34.8",
    "daily": "precipitation_sum,wind_gusts_10m_max,temperature_2m_max", "forecast_days": 3, "timezone": "Asia/Jerusalem"})
print("OPENMETEO", r.status_code, str(r.json())[:400])
