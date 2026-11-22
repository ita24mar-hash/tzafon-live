import asyncio
import json
import socket

import pytest

TOKEN = "test-admin-token-123456"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SEED_DEMO", "1")
    from app.db import init_db
    from app.main import app
    from app.seed import run_seed
    init_db()
    run_seed()
    run_seed()  # הרצה חוזרת לא יוצרת כפילויות

    def call(method, path, body=None, token=None):
        """קריאה ישירה לאפליקציית ה-ASGI, ללא שרת וללא ספריות נוספות."""
        path, _, query = path.partition("?")
        headers = [(b"content-type", b"application/json")]
        if token:
            headers.append((b"authorization", f"Bearer {token}".encode()))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "path": path, "raw_path": path.encode(), "query_string": query.encode(),
                 "headers": headers, "client": ("1.2.3.4", 1), "server": ("test", 80), "scheme": "http",
                 "root_path": ""}
        payload = json.dumps(body).encode() if body is not None else b""
        out = {"body": b""}

        async def receive():
            return {"type": "http.request", "body": payload, "more_body": False}

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"] = msg["status"]
                out["headers"] = dict(msg["headers"])
            elif msg["type"] == "http.response.body":
                out["body"] += msg.get("body", b"")

        asyncio.run(app(scope, receive, send))
        try:
            data = json.loads(out["body"])
        except ValueError:
            data = out["body"]
        return out["status"], data, out["headers"]

    return call


def test_feed_returns_demo_events_marked(client):
    status, events, headers = client("GET", "/api/events")
    assert status == 200 and len(events) == 5
    assert all(e["is_demo"] for e in events)
    assert b"content-security-policy" in headers


def test_event_without_location_has_no_coordinates(client):
    _, events, _ = client("GET", "/api/events")
    unknown = [e for e in events if e["location_precision"] == "unknown"]
    assert unknown and all(e["location"] is None for e in unknown)


def test_filters(client):
    _, fires, _ = client("GET", "/api/events?type=fire")
    assert [e["event_type"] for e in fires] == ["fire"]
    _, locs, _ = client("GET", "/api/locations")
    safed = next(l for l in locs if l["name_he"] == "צפת")
    _, near, _ = client("GET", f"/api/events?location_id={safed['id']}&radius_km=10")
    names = {e["location"]["name"] for e in near}
    assert "צפת" in names and "מירון" in names and "כרמיאל" not in names
    _, by_gps, _ = client("GET", "/api/events?lat=32.92&lon=35.30&radius_km=5")
    assert {e["location"]["name"] for e in by_gps} == {"כרמיאל"}
    assert client("GET", "/api/events?type=bogus")[0] == 400


def test_independent_sources_counted(client):
    _, events, _ = client("GET", "/api/events?verification=multi_source")
    assert events[0]["independent_sources"] == 2


def test_admin_requires_token(client):
    assert client("GET", "/api/admin/sources")[0] == 401
    assert client("GET", "/api/admin/sources", token="wrong")[0] == 401
    assert client("GET", "/api/admin/sources", token=TOKEN)[0] == 200


def test_source_lifecycle_and_duplicates(client):
    body = {"name": "ערוץ בדיקה", "kind": "telegram", "address": "https://t.me/s/Some_Channel"}
    status, src, _ = client("POST", "/api/admin/sources", body, TOKEN)
    assert status == 201 and src["status"] == "configured" and src["address_norm"] == "some_channel"
    # אותו ערוץ בכתיב אחר = כפילות
    status, e, _ = client("POST", "/api/admin/sources", body | {"address": "@some_channel"}, TOKEN)
    assert status == 400
    # בדיקת חיבור לטלגרם עדיין לא קיימת – המקור לא מסומן כמחובר
    status, res, _ = client("POST", f"/api/admin/sources/{src['id']}/test", token=TOKEN)
    assert res["ok"] is None and res["source"]["status"] == "configured"
    status, upd, _ = client("PATCH", f"/api/admin/sources/{src['id']}", {"enabled": False, "priority": 5}, TOKEN)
    assert upd["enabled"] is False and upd["priority"] == 5
    _, log, _ = client("GET", "/api/admin/audit", token=TOKEN)
    assert {x["action"] for x in log} >= {"create", "check", "update"}
    assert client("DELETE", f"/api/admin/sources/{src['id']}", token=TOKEN)[0] == 200


def test_invalid_sources_rejected(client):
    bad = [
        {"name": "x", "kind": "telegram", "address": "https://t.me/+AbCdEf123"},
        {"name": "x", "kind": "rss", "address": "ftp://example.com/feed"},
        {"name": "", "kind": "rss", "address": "https://example.com/feed"},
        {"name": "x", "kind": "nope", "address": "https://example.com"},
    ]
    for b in bad:
        assert client("POST", "/api/admin/sources", b, TOKEN)[0] in (400, 422)


def test_internal_address_blocked_on_check(client):
    body = {"name": "פנימי", "kind": "rss", "address": "http://127.0.0.1/feed"}
    _, src, _ = client("POST", "/api/admin/sources", body, TOKEN)
    _, res, _ = client("POST", f"/api/admin/sources/{src['id']}/test", token=TOKEN)
    assert res["ok"] is False and res["source"]["status"] == "error"


def test_ssrf_guard():
    from app.net import UnsafeURL, check_url

    def fake(ip):
        return lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    assert check_url("https://example.com/feed", resolver=fake("93.184.216.34"))
    for ip in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "::1", "::ffff:10.0.0.1"):
        with pytest.raises(UnsafeURL):
            check_url("https://example.com/", resolver=fake(ip))
    for url in ("file:///etc/passwd", "http://user:pw@example.com/", "http://example.com:8080/"):
        with pytest.raises(UnsafeURL):
            check_url(url, resolver=fake("93.184.216.34"))


def test_feed_parser():
    from app.net import count_feed_items
    rss = b"<rss><channel><item><title>a</title></item><item/></channel></rss>"
    assert count_feed_items(rss) == 2
    with pytest.raises(ValueError):
        count_feed_items(b'<!DOCTYPE x [<!ENTITY a "b">]><rss/>')


def test_db_blocks_duplicate_reports(client, tmp_path):
    import sqlite3
    from app.db import connect
    with pytest.raises(sqlite3.IntegrityError):
        with connect() as con:
            con.execute("INSERT INTO raw_reports(source_id, external_id, published_at, ingested_at, content,"
                        " content_hash) SELECT source_id, external_id, published_at, ingested_at, content,"
                        " content_hash FROM raw_reports LIMIT 1")
