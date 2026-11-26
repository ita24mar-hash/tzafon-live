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
    bad = re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|(?<![\w/.-])sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}"
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


def test_gap_detection_and_source_metadata(tmp_path):
    from collector.run import main
    srcs = tmp_path / "s.json"
    srcs.write_text(json.dumps([{"name": "ערוץ בדיקה", "kind": "telegram", "address": "https://t.me/Test_Channel",
                                 "is_official": True, "category": "בדיקה", "identity": "official_link",
                                 "evidence": "ראיה", "note": "הערה"}]), encoding="utf-8")
    argv = ["--out", str(tmp_path / "site"), "--log", str(tmp_path / "raw.jsonl"), "--sources", str(srcs)]
    first = main(argv, fetch=lambda u: (200, FIXTURE))                     # 101-103, הרצה ראשונה: אין פער
    assert first["results"][0]["gap"] == 0
    jumped = FIXTURE.replace(b"Test_Channel/101", b"Test_Channel/110").replace(b"Test_Channel/102", b"Test_Channel/111") \
                    .replace(b"Test_Channel/103", b"Test_Channel/112")
    second = main(argv, fetch=lambda u: (200, jumped))                     # 104-109 לא נראו
    assert second["results"][0]["gap"] == 6
    src = by_name(tmp_path / "site")["ערוץ בדיקה"]
    assert src["last_gap"] == 6 and src["identity"] == "official_link" and src["url"] == "https://t.me/test_channel"
    assert src["category"] == "בדיקה" and src["note"] == "הערה"


def test_real_sources_file_is_consistent():
    """רשימת המקורות האמיתית: אין כפילויות, מקור 'רשמי' רק עם ראיה, ולכל מקור מושבת יש סיבה."""
    from app.repo import SourceIn, normalize_address
    data = json.loads((Path(__file__).resolve().parent.parent / "collector" / "sources.json").read_text("utf-8"))
    norms = [normalize_address(s["kind"], s["address"]) for s in data]
    assert len(norms) == len(set(norms))
    for s in data:
        SourceIn(**s)
        if s["is_official"]:
            assert s["identity"] in ("telegram_verified", "official_link") and s["evidence"]
        if not s["enabled"]:
            assert s["note"].startswith("לא הופעל")
    assert 1 <= sum(s["enabled"] for s in data) <= 60          # תקרה כדי שכל הרצה תישאר קצרה (~1.5 שניות לערוץ)


def test_only_excerpt_is_stored_and_edits_still_detected(tmp_path):
    from collector.run import main
    from app.ingest import excerpt
    long_text = "תאונה בכביש 89 סמוך לצומת מירון. " * 20
    page = FIXTURE.replace("עדכון</b> ראשון".encode(), long_text.encode())
    log = tmp_path / "raw.jsonl"
    argv = ["--out", str(tmp_path / "site"), "--log", str(log), "--sources", str(_sources(tmp_path))]
    main(argv, fetch=lambda u: (200, page))
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert len(rec["content"]) <= 150 and rec["content"].endswith("…")
    assert long_text.strip() not in log.read_text(encoding="utf-8")         # הטקסט המלא לא במאגר
    again = main(argv, fetch=lambda u: (200, page))                        # אותו טקסט: לא "נערך"
    assert again["results"][0]["edited"] == 0 and again["results"][0]["new"] == 0
    changed = page.replace("ראשון".encode(), "שני".encode()) .replace("שורה שנייה".encode(), "שורה אחרת".encode())
    third = main(argv, fetch=lambda u: (200, changed))                     # שינוי בסוף ההודעה מזוהה
    assert third["results"][0]["edited"] == 1
    assert excerpt(excerpt(long_text)) == excerpt(long_text)


def test_noise_classifier_on_real_examples():
    """דוגמאות אמיתיות שנקלטו מהערוצים (22.11.2026)."""
    from app.ingest import classify_noise
    noise = {
        "ללא": "קצר", "לכודים": "קצר", "מקריית שלום": "קצר", "בית שמש?": "שאלה",
        'מוכר אירוע חומ"ס בבאר שבע?': "שאלה", "איפה בכרמיאל?": "שאלה",
        "https://chat.whatsapp.com/IZl3NGdbKWBKSHh1I46zw2 כרגע זו הקבוצה הפנויה": "קבוצה",
        "תוכן שיווקי 👇": "פרסומת", "לתרומות להצלת המשפחה לחצו כאן": "פרסומת", "": "ללא טקסט",
    }
    for text, kind in noise.items():
        assert kind in (classify_noise(text) or ""), text
    reports = [
        "כפר תבור שריפה", "בב תניא שריפה", "יש שריפת רכב חשמלי", "ים גזר רכב בוער תחת בניין",
        "דוברות כבאות והצלה לישראל | מחוז חוף שריפה בבית פרטי בקריית חיים",
        "תיעוד | צה\"ל פוצץ לפני זמן קצר תשתיות טרור של חיזבאללה בכפר זוטר א-שרקיה "
        "לשליחת תיעוד מהשטח | לפרסום בערוץ 🔴 חדשות ישראל בטלגרם 🔴 https://t.me/newsil",
        "רפאל חיון: חמאס מכין רחפנים. לשליחת תיעוד מהשטח | לפרסום בערוץ",
    ]
    for text in reports:
        assert classify_noise(text) is None, text


def test_promo_and_appeals_filtered_without_hiding_news():
    from app.ingest import classify_noise
    appeals_and_ads = [
        # ההודעה האמיתית שעברה את הסינון הקודם (22.11.2026, כפי שנשמרה)
        "קריאת חירום דחופה ביותר מהרב הראשי לישראל והרב שלום ארוש‼️ עבור כלה לפני חתונתה שנמצאת "
        "בחוסר כל ממשי!! בעקבות פציעה קשה בילדותה, המשפחה נכנסה לחובות…",
        "זעקת אלמנה ויתומים: המשפחה בחוסר כל, כל סכום עוזר",
        "מבצע מטורף! מזגן אינוורטר רק 1,990 ₪ כולל התקנה, להזמנות בוואטסאפ",
        "#פרסומת הכירו את האפליקציה החדשה שתשנה לכם את החיים",
    ]
    for t in appeals_and_ads:
        assert classify_noise(t), t
    real_news = [  # הודעות אמיתיות שמכילות מילה אחת מהרשימות
        "אזהרה לציבור. חשד לניסיון הונאה! בשעות האחרונות מופצות הודעות SMS המתחזות להודעות על חובות לעירייה",
        "במאמץ מבצעי ממוקד שנמשך שבוע: כוחות הביטחון החרימו כ-15 רחפנים באיו\"ש",
        "תושבים יקרים, במסגרת היערכות לכל תרחיש חירום הנחה ראש העיר לפתוח את המקלטים הציבוריים",
        "בלשי ימ\"ר ת\"א סיכלו ניסיון הברחת סם במבצע משותף עם המכס",
        "קריאת חירום: שריפה גדולה בחורש סמוך לצפת, צוותי כיבוי בדרך",
    ]
    for t in real_news:
        assert classify_noise(t) is None, t


def test_scout_mentions_and_evaluate():
    from collector import scout
    html = ('<a class="tgme_widget_message_forwarded_from_name" href="https://t.me/Galil_News/55">x</a>'
            ' עקבו @kiryat_news ו-t.me/s/haifa_now ולא @mybot או t.me/joinchat/abc או mail@example.com')
    assert scout.mentions(html) == ["Galil_News", "haifa_now", "kiryat_news"]
    fixture = (Path(__file__).parent / "fixtures" / "preview.html").read_bytes()
    r = scout.evaluate("Test_Channel", lambda url: (200, fixture))
    assert r["messages"] > 0 and r["verdict"] in ("recommended", "possible", "unsuitable") and r["reason"]
    r = scout.evaluate("empty", lambda url: (200, b"<html></html>"))
    assert r["verdict"] == "unsuitable" and "ציבורי" in r["reason"]


def test_feed_parse_and_discovery():
    from app import feeds
    rss = """<?xml version="1.0"?><rss><channel><item><title>שריפה בנתניה</title>
      <description>&lt;p&gt;כוחות כיבוי פועלים במקום&lt;/p&gt;</description><link>https://x.co.il/a/1</link>
      <guid>abc</guid><pubDate>Mon, 23 Nov 2026 07:20:00 GMT</pubDate></item>
      <item><title>בלי תאריך</title></item></channel></rss>""".encode()
    items = feeds.parse_feed(rss)
    assert len(items) == 1 and items[0]["content"] == "שריפה בנתניה. כוחות כיבוי פועלים במקום"
    assert items[0]["published_at"] == "2026-11-23T07:20:00+00:00" and items[0]["url"] == "https://x.co.il/a/1"
    home = b'<link rel="alternate" type="application/rss+xml" title="mivzakim" href="/rss/flash.xml">'
    assert feeds.discover_feeds("https://x.co.il/", home) == [("mivzakim", "https://x.co.il/rss/flash.xml")]
    import pytest
    with pytest.raises(ValueError):
        feeds.parse_feed(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss/>')


def test_approve_parses_checked_items(tmp_path, monkeypatch):
    import json as _j
    from collector import approve, proposals, sources_edit as se
    src = tmp_path / "sources.json"
    src.write_text('[\n  {"name": "a", "kind": "telegram", "address": "https://t.me/aaaaa", "enabled": true}\n]\n', encoding="utf-8")
    monkeypatch.setattr(se, "SOURCES", src)
    monkeypatch.setattr(se, "IGNORE", tmp_path / "ignore.json")
    monkeypatch.setattr(proposals, "PROPOSED", tmp_path / "proposed.json")
    cand = lambda u: {"kind": "telegram", "key": "tg:" + u.lower(), "username": u, "url": "https://t.me/" + u,
                      "title": u, "report_share": 0.2, "regions": {}, "samples": [], "verdict": "recommended", "age_hours": 1}
    proposals.save({"tg:goodchan": {"status": "proposed", "issue": 7, "candidate": cand("goodchan")},
                    "tg:badchan": {"status": "proposed", "issue": 7, "candidate": cand("badchan")}})
    body = "- [x] `tg:goodchan` **goodchan**\n- [ ] `tg:badchan` **badchan**"
    ev = tmp_path / "ev.json"
    ev.write_text(_j.dumps({"action": "closed", "issue": {"number": 7, "body": body, "state": "closed"}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(ev))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    calls = []
    class R:
        def raise_for_status(self): pass
    monkeypatch.setattr(approve.requests, "post", lambda *a, **k: calls.append(k["json"]) or R())
    approve.main()
    assert [s["address"] for s in _j.loads(src.read_text(encoding="utf-8"))] == ["https://t.me/aaaaa", "https://t.me/goodchan"]
    assert se.ignored() == {"tg:badchan"} and "goodchan" in calls[0]["body"]


def test_opendata_quakes_and_flights():
    import json as _j
    from datetime import datetime, timezone
    from app import opendata
    from app.analyze import analyze
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    q = {"features": [
        {"properties": {"unid": "A1", "time": "2026-11-23T09:24:00Z", "mag": 4.1, "flynn_region": "DEAD SEA REGION"},
         "geometry": {"coordinates": [35.45, 31.5, 10]}},
        {"properties": {"unid": "A2", "time": "2026-11-23T10:00:00Z", "mag": 3.2, "flynn_region": "LEBANON - SYRIA REGION"},
         "geometry": {"coordinates": [35.75, 33.3, 10]}}]}
    msgs = opendata.quakes(lambda url: (200, _j.dumps(q).encode()), now=now)
    assert [m["external_id"] for m in msgs] == ["A1", "A2"]
    a1, a2 = analyze(msgs[0]["content"]), analyze(msgs[1]["content"])
    assert (a1["type"], a1["severity"], a1["relevant"]) == ("earthquake", 3, True)
    assert (a2["type"], a2["severity"]) == ("earthquake", 2) and a2["north"]
    assert opendata.quakes(lambda url: (204, b""), now=now) == []

    def recs(n, cancel, delay):
        out = []
        for i in range(n):
            st = "CANCELED" if i < cancel else "DELAYED" if i < cancel + delay else "ON TIME"
            actual = "2026-11-23T16:30:00" if st == "DELAYED" else "2026-11-23T15:00:00"
            out.append({"CHSTOL": "2026-11-23T15:00:00", "CHPTOL": actual, "CHRMINE": st})
        return _j.dumps({"result": {"records": out}}).encode()
    assert opendata.flights(lambda url: (200, recs(40, 2, 3)), now=now) == []          # יום רגיל
    m = opendata.flights(lambda url: (200, recs(40, 22, 3)), now=now)
    a = analyze(m[0]["content"])
    assert (a["type"], a["severity"], a["places"]) == ("infrastructure", 3, ["נמל התעופה בן גוריון"])
    assert "22 מתוך 40" in m[0]["content"] and m[0]["external_id"] == "flights-2026112314"


def test_story_written_checked_and_rate_limited(tmp_path):
    """תקציר כסיפור: נכתב מהאירועים, נפסל אם הומצא מספר או מקום, ולא קוראים ל-AI יותר מפעם ב-20 דקות."""
    from datetime import datetime, timedelta, timezone
    from collector import story
    now = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)
    ev = lambda **o: {"event_type": "fire", "severity": 3, "status": "active", "verification": "single_source",
                      "is_demo": False, "first_reported_at": "2026-11-27T09:40:00+00:00",
                      "updated_at": "2026-11-27T09:50:00+00:00", "places": ["כרמיאל"], "regions": ["galil-maaravi"],
                      "location": {"name": "כרמיאל"}, "title": "שריפה בחורש ליד כרמיאל, 3 צוותים בשטח", **o}
    titles = {"galil-maaravi": "הגליל המערבי", "south": "הדרום"}
    places = {"כרמיאל", "אשקלון", "נהריה"}
    calls = []

    def fake(wanted, _titles):
        calls.append(sorted(wanted))
        return {"all": "דיווח ראשוני על שריפה בחורש ליד כרמיאל משעה 11:40, 3 צוותים בשטח.",
                "galil-maaravi": "שריפה ליד נהריה עם 5 צוותים."}          # ממציא מקום ומספר – ייפסל

    state = tmp_path / "stories.json"
    out = story.update([ev()], titles, places, now=now, call=fake, state_path=state)
    assert calls == [["all", "galil-maaravi"]]
    assert "כרמיאל" in out["all"]["text"] and "galil-maaravi" not in out
    # 5 דקות אחר כך, אירוע חדש – עדיין לא קוראים שוב
    out = story.update([ev(), ev(event_type="accident", places=["אשקלון"], regions=["south"], location={"name": "אשקלון"},
                                 title="תאונה באשקלון")], titles, places, now=now + timedelta(minutes=5), call=fake, state_path=state)
    assert len(calls) == 1 and out["all"]["current"] is False
    assert story.check("שריפה ב-12:00", [{"שעה": "11:40"}], set()) is not None
