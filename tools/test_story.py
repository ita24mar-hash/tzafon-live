"""בדיקה: קריאה קצרה ל-GitHub Models כמו שהתקציר עושה, ומדפיס מה חזר (בלי סודות)."""
import json, os
import requests
for model in ["openai/gpt-4.1-mini", "openai/gpt-4o-mini"]:
    for fmt in (True, False):
        body = {"model": model, "temperature": 0.2, "max_tokens": 200,
                "messages": [{"role": "system", "content": "החזר JSON בלבד: {\"stories\": {\"all\": \"<משפט>\"}}"},
                             {"role": "user", "content": "אירוע: שריפה ליד כרמיאל בשעה 10:00"}]}
        if fmt:
            body["response_format"] = {"type": "json_object"}
        r = requests.post("https://models.github.ai/inference/chat/completions", timeout=60,
                          headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Content-Type": "application/json"},
                          json=body)
        print("MODEL", model, "json_format", fmt, "STATUS", r.status_code, "CTYPE", r.headers.get("content-type"),
              "LEN", len(r.content), "BODY", r.text[:300].replace("\n", " "))
