"""בדיקה: חיבור ל-GitHub Models – קטלוג, ושתי כתובות לבקשה. מדפיס מה חזר (בלי סודות)."""
import os
import requests
T = os.environ["GITHUB_TOKEN"]
H = {"Authorization": "Bearer " + T, "Content-Type": "application/json", "Accept": "application/vnd.github+json",
     "X-GitHub-Api-Version": "2022-11-28"}
r = requests.get("https://models.github.ai/catalog/models", headers=H, timeout=60)
print("CATALOG", r.status_code, r.headers.get("content-type"), len(r.content), r.text[:200].replace("\n", " "))
body = {"model": "openai/gpt-4.1-mini", "max_tokens": 60,
        "messages": [{"role": "user", "content": "כתוב משפט אחד: שריפה ליד כרמיאל בשעה 10:00"}]}
for url in ["https://models.github.ai/inference/chat/completions",
            "https://models.inference.ai.azure.com/chat/completions"]:
    b = dict(body, model="gpt-4.1-mini") if "azure" in url else body
    r = requests.post(url, headers=H, json=b, timeout=60, allow_redirects=False)
    print("URL", url, "STATUS", r.status_code, r.headers.get("content-type"), "LOC", r.headers.get("location"),
          "LEN", len(r.content), "BODY", r.text[:300].replace("\n", " "))
