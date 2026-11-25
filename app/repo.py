"""שאילתות ולוגיקת נתונים."""
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from .db import audit, now_iso
from .gazetteer import regions_for

EVENT_TYPES = ("security", "accident", "fire", "closure", "infrastructure", "weather", "hazard", "medical", "earthquake", "cyber", "health", "other")
EventType = Literal["security", "accident", "fire", "closure", "infrastructure", "weather", "hazard", "medical", "other"]
SourceKind = Literal["telegram", "rss", "api", "website", "other"]
TG_USER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: SourceKind
    address: str = Field(min_length=1, max_length=500)
    is_official: bool = False
    coverage: list[int] = Field(default_factory=list, max_length=200)
    wanted_types: list[EventType] = Field(default_factory=list)
    priority: int = Field(default=3, ge=1, le=5)
    enabled: bool = True


class SourcePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    address: Optional[str] = Field(default=None, min_length=1, max_length=500)
    is_official: Optional[bool] = None
    coverage: Optional[list[int]] = None
    wanted_types: Optional[list[EventType]] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    enabled: Optional[bool] = None


def normalize_address(kind: str, address: str) -> str:
    """מחזיר כתובת מנורמלת או זורק ValueError עם הסבר בעברית."""
    a = address.strip()
    if kind == "api" and a.startswith("opendata:"):
        from .opendata import ADAPTERS          # מקור נתונים פתוח מובנה (רעידות אדמה, טיסות)
        if a not in ADAPTERS:
            raise ValueError("מקור נתונים פתוח לא מוכר: " + a)
        return a
    if kind == "telegram":
        m = re.match(r"^(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([^/?#]+)", a, re.I)
        user = m.group(1) if m else a.lstrip("@")
        if user.startswith("+") or user.lower() == "joinchat":
            raise ValueError("קישור הזמנה לערוץ פרטי אינו נתמך – רק ערוצים ציבוריים עם שם משתמש")
        if not TG_USER.match(user):
            raise ValueError("שם ערוץ טלגרם לא תקין. דוגמה: @channel או https://t.me/channel")
        return user.lower()
    if kind in ("rss", "api", "website"):
        p = urlsplit(a)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise ValueError("נדרשת כתובת מלאה שמתחילה ב-https://")
        return f"{p.scheme}://{p.hostname.lower()}{p.path or '/'}" + (f"?{p.query}" if p.query else "")
    return a.lower()


def _source_row(r) -> dict:
    d = dict(r)
    for k in ("coverage", "wanted_types"):
        d[k] = json.loads(d[k])
    for k in ("is_official", "enabled", "is_demo"):
        d[k] = bool(d[k])
    return d


def list_sources(con) -> list[dict]:
    return [_source_row(r) for r in con.execute("SELECT * FROM sources ORDER BY priority DESC, id")]


def get_source(con, sid: int) -> Optional[dict]:
    r = con.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone()
    return _source_row(r) if r else None


def create_source(con, s: SourceIn, actor: str) -> dict:
    norm = normalize_address(s.kind, s.address)
    if con.execute("SELECT 1 FROM sources WHERE kind = ? AND address_norm = ?", (s.kind, norm)).fetchone():
        raise ValueError("המקור הזה כבר קיים במערכת")
    cur = con.execute(
        "INSERT INTO sources(name, kind, address, address_norm, is_official, coverage, wanted_types,"
        " priority, enabled, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,'configured',?)",
        (s.name.strip(), s.kind, s.address.strip(), norm, int(s.is_official), json.dumps(s.coverage),
         json.dumps(s.wanted_types), s.priority, int(s.enabled), now_iso()),
    )
    audit(con, actor, "create", "source", cur.lastrowid, {"name": s.name, "kind": s.kind})
    return get_source(con, cur.lastrowid)


def update_source(con, sid: int, p: SourcePatch, actor: str) -> Optional[dict]:
    cur = get_source(con, sid)
    if not cur:
        return None
    changes = p.model_dump(exclude_unset=True)
    sets, vals = [], []
    for k, v in changes.items():
        if k == "address":
            norm = normalize_address(cur["kind"], v)
            dup = con.execute("SELECT 1 FROM sources WHERE kind = ? AND address_norm = ? AND id <> ?",
                              (cur["kind"], norm, sid)).fetchone()
            if dup:
                raise ValueError("המקור הזה כבר קיים במערכת")
            # כתובת חדשה = החיבור טרם נבדק
            sets += ["address = ?", "address_norm = ?", "status = 'configured'", "last_error = NULL"]
            vals += [v.strip(), norm]
        elif k in ("coverage", "wanted_types"):
            sets.append(f"{k} = ?"); vals.append(json.dumps(v))
        elif k in ("is_official", "enabled"):
            sets.append(f"{k} = ?"); vals.append(int(v))
        else:
            sets.append(f"{k} = ?"); vals.append(v)
    if sets:
        con.execute(f"UPDATE sources SET {', '.join(sets)} WHERE id = ?", (*vals, sid))
        audit(con, actor, "update", "source", sid, changes)
    return get_source(con, sid)


def delete_source(con, sid: int, actor: str) -> bool:
    n = con.execute("DELETE FROM sources WHERE id = ?", (sid,)).rowcount
    if n:
        audit(con, actor, "delete", "source", sid)
    return bool(n)


def record_check(con, sid: int, ok: Optional[bool], message: str, actor: str) -> dict:
    """ok=True → verified (אלא אם כבר נקלט מידע); ok=False → error; ok=None → לא נבדק, אין שינוי סטטוס."""
    src = get_source(con, sid)
    if ok is True:
        status = "ingesting" if src["ingested_count"] > 0 else "verified"
        con.execute("UPDATE sources SET status = ?, last_check_at = ?, last_error = NULL WHERE id = ?",
                    (status, now_iso(), sid))
    elif ok is False:
        con.execute("UPDATE sources SET status = 'error', last_check_at = ?, last_error = ? WHERE id = ?",
                    (now_iso(), message[:500], sid))
    audit(con, actor, "check", "source", sid, {"ok": ok, "message": message})
    return get_source(con, sid)


def list_locations(con) -> list[dict]:
    out = []
    for r in con.execute("SELECT * FROM locations ORDER BY kind, name_he"):
        d = dict(r)
        d["aliases"] = json.loads(d["aliases"])
        out.append(d)
    return out


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def list_events(con, *, event_type=None, verification=None, hours=None, location_id=None,
                lat=None, lon=None, radius_km=None, include_unpublished=False) -> list[dict]:
    q = ("SELECT e.*, l.name_he AS loc_name, l.kind AS loc_kind, l.lat AS loc_lat, l.lon AS loc_lon,"
         " l.coord_quality AS loc_quality FROM events e LEFT JOIN locations l ON l.id = e.location_id WHERE 1=1")
    args: list = []
    if not include_unpublished:
        q += " AND e.published = 1"
    if event_type:
        q += " AND e.event_type = ?"; args.append(event_type)
    if verification:
        q += " AND e.verification = ?"; args.append(verification)
    if hours:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        q += " AND e.updated_at >= ?"; args.append(since)
    q += " ORDER BY e.updated_at DESC LIMIT 300"
    rows = con.execute(q, args).fetchall()

    center = None
    if location_id is not None:
        loc = con.execute("SELECT lat, lon FROM locations WHERE id = ?", (location_id,)).fetchone()
        if loc and loc["lat"] is not None and radius_km:
            center = (loc["lat"], loc["lon"])
    elif lat is not None and lon is not None and radius_km:
        center = (lat, lon)

    out = []
    for r in rows:
        dist = None
        if center and r["loc_lat"] is not None:
            dist = haversine_km(center[0], center[1], r["loc_lat"], r["loc_lon"])
        if location_id is not None:
            same = r["location_id"] == location_id
            if not (same or (dist is not None and dist <= radius_km)):
                continue
        elif center and not (dist is not None and dist <= radius_km):
            continue
        out.append(_event_row(con, r, dist))
    return out


def _event_row(con, r, dist=None) -> dict:
    reps = con.execute(
        "SELECT s.id AS source_id, s.name AS source_name, s.is_official, rr.url, rr.published_at, er.relation"
        " FROM event_reports er JOIN raw_reports rr ON rr.id = er.raw_report_id"
        " JOIN sources s ON s.id = rr.source_id WHERE er.event_id = ? ORDER BY rr.published_at", (r["id"],)
    ).fetchall()
    # מקור עצמאי = מקור שונה שלא סומן כהעתקה
    independent = {x["source_id"] for x in reps if x["relation"] != "copy"}
    location = None
    if r["location_id"] is not None:
        location = {"id": r["location_id"], "name": r["loc_name"], "kind": r["loc_kind"],
                    "lat": r["loc_lat"], "lon": r["loc_lon"], "coord_quality": r["loc_quality"]}
    return {
        "id": r["id"], "title": r["title"], "summary": r["summary"], "event_type": r["event_type"],
        "status": r["status"], "verification": r["verification"], "severity": r["severity"],
        "location": location, "location_precision": r["location_precision"],
        "occurred_at": r["occurred_at"], "first_reported_at": r["first_reported_at"],
        "updated_at": r["updated_at"], "is_demo": bool(r["is_demo"]),
        "places": json.loads(r["places"]), "regions": regions_for(json.loads(r["places"])), "analyzer": r["analyzer"],
        "independent_sources": len(independent),
        "distance_km": round(dist, 1) if dist is not None else None,
        "reports": [{"source_name": x["source_name"], "is_official": bool(x["is_official"]),
                     "url": x["url"], "published_at": x["published_at"], "relation": x["relation"]}
                    for x in reps],
    }


def meta(con) -> dict:
    r = con.execute("SELECT MAX(updated_at) AS last, COUNT(*) AS n, SUM(is_demo) AS demo FROM events"
                    " WHERE published = 1").fetchone()
    real_ingest = con.execute("SELECT COUNT(*) AS n FROM raw_reports WHERE is_demo = 0").fetchone()["n"]
    return {"last_updated": r["last"], "events": r["n"], "demo_events": r["demo"] or 0,
            "real_reports_ingested": real_ingest, "server_time": now_iso()}
