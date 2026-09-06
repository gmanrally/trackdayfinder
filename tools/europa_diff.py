"""One-off: parse europatrackdays.com calendar HTML and report which events
are NOT already covered by our DB (rough fuzzy match on date + slug tokens)."""
import re, unicodedata
from datetime import date
from collections import Counter
from app.main import db_session
from app.models import Event
from sqlmodel import select

html = open("et.html", encoding="utf-8", errors="ignore").read()

events = []
for m in re.finditer(r"/trackday/(\d+)/([a-z0-9-]+?)-(\d{4}-\d{2}-\d{2})", html):
    try:
        d = date.fromisoformat(m.group(3))
    except ValueError:
        continue
    events.append({"id": m.group(1), "slug": m.group(2), "date": d})

seen = set(); uniq = []
for e in events:
    if e["id"] in seen: continue
    seen.add(e["id"]); uniq.append(e)

def tok(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]+", s))

with db_session() as s:
    db = s.exec(select(Event).where(Event.event_date >= date(2026, 5, 10))).all()

db_by_date = {}
for e in db:
    db_by_date.setdefault(e.event_date, []).append(tok(e.circuit) | tok(e.organiser))

missing = []
for e in uniq:
    cand = db_by_date.get(e["date"], [])
    slug_tokens = set(e["slug"].split("-"))
    if not any(len(slug_tokens & db_toks) >= 2 for db_toks in cand):
        missing.append(e)

print(f"{len(uniq)} europa events; {len(missing)} not covered by our DB")
print()

# Group by trailing slug bits (rough organiser cluster)
hints = Counter()
for e in missing:
    parts = e["slug"].split("-")
    hint = "-".join(parts[-3:]) if len(parts) >= 3 else e["slug"]
    hints[hint] += 1

print("--- top 30 missing clusters (last 3 slug tokens, rough organiser/site) ---")
for h, n in hints.most_common(30):
    print(f"  {n:3d}  {h}")

print()
print("--- top circuits in missing set (first 3 slug tokens) ---")
heads = Counter()
for e in missing:
    parts = e["slug"].split("-")
    heads["-".join(parts[:3])] += 1
for h, n in heads.most_common(30):
    print(f"  {n:3d}  {h}")
