"""הרצת איסוף אחת + בניית האתר הסטטי. מיועד ל-GitHub Actions (או להרצה ידנית).

    python -m collector.run --out _site

שלבים: בניית מסד זמני → טעינת יומן ההודעות הקבוע → קליטה מהמקורות הפעילים →
שמירת היומן → ייצוא האתר. קוד היציאה תמיד 0; הצלחה/כישלון נכתבים ל-GITHUB_OUTPUT
כדי שהאתר יתעדכן גם כשמקור נכשל, והשגיאה תוצג בו.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None, fetch=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site")
    ap.add_argument("--log", default=str(ROOT / "data" / "raw_reports.jsonl"))
    ap.add_argument("--sources", default=str(ROOT / "collector" / "sources.json"))
    args = ap.parse_args(argv)

    tmp = tempfile.mkdtemp(prefix="tzafon-")
    os.environ["DATABASE_PATH"] = str(Path(tmp) / "build.db")
    os.environ["SEED_DEMO"] = "0"   # באתר הניסוי אין נתוני הדגמה כלל

    from app import ingest, repo, telegram_web
    from app.db import connect, init_db, now_iso
    from app.seed import run_seed

    init_db()
    run_seed()
    results = []
    with connect() as con:
        ids, active, extra = {}, [], {}
        for s in json.loads(Path(args.sources).read_text(encoding="utf-8")):
            src = repo.create_source(con, repo.SourceIn(**s), "collector")
            ids[src["address_norm"]] = src["id"]
            # פרטי זיהוי ותיעוד שאינם חלק מטבלת המקורות (סוג, רמת אימות, ראיה, סיבת השבתה)
            extra[src["id"]] = {k: s.get(k) for k in ("category", "identity", "evidence", "note")}
            if src["enabled"] and src["kind"] == "telegram":
                active.append(src)
        loaded = ingest.load_log(con, Path(args.log), ids)
        names = {v: k for k, v in ids.items()}
        for sid in ids.values():
            ingest.mark_ingested(con, sid)

        for src in active:
            res = {"source": src["name"], "new": 0, "edited": 0, "seen": 0, "error": None,
                   "new_recent": 0, "new_historical": 0, "newest_published_at": None, "fresh": None,
                   "gap": 0, "source_id": src["id"]}
            try:
                if fetch is None and active.index(src):
                    time.sleep(1.5)   # לא להעמיס על טלגרם
                kwargs = {"fetch": fetch} if fetch else {}
                messages = telegram_web.fetch_channel(src["address_norm"], **kwargs)
                stamp = now_iso()
                res["gap"] = ingest.detect_gap(con, src["id"], messages)
                if res["gap"]:
                    print(f"::warning::{src['name']}: ייתכן שהוחמצו עד {res['gap']} הודעות בין ההרצות "
                          "(הדף הציבורי מציג רק את 20 האחרונות)")
                for m in messages:
                    outcome = ingest.upsert_report(con, src["id"], m, stamp)
                    res["seen"] += 1
                    if outcome in res:
                        res[outcome] += 1
                    if outcome == "new":
                        key = "new_historical" if ingest.is_historical(m["published_at"], stamp) else "new_recent"
                        res[key] += 1
                repo.record_check(con, src["id"], True, f"נקראו {len(messages)} הודעות", "collector")
                ingest.mark_ingested(con, src["id"])
            except Exception as e:  # מקור אחד שנכשל לא עוצר את האחרים
                res["error"] = str(e) if isinstance(e, (RuntimeError, ValueError)) else type(e).__name__
                repo.record_check(con, src["id"], False, res["error"], "collector")
            results.append(res)

        ok = bool(results) and all(r["error"] is None for r in results)
        fresh = ingest.source_freshness(con)
        for src, res in zip(active, results):
            f = fresh.get(src["id"], {})
            res["newest_published_at"], res["fresh"] = f.get("newest_published_at"), f.get("fresh")
        pruned = ingest.prune(con, int(os.environ.get("MAX_REPORTS_PER_SOURCE", "2000")))
        con.execute("UPDATE sources SET ingested_count ="
                    " (SELECT COUNT(*) FROM raw_reports WHERE source_id = sources.id) WHERE is_demo = 0")
        total = ingest.save_log(con, Path(args.log))
        export_site(con, Path(args.out), results, now_iso(), ok, extra)

    report(results, loaded, total, ok)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"ok": ok, "results": results, "total": total, "pruned": pruned}


def export_site(con, out: Path, results: list, generated_at: str, run_ok: bool, extra=None) -> None:
    from app import ingest, repo
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out)
    index = out / "index.html"
    index.write_text(index.read_text(encoding="utf-8").replace(
        '<html lang="he" dir="rtl">', '<html lang="he" dir="rtl" data-static="1">'), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    data = out / "data"
    data.mkdir()
    fresh = ingest.source_freshness(con)
    extra = extra or {}
    gaps = {r["source_id"]: r["gap"] for r in results}
    sources = [{k: s[k] for k in ("name", "kind", "address", "is_official", "enabled", "status", "priority",
                                  "last_check_at", "last_error", "last_ingest_at", "ingested_count", "is_demo")}
               | {"newest_published_at": fresh.get(s["id"], {}).get("newest_published_at"),
                  "url": f"https://t.me/{s['address_norm']}" if s["kind"] == "telegram" else s["address"],
                  "last_gap": gaps.get(s["id"], 0)}
               | extra.get(s["id"], {})
               for s in repo.list_sources(con)]
    newest = con.execute("SELECT MAX(published_at) AS t FROM raw_reports WHERE is_demo = 0").fetchone()["t"]
    meta = repo.meta(con) | {"generated_at": generated_at, "static": True, "collector": results,
                             "run_ok": run_ok, "newest_published_at": newest,
                             "fresh_hours": ingest.FRESH_HOURS}
    files = {"events": repo.list_events(con), "locations": repo.list_locations(con), "meta": meta,
             "raw": ingest.list_raw_reports(con, 300), "sources": sources}
    for name, payload in files.items():
        (data / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def report(results, loaded, total, ok) -> None:
    lines = ["## צפון LIVE – סיכום הרצת איסוף", "",
             f"- הודעות שנשמרו מהרצות קודמות: {loaded}", f"- סך הכול ביומן כעת: {total}", ""]
    for r in results:
        if r["error"]:
            lines.append(f"- ❌ {r['source']}: הקריאה נכשלה – {r['error']}")
            continue
        lines.append(f"- ✅ {r['source']}: הקריאה הצליחה. נקראו {r['seen']}; חדשות למערכת {r['new']}"
                     f" (מתוכן עדכניות {r['new_recent']}, היסטוריות {r['new_historical']}); נערכו {r['edited']}")
        lines.append(f"  - הודעה אחרונה שפורסמה במקור: {r['newest_published_at'] or 'אין'}")
        if r["gap"]:
            lines.append(f"  - ⚠️ ייתכן שהוחמצו עד {r['gap']} הודעות בין ההרצות")
        if not r["fresh"]:
            warn = f"{r['source']}: המקור לא פרסם הודעה ב-24 השעות האחרונות. קריאה מוצלחת אינה אומרת שהמקור עדכני."
            lines.append(f"  - ⚠️ {warn}")
            print(f"::warning::{warn}")
    if not results:
        lines.append("- ❌ אין מקור טלגרם פעיל ב-collector/sources.json")
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"ok={'true' if ok else 'false'}\n")


if __name__ == "__main__":
    main()
    sys.exit(0)
