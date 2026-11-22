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
        ids, active = {}, []
        for s in json.loads(Path(args.sources).read_text(encoding="utf-8")):
            src = repo.create_source(con, repo.SourceIn(**s), "collector")
            ids[src["address_norm"]] = src["id"]
            if src["enabled"] and src["kind"] == "telegram":
                active.append(src)
        loaded = ingest.load_log(con, Path(args.log), ids)
        for sid in ids.values():
            ingest.mark_ingested(con, sid)

        for src in active:
            res = {"source": src["name"], "new": 0, "edited": 0, "seen": 0, "error": None}
            try:
                kwargs = {"fetch": fetch} if fetch else {}
                messages = telegram_web.fetch_channel(src["address_norm"], **kwargs)
                stamp = now_iso()
                for m in messages:
                    outcome = ingest.upsert_report(con, src["id"], m, stamp)
                    res["seen"] += 1
                    if outcome in res:
                        res[outcome] += 1
                repo.record_check(con, src["id"], True, f"נקראו {len(messages)} הודעות", "collector")
                ingest.mark_ingested(con, src["id"])
            except Exception as e:  # מקור אחד שנכשל לא עוצר את האחרים
                res["error"] = str(e) if isinstance(e, (RuntimeError, ValueError)) else type(e).__name__
                repo.record_check(con, src["id"], False, res["error"], "collector")
            results.append(res)

        ok = bool(results) and all(r["error"] is None for r in results)
        pruned = ingest.prune(con, int(os.environ.get("MAX_REPORTS_PER_SOURCE", "2000")))
        con.execute("UPDATE sources SET ingested_count ="
                    " (SELECT COUNT(*) FROM raw_reports WHERE source_id = sources.id) WHERE is_demo = 0")
        total = ingest.save_log(con, Path(args.log))
        export_site(con, Path(args.out), results, now_iso(), ok)

    report(results, loaded, total, ok)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"ok": ok, "results": results, "total": total, "pruned": pruned}


def export_site(con, out: Path, results: list, generated_at: str, run_ok: bool) -> None:
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
    sources = [{k: s[k] for k in ("name", "kind", "address", "is_official", "enabled", "status", "priority",
                                  "last_check_at", "last_error", "last_ingest_at", "ingested_count", "is_demo")}
               for s in repo.list_sources(con)]
    last = con.execute("SELECT MAX(ingested_at) AS t FROM raw_reports WHERE is_demo = 0").fetchone()["t"]
    meta = repo.meta(con) | {"generated_at": generated_at, "static": True, "collector": results,
                             "run_ok": run_ok, "last_message_ingested_at": last}
    files = {"events": repo.list_events(con), "locations": repo.list_locations(con), "meta": meta,
             "raw": ingest.list_raw_reports(con, 300), "sources": sources}
    for name, payload in files.items():
        (data / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def report(results, loaded, total, ok) -> None:
    lines = ["## צפון LIVE – סיכום הרצת איסוף", "",
             f"- הודעות שנשמרו מהרצות קודמות: {loaded}", f"- סך הכול ביומן כעת: {total}", ""]
    for r in results:
        if r["error"]:
            lines.append(f"- ❌ {r['source']}: {r['error']}")
        else:
            lines.append(f"- ✅ {r['source']}: נקראו {r['seen']}, חדשות {r['new']}, נערכו {r['edited']}")
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
