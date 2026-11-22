"""בדיקה: האם אפשר לתמצת הודעה ארוכה עם מודל AI של GitHub Models, בחינם ובלי מפתח נוסף.
קורא הודעה ארוכה אמיתית מערוץ ציבורי ומבקש תמצית. לא שומר דבר."""
import os, time
import requests
from app.telegram_web import parse_preview

H = {"User-Agent": "TzafonLive/0.1"}
html = requests.get("https://t.me/s/fireisrael7777", headers=H, timeout=30).text
msgs = sorted(parse_preview(html, "fireisrael7777"), key=lambda m: -len(m["content"]))
text = msgs[0]["content"]
print("SOURCE_LEN", len(text), "chars")
for model in ["openai/gpt-4.1-mini", "openai/gpt-4o-mini", "meta/Llama-3.3-70B-Instruct"]:
    t0 = time.time()
    r = requests.post("https://models.github.ai/inference/chat/completions",
        headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Content-Type": "application/json"},
        json={"model": model, "max_tokens": 200, "temperature": 0, "messages": [
            {"role": "system", "content": "אתה עורך חדשות. סכם את ההודעה במשפט אחד או שניים בעברית, עד 200 תווים. "
             "רק עובדות שכתובות בהודעה: מה קרה, איפה, מצב הנפגעים. בלי פרשנות ובלי מידע שלא מופיע."},
            {"role": "user", "content": text}]}, timeout=60)
    print("MODEL", model, "STATUS", r.status_code, f"{time.time()-t0:.1f}s")
    if r.ok:
        print("SUMMARY", r.json()["choices"][0]["message"]["content"])
        print("USAGE", r.json().get("usage"))
    else:
        print("BODY", r.text[:300])
    for k, v in r.headers.items():
        if "ratelimit" in k.lower():
            print("HDR", k, v)
