"""גישה בטוחה לכתובות חיצוניות (הגנת SSRF) ובדיקת חיבור למקורות RSS/אתר."""
import ipaddress
import socket
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit

import requests

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
UA = "TzafonLive/0.1 (+source connection check)"


class UnsafeURL(ValueError):
    pass


def check_url(url: str, resolver=socket.getaddrinfo) -> str:
    """מאמת שהכתובת ציבורית ומותרת. זורק UnsafeURL אם לא."""
    p = urlsplit(url)
    if p.scheme not in ("http", "https"):
        raise UnsafeURL("מותרות רק כתובות http/https")
    if not p.hostname or p.username or p.password:
        raise UnsafeURL("כתובת לא תקינה")
    try:
        port = p.port
    except ValueError:
        raise UnsafeURL("פורט לא תקין")
    if port not in (None, 80, 443):
        raise UnsafeURL("פורט לא מורשה")
    try:
        infos = resolver(p.hostname, port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        raise UnsafeURL("לא ניתן לאתר את השרת")
    if not infos:
        raise UnsafeURL("לא ניתן לאתר את השרת")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise UnsafeURL("הכתובת מפנה לרשת פנימית ואינה מורשית")
    return url


def safe_fetch(url: str) -> tuple[int, bytes]:
    """מוריד עד 2MB, בודק כל הפניה מחדש. מחזיר (status, body)."""
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        with requests.get(url, allow_redirects=False, timeout=(5, 10), stream=True,
                          headers={"User-Agent": UA}) as r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                url = urljoin(url, r.headers["Location"])
                continue
            body = b""
            for chunk in r.iter_content(65536):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise UnsafeURL("התגובה גדולה מדי")
            return r.status_code, body
    raise UnsafeURL("יותר מדי הפניות")


def count_feed_items(body: bytes) -> int:
    """סופר פריטים ב-RSS/Atom. דוחה DTD/ENTITY כדי למנוע התקפות XML."""
    head = body[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in body.lower():
        raise ValueError("קובץ XML עם DTD אינו נתמך")
    root = ET.fromstring(body)
    return sum(1 for el in root.iter() if el.tag.split("}")[-1] in ("item", "entry"))
