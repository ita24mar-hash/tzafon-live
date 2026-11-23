"""עיבוד אישורים להצעות הסוכן: issue שבו סומנו ✓, נסגר, או קיבל תגובה "אשר הכל" / "דחה הכל"."""
import json
import os
import re

import requests

from collector import proposals, sources_edit as se

CHECK = re.compile(r"^\s*-\s*\[([ xX])\]\s*`([^`]+)`", re.M)


def main() -> int:
    ev = json.load(open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8"))
    issue, action = ev["issue"], ev.get("action")
    num, body = issue["number"], issue.get("body") or ""
    prop = proposals.load()
    items = {k: v == " " for v, k in [(m.group(1), m.group(2)) for m in CHECK.finditer(body)]}   # key → unchecked?
    pending = [k for k in items if prop.get(k, {}).get("status") == "proposed"]
    approve, reject = [], []
    if "comment" in ev:
        text = ev["comment"]["body"].strip()
        if re.search(r"אשר(?:\s+את)?\s+הכל|אשר הכול|approve all", text, re.I):
            approve = pending
        elif re.search(r"דחה(?:\s+את)?\s+הכל|דחה הכול|reject all", text, re.I):
            reject = pending
        else:
            for k in pending:
                name = k.split(":", 1)[1]
                if re.search(rf"אשר\b[^\n]*{re.escape(name)}", text, re.I):
                    approve.append(k)
                elif re.search(rf"דחה\b[^\n]*{re.escape(name)}", text, re.I):
                    reject.append(k)
    else:
        approve = [k for k in pending if not items[k]]
        if action == "closed":
            reject = [k for k in pending if items[k]]
    added = []
    for k in approve:
        c = prop[k]["candidate"]
        if se.add_source(se.entry_from_candidate(c, f"אושר על ידי מנהל המערכת בהצעה #{num}")):
            added.append(c["title"] or c["username"])
        prop[k]["status"] = "approved"
    for k in reject:
        se.ignore(k)
        prop[k]["status"] = "rejected"
    if not approve and not reject:
        print("אין שינוי")
        return 0
    proposals.save(prop)
    msg = []
    if added:
        msg.append("✅ נוספו לאיסוף: " + ", ".join(added) + ". ההודעות שלהם יופיעו בהרצת האיסוף הבאה (תוך כמה דקות).")
    if reject:
        msg.append(f"🚫 נדחו ולא יוצעו שוב: {len(reject)}.")
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    requests.post(f"https://api.github.com/repos/{repo}/issues/{num}/comments", headers=h, timeout=30,
                  json={"body": "\n".join(msg)}).raise_for_status()
    left = [k for k in items if prop.get(k, {}).get("status") == "proposed"]
    if not left and issue.get("state") == "open":
        requests.patch(f"https://api.github.com/repos/{repo}/issues/{num}", headers=h, timeout=30,
                       json={"state": "closed"}).raise_for_status()
    print("\n".join(msg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
