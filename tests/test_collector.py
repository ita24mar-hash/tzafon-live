import json
from pathlib import Path

import pytest

FIXTURE = (Path(__file__).parent / "fixtures" / "preview.html").read_bytes()


def test_parse_preview():
    from app.telegram_web import parse_preview
    msgs = parse_preview(FIXTURE.decode(), "test_channel")
    assert [m["external_id"] for m in msgs] == ["101", "102", "103"]      # 104 ללא זמן – נדחתה
    assert msgs[0]["content"] == "עדכון ראשון\nשורה שנייה & סוף קישור"
    assert msgs[0]["url"] == "https://t.me/Test_Channel/101"
    assert msgs[0]["published_at"] == "2026-10-19T17:31:00+00:00"
    assert msgs[0]["edited"] is False and msgs[1]["edited"] is True
    assert "ציטוט קודם" not in msgs[1]["content"] and "בלוק פנימי" in msgs[1]["content"]
    assert msgs[2]["content"] == ""                                         # מדיה בלבד
    assert parse_preview(FIXTURE.decode(), "other_channel") == []          # ערוץ אחר – לא נקלט


def test_fetch_errors():
    from app.telegram_web import fetch_channel
    with pytest.raises(RuntimeError):
        fetch_channel("x", fetch=lambda url: (404, b""))
    with pytest.raises(RuntimeError):
        fetch_channel("x", fetch=lambda url: (200, b"<html>no posts</html>"))


def by_name(out):
    return {s["name"]: s for s in json.loads((out / "data" / "sources.json").read_text(encoding="utf-8"))}


def _sources(tmp_path):
    p = tmp_path / "sources.json"
    p.write_text(json.dumps([
        {"name": "ערוץ בדיקה", "kind": "telegram", "address": "https://t.me/Test_Channel", "is_official": True},
        {"name": "כבוי", "kind": "telegram", "address": "@other_one", "enabled": False},
    ]), encoding="utf-8")
    return p


def test_run_persists_and_dedupes(tmp_path):
    from collector.run import main
    log, out = tmp_path / "data" / "raw.jsonl", tmp_path / "site"
    argv = ["--out", str(out), "--log", str(log), "--sources", str(_sources(tmp_path))]
    calls = []

    def fetch(url):
        calls.append(url)
        return 200, FIXTURE

    first = main(argv, fetch=fetch)
    assert calls == ["https://t.me/s/test_channel"]                         # מקור כבוי לא נקרא
    assert first["ok"] and first["results"][0]["new"] == 3 and first["total"] == 3
    saved = log.read_text(encoding="utf-8")

    # הרצה שנייה: מסד חדש לגמרי, אותן הודעות – אין כפילויות והיומן זהה בייט-בייט
    second = main(argv, fetch=fetch)
    assert second["results"][0]["new"] == 0 and second["total"] == 3
    assert log.read_text(encoding="utf-8") == saved

    # הודעה שנערכה + הודעה חדשה
    changed = FIXTURE.replace("ראשון".encode(), "מתוקן".encode()).replace(b"Test_Channel/103", b"Test_Channel/105")
    third = main(argv, fetch=lambda url: (200, changed))
    r = third["results"][0]
    assert (r["new"], r["edited"], third["total"]) == (1, 1, 4)
    recs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [x["external_id"] for x in recs] == ["101", "102", "103", "105"]  # 103 נשמרה אף שירדה מהדף
    assert recs[0]["edited_at"] and "מתוקן" in recs[0]["content"]

    # האתר הסטטי
    raw = json.loads((out / "data" / "raw.json").read_text(encoding="utf-8"))
    assert len(raw) == 4 and raw[0]["external_id"] == "105" and raw[0]["is_official"] is True
    assert "050-1234567" not in json.dumps(raw)                             # טלפון מוסתר בתצוגה
    assert "050-1234567" not in log.read_text(encoding="utf-8")             # וגם ביומן הציבורי
    assert "[מספר הוסר]" in log.read_text(encoding="utf-8")
    meta = json.loads((out / "data" / "meta.json").read_text(encoding="utf-8"))
    assert meta["demo_events"] == 0 and meta["real_reports_ingested"] == 4
    assert meta["run_ok"] is True and meta["generated_at"]
    assert meta["newest_published_at"] == "2026-10-20T06:00:00+00:00"
    # כל הודעות הדוגמה ישנות מ-24 שעות ברגע הקליטה → היסטוריות, ולא נספרו כעדכניות
    assert all(x["historical"] for x in raw)
    r1 = first["results"][0]
    assert (r1["new_recent"], r1["new_historical"], r1["fresh"]) == (0, 3, False)
    assert by_name(out)["ערוץ בדיקה"]["newest_published_at"] == "2026-10-20T06:00:00+00:00"
    assert json.loads((out / "data" / "events.json").read_text(encoding="utf-8")) == []
    src = json.loads((out / "data" / "sources.json").read_text(encoding="utf-8"))
    by = {s["name"]: s for s in src}
    assert by["ערוץ בדיקה"]["status"] == "ingesting" and by["כבוי"]["status"] == "configured"
    assert 'data-static="1"' in (out / "index.html").read_text(encoding="utf-8")


def test_failed_source_keeps_old_data(tmp_path):
    from collector.run import main
    log, out = tmp_path / "raw.jsonl", tmp_path / "site"
    argv = ["--out", str(out), "--log", str(log), "--sources", str(_sources(tmp_path))]
    main(argv, fetch=lambda url: (200, FIXTURE))
    res = main(argv, fetch=lambda url: (500, b""))
    assert res["ok"] is False and res["total"] == 3                          # שום דבר לא נמחק
    src = json.loads((out / "data" / "sources.json").read_text(encoding="utf-8"))
    assert src[0]["status"] == "error" and src[0]["last_error"]
    assert len(json.loads((out / "data" / "raw.json").read_text(encoding="utf-8"))) == 3


def test_size_limit_keeps_newest(tmp_path, monkeypatch):
    from collector.run import main
    monkeypatch.setenv("MAX_REPORTS_PER_SOURCE", "2")
    log, out = tmp_path / "raw.jsonl", tmp_path / "site"
    argv = ["--out", str(out), "--log", str(log), "--sources", str(_sources(tmp_path))]
    res = main(argv, fetch=lambda url: (200, FIXTURE))
    assert res["total"] == 2 and res["pruned"] == 1
    ids = [json.loads(x)["external_id"] for x in log.read_text(encoding="utf-8").splitlines()]
    assert ids == ["102", "103"]                                             # הישנה ביותר הוסרה
    src = json.loads((out / "data" / "sources.json").read_text(encoding="utf-8"))
    assert src[0]["ingested_count"] == 2


def test_repo_has_no_secrets():
    """סורק את כל קובצי המאגר לדפוסים של מפתחות, סיסמאות וכתובות אימייל."""
    import re
    import subprocess
    root = Path(__file__).resolve().parent.parent
    try:
        files = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).split()
    except Exception:
        pytest.skip("לא מאגר git")
    bad = re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
                     r"|BEGIN [A-Z ]*PRIVATE KEY|[\w.+-]+@(?!users\.noreply)[\w-]+\.(?:com|net|org|il)\b")
    hits = []
    for f in files:
        if f.endswith((".session", ".env", ".db")):
            hits.append(f)
            continue
        text = (root / f).read_text(encoding="utf-8", errors="ignore")
        hits += [f"{f}: {m.group(0)}" for m in bad.finditer(text) if "example.com" not in m.group(0)]
    assert hits == []


def _fresh_fixture(minutes_ago: int) -> bytes:
    from datetime import datetime, timedelta, timezone
    t = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    return FIXTURE.replace(b"2026-10-20T06:00:00+00:00", t.encode())


def test_recent_message_counted_as_recent(tmp_path):
    from collector.run import main
    argv = ["--out", str(tmp_path / "site"), "--log", str(tmp_path / "raw.jsonl"),
            "--sources", str(_sources(tmp_path))]
    res = main(argv, fetch=lambda url: (200, _fresh_fixture(30)))
    r = res["results"][0]
    assert (r["new_recent"], r["new_historical"], r["fresh"]) == (1, 2, True)
    raw = {x["external_id"]: x for x in json.loads((tmp_path / "site" / "data" / "raw.json").read_text("utf-8"))}
    assert raw["103"]["historical"] is False and raw["101"]["historical"] is True


def test_historical_rule():
    from app.ingest import is_historical
    assert is_historical("2026-11-13T01:00:00+00:00", "2026-11-22T18:15:00+00:00")
    assert not is_historical("2026-11-22T10:00:00+00:00", "2026-11-22T18:15:00+00:00")
    assert not is_historical("2026-11-21T18:16:00+00:00", "2026-11-22T18:15:00+00:00")


def test_verify_against_original_links(tmp_path):
    from collector.run import main
    from collector.verify import verify
    log = tmp_path / "raw.jsonl"
    argv = ["--out", str(tmp_path / "site"), "--log", str(log), "--sources", str(_sources(tmp_path))]
    main(argv, fetch=lambda url: (200, FIXTURE))
    urls = []

    def fetch(url):
        urls.append(url)
        return 200, FIXTURE
    res = verify(log, fetch=fetch)
    assert urls[0] == "https://t.me/Test_Channel/103?embed=1"
    assert [r["status"] for r in res] == ["ok", "ok", "ok"]
    changed = FIXTURE.replace("ראשון".encode(), "אחר".encode())
    res = {r["id"]: r["status"] for r in verify(log, fetch=lambda u: (200, changed))}
    assert res["101"] == "mismatch" and res["102"] == "ok"
    assert {r["status"] for r in verify(log, fetch=lambda u: (403, b""))} == {"unverified"}
