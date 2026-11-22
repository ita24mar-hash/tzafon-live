"""שרת ה-API של צפון LIVE (Starlette). הרצה: uvicorn app.main:app"""
import hmac
import json
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import ingest, net, repo
from .db import connect, init_db
from .seed import run_seed

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MIN", "120"))
CSP = ("default-src 'self'; script-src 'self' https://unpkg.com; style-src 'self' https://unpkg.com;"
       " img-src 'self' data: https://*.tile.openstreetmap.org https://unpkg.com; connect-src 'self';"
       " frame-ancestors 'none'; base-uri 'none'")


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class SecurityMiddleware(BaseHTTPMiddleware):
    """הגבלת קצב לפי IP + כותרות אבטחה."""

    def __init__(self, app):
        super().__init__(app)
        self.hits: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            ip = request.client.host if request.client else "?"
            q, now = self.hits[ip], time.monotonic()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= RATE_LIMIT:
                return err(429, "יותר מדי בקשות, נסו שוב בעוד דקה")
            q.append(now)
            if len(self.hits) > 10000:
                self.hits.clear()
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        # ההרשאה למיקום ניתנת רק לאפליקציה עצמה, ורק אם המשתמש בוחר בכך
        resp.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=()"
        return resp


def admin_actor(request: Request):
    """מחזיר 'admin' אם הטוקן תקין, אחרת תגובת שגיאה."""
    token = os.environ.get("ADMIN_TOKEN", "")
    if len(token) < 16:
        return err(503, "ממשק הניהול כבוי: יש להגדיר ADMIN_TOKEN (לפחות 16 תווים) בשרת")
    given = request.headers.get("authorization", "")
    if not given.startswith("Bearer ") or not hmac.compare_digest(given[7:].encode(), token.encode()):
        return err(401, "נדרשת הרשאת מנהל")
    return "admin"


def _int(v, lo, hi):
    if v is None or v == "":
        return None
    n = int(v)
    if not lo <= n <= hi:
        raise ValueError
    return n


def _float(v, lo, hi):
    if v is None or v == "":
        return None
    n = float(v)
    if not lo <= n <= hi:
        raise ValueError
    return n


def health(request):
    return JSONResponse({"ok": True})


def get_meta(request):
    with connect() as con:
        return JSONResponse(repo.meta(con))


def get_locations(request):
    with connect() as con:
        return JSONResponse(repo.list_locations(con))


def get_events(request: Request):
    qp = request.query_params
    try:
        etype = qp.get("type") or None
        verif = qp.get("verification") or None
        if etype and etype not in repo.EVENT_TYPES:
            raise ValueError
        if verif and verif not in ("single_source", "multi_source", "official", "retracted"):
            raise ValueError
        args = dict(
            event_type=etype, verification=verif,
            hours=_int(qp.get("hours"), 1, 24 * 30),
            location_id=_int(qp.get("location_id"), 1, 10**9),
            lat=_float(qp.get("lat"), -90, 90), lon=_float(qp.get("lon"), -180, 180),
            radius_km=_float(qp.get("radius_km"), 0.5, 300),
        )
    except ValueError:
        return err(400, "פרמטר סינון לא תקין")
    with connect() as con:
        return JSONResponse(repo.list_events(con, **args))


def get_raw(request):
    """הודעות גולמיות אמיתיות כפי שנקלטו מהמקורות (ללא נתוני הדגמה)."""
    with connect() as con:
        return JSONResponse(ingest.list_raw_reports(con, 200))


def public_sources(request):
    """מצב המקורות לקריאה בלבד (ללא פרטים רגישים)."""
    keys = ("name", "kind", "address", "is_official", "enabled", "status", "priority", "last_check_at",
            "last_error", "last_ingest_at", "ingested_count", "is_demo")
    with connect() as con:
        return JSONResponse([{k: s[k] for k in keys} for s in repo.list_sources(con)])


async def _json_body(request: Request):
    body = await request.body()
    if len(body) > 20000:
        raise ValueError("גוף הבקשה גדול מדי")
    return json.loads(body or b"{}")


def _validation_message(e: ValidationError) -> str:
    return "קלט לא תקין: " + ", ".join(str(x["loc"][0]) for x in e.errors() if x["loc"])


async def admin_sources(request: Request):
    actor = admin_actor(request)
    if not isinstance(actor, str):
        return actor
    if request.method == "GET":
        with connect() as con:
            return JSONResponse(repo.list_sources(con))
    try:
        data = repo.SourceIn(**(await _json_body(request)))
        with connect() as con:
            return JSONResponse(repo.create_source(con, data, actor), status_code=201)
    except ValidationError as e:
        return err(422, _validation_message(e))
    except (ValueError, TypeError) as e:
        return err(400, str(e))


async def admin_source(request: Request):
    actor = admin_actor(request)
    if not isinstance(actor, str):
        return actor
    sid = request.path_params["sid"]
    if request.method == "DELETE":
        with connect() as con:
            return JSONResponse({"deleted": True}) if repo.delete_source(con, sid, actor) else err(404, "לא נמצא")
    try:
        patch = repo.SourcePatch(**(await _json_body(request)))
        with connect() as con:
            out = repo.update_source(con, sid, patch, actor)
        return JSONResponse(out) if out else err(404, "לא נמצא")
    except ValidationError as e:
        return err(422, _validation_message(e))
    except (ValueError, TypeError) as e:
        return err(400, str(e))


def admin_source_test(request: Request):
    """בדיקת חיבור אמיתית. מקור מסומן 'נבדק' רק אם הבדיקה הצליחה בפועל."""
    actor = admin_actor(request)
    if not isinstance(actor, str):
        return actor
    sid = request.path_params["sid"]
    with connect() as con:
        src = repo.get_source(con, sid)
    if not src:
        return err(404, "לא נמצא")
    ok, message = None, ""
    if src["kind"] == "telegram":
        message = "בדיקת חיבור לטלגרם תתווסף בשלב ב (שירות האיסוף עם Telethon). המקור נשמר כ'הוגדר' בלבד."
    elif src["kind"] in ("rss", "api", "website"):
        try:
            status, body = net.safe_fetch(src["address"])
            if status != 200:
                ok, message = False, f"השרת החזיר קוד {status}"
            elif src["kind"] == "rss":
                n = net.count_feed_items(body)
                ok, message = (True, f"נמצאו {n} פריטים בפיד") if n else (False, "לא נמצאו פריטים בפיד")
            else:
                ok, message = True, "הכתובת נגישה (קליטת תוכן תתווסף עם מתאם ייעודי)"
        except net.UnsafeURL as e:
            ok, message = False, str(e)
        except Exception as e:  # שגיאות רשת/פענוח
            ok, message = False, f"הבדיקה נכשלה: {type(e).__name__}"
    else:
        message = "לסוג מקור זה אין עדיין בדיקת חיבור."
    with connect() as con:
        out = repo.record_check(con, sid, ok, message, actor)
    return JSONResponse({"ok": ok, "message": message, "source": out})


def admin_audit(request: Request):
    actor = admin_actor(request)
    if not isinstance(actor, str):
        return actor
    with connect() as con:
        rows = con.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100").fetchall()
    return JSONResponse([dict(r) | {"detail": json.loads(r["detail"])} for r in rows])


@asynccontextmanager
async def lifespan(app):
    init_db()
    run_seed()
    yield


routes = [
    Route("/api/health", health),
    Route("/api/meta", get_meta),
    Route("/api/locations", get_locations),
    Route("/api/events", get_events),
    Route("/api/raw", get_raw),
    Route("/api/sources", public_sources),
    Route("/api/admin/sources", admin_sources, methods=["GET", "POST"]),
    Route("/api/admin/sources/{sid:int}", admin_source, methods=["PATCH", "DELETE"]),
    Route("/api/admin/sources/{sid:int}/test", admin_source_test, methods=["POST"]),
    Route("/api/admin/audit", admin_audit),
    Mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web"),
]

app = Starlette(routes=routes, lifespan=lifespan, middleware=[Middleware(SecurityMiddleware)])
