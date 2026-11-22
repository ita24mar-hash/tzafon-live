"""מתאם טלגרם-ווב: קורא את דף התצוגה הציבורי של ערוץ (https://t.me/s/<channel>).

אין צורך בחשבון, במספר טלפון או בבוט. זה אינו API רשמי: מבנה הדף עלול להשתנות,
וערוץ יכול לכבות את התצוגה הציבורית. המתאם קורא בלבד, בקשה אחת לכל הרצה.
"""
import re
from html.parser import HTMLParser

from . import net

PREVIEW_URL = "https://t.me/s/{username}"
POST_URL = "https://t.me/{username}/{msg_id}"


class _PreviewParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.messages: list[dict] = []
        self.cur: dict | None = None
        self.text_depth = 0      # עומק ה-div בתוך גוף ההודעה
        self.in_date_link = False
        self.in_meta = 0

    @staticmethod
    def _classes(attrs) -> set[str]:
        return set((dict(attrs).get("class") or "").split())

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = self._classes(attrs)
        if tag == "div" and a.get("data-post") and "tgme_widget_message" in cls:
            self.cur = {"post": a["data-post"], "parts": [], "published_at": None,
                        "edited": False, "has_text": False}
            self.messages.append(self.cur)
            self.text_depth = 0
            return
        if self.cur is None:
            return
        if self.text_depth:
            if tag == "div":
                self.text_depth += 1
            elif tag == "br":
                self.cur["parts"].append("\n")
            return
        if tag == "div" and "tgme_widget_message_text" in cls and not self.cur["has_text"]:
            self.text_depth = 1
            self.cur["has_text"] = True
        elif tag == "span" and "tgme_widget_message_meta" in cls:
            self.in_meta = 1
        elif tag == "a" and "tgme_widget_message_date" in cls:
            self.in_date_link = True
        elif tag == "time" and self.in_date_link and a.get("datetime"):
            self.cur["published_at"] = a["datetime"]

    def handle_endtag(self, tag):
        if self.cur is None:
            return
        if self.text_depth:
            if tag == "div":
                self.text_depth -= 1
            return
        if tag == "a":
            self.in_date_link = False
        elif tag == "span" and self.in_meta:
            self.in_meta = 0

    def handle_data(self, data):
        if self.cur is None:
            return
        if self.text_depth:
            self.cur["parts"].append(data)
        elif self.in_meta and "edited" in data.lower():
            self.cur["edited"] = True


def parse_preview(html: str, username: str) -> list[dict]:
    """מחזיר רשימת הודעות: external_id, url, published_at, content, edited."""
    p = _PreviewParser()
    p.feed(html)
    out = []
    for m in p.messages:
        channel, _, msg_id = m["post"].rpartition("/")
        # מתעלמים מהודעות שאינן של הערוץ המבוקש או שחסר בהן מזהה/זמן – לא ממציאים נתונים
        if channel.lower() != username.lower() or not msg_id.isdigit() or not m["published_at"]:
            continue
        text = "".join(m["parts"]).replace("\xa0", " ")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        out.append({
            "external_id": msg_id,
            "url": POST_URL.format(username=channel, msg_id=msg_id),
            "published_at": m["published_at"],
            "content": text,
            "edited": m["edited"],
        })
    return out


def fetch_channel(username: str, fetch=net.safe_fetch) -> list[dict]:
    """מוריד ומפענח. זורק RuntimeError עם הסבר בעברית אם אין הודעות."""
    status, body = fetch(PREVIEW_URL.format(username=username))
    if status != 200:
        raise RuntimeError(f"טלגרם החזיר קוד {status}")
    messages = parse_preview(body.decode("utf-8", errors="replace"), username)
    if not messages:
        raise RuntimeError("לא נמצאו הודעות בדף: ייתכן שהתצוגה הציבורית של הערוץ כבויה,"
                           " שהערוץ אינו קיים, או שמבנה הדף השתנה")
    return messages
