"""השוואת הודעות שמורות מול הקישור המקורי שלהן בטלגרם (https://t.me/<channel>/<id>?embed=1).

רץ ב-GitHub Actions אחרי האיסוף. מדווח בלבד, לא מכשיל את ההרצה: אם טלגרם לא מאפשר
לקרוא דף הודעה, נכתב "לא נבדק" – לא "תקין".
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def verify(log: Path, n: int = 5, fetch=None) -> list[dict]:
    from app import ingest, net, telegram_web
    fetch = fetch or net.safe_fetch
    recs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    recs = [r for r in recs if (r.get("url") or "").startswith("https://t.me/")]   # רק הודעות טלגרם נבדקות מול טלגרם
    recs.sort(key=lambda r: r["published_at"], reverse=True)
    out = []
    for r in recs[:n]:
        channel = r["url"].rstrip("/").split("/")[-2]
        res = {"id": r["external_id"], "url": r["url"], "status": None, "detail": ""}
        try:
            code, body = fetch(r["url"] + "?embed=1")
            live = [m for m in telegram_web.parse_preview(body.decode("utf-8", "replace"), channel)
                    if m["external_id"] == r["external_id"]]
            if code != 200 or not live:
                res["status"], res["detail"] = "unverified", f"לא ניתן לקרוא את דף ההודעה (קוד {code})"
            else:
                m = live[0]
                # משווים את טביעת האצבע של הטקסט המלא בטלגרם לזו שנשמרה (נשמר רק פתיח)
                same_text = ingest.content_hash(ingest.clean(m["content"])) == r["content_hash"]
                same_time = m["published_at"] == r["published_at"]
                res["status"] = "ok" if same_text and same_time else "mismatch"
                res["detail"] = f"טקסט {'זהה' if same_text else 'שונה'}, זמן פרסום {'זהה' if same_time else 'שונה'}" \
                                f" ({m['published_at']})"
        except Exception as e:
            res["status"], res["detail"] = "unverified", f"שגיאה: {type(e).__name__}"
        out.append(res)
    return out


def main():
    results = verify(ROOT / "data" / "raw_reports.jsonl")
    icon = {"ok": "✅", "mismatch": "❌", "unverified": "⚪"}
    lines = ["## בדיקה מול טלגרם: 5 ההודעות האחרונות מול הקישור המקורי", ""]
    lines += [f"- {icon[r['status']]} {r['id']}: {r['detail']} – {r['url']}" for r in results]
    if not results:
        lines.append("- אין הודעות לבדוק")
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")
    if any(r["status"] == "mismatch" for r in results):
        print("::warning::נמצא פער בין הודעה שמורה לבין ההודעה המקורית בטלגרם")


if __name__ == "__main__":
    main()
    sys.exit(0)
