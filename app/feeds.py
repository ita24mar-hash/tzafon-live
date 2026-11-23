"""קריאת אתרים דרך פיד RSS/Atom (הדרך המקובלת שבה אתרים מפרסמים עדכונים).

כמו בטלגרם: נשמר רק פתיח קצר (כותרת + תחילת התקציר) וקישור לכתבה המקורית.
"""
import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

from . import net

TAG = re.compile(r"<[^>]+>")


def _local(tag: str) -> str:
    return tag.split("}")[-1].lower()


def _text(el, *names) -> str:
    for child in el:
        if _local(child.tag) in names:
            if _local(child.tag) == "link" and child.get("href"):
                return child.get("href")
            return (child.text or "").strip()
    return ""


def _date(s: str) -> str | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", html.unescape(s or "")))).strip()


def parse_feed(body: bytes) -> list[dict]:
    """פריטי RSS/Atom בפורמט של הודעות טלגרם: external_id, url, published_at, content."""
    head = body[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in body.lower():
        raise ValueError("קובץ XML עם DTD אינו נתמך")
    root = ET.fromstring(body)
    out = []
    for item in (el for el in root.iter() if _local(el.tag) in ("item", "entry")):
        title = _plain(_text(item, "title"))
        desc = _plain(_text(item, "description", "summary", "content"))
        link = _text(item, "link")
        when = _date(_text(item, "pubdate", "published", "updated", "date"))
        if not (title or desc) or not when:
            continue
        guid = _text(item, "guid", "id") or link or title
        content = title if not desc or desc.startswith(title) else f"{title}. {desc}"
        out.append({"external_id": hashlib.sha1(guid.encode()).hexdigest()[:16], "url": link or None,
                    "published_at": when, "content": content})
    return out


def fetch_feed(url: str, fetch=net.safe_fetch) -> list[dict]:
    status, body = fetch(url)
    if status != 200:
        raise RuntimeError(f"האתר החזיר קוד {status}")
    items = parse_feed(body)
    if not items:
        raise RuntimeError("לא נמצאו ידיעות בפיד")
    return items


class _AltLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and "alternate" in (a.get("rel") or "").lower() and \
                any(t in (a.get("type") or "").lower() for t in ("rss", "atom")) and a.get("href"):
            self.links.append((a.get("title") or "", a["href"]))


def discover_feeds(page_url: str, body: bytes) -> list[tuple[str, str]]:
    """קישורי הפיד שאתר מצהיר עליהם בדף הבית (<link rel="alternate" type="application/rss+xml">)."""
    p = _AltLinks()
    p.feed(body.decode("utf-8", "replace"))
    return [(t, urljoin(page_url, h)) for t, h in p.links]
