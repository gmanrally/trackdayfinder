"""Which clicks came from a page, and which just hit the redirect.

84% of recorded clicks arrive at /go/<id> with no referrer at all. The booking
links are rel="noopener" under strict-origin-when-cross-origin, so a real click
from one of our own pages DOES send one — these are hits on the redirect by
something that never loaded a page, spoofing a browser past _looks_like_bot.

It matters because the click count is what we would quote to an organiser.

What this pins:

  * a click from one of our pages is marked onsite
  * a click with no referrer is still RECORDED, and marked not-onsite — a
    privacy extension strips referrers too, and dropping the row would both
    lose a real person and hide how big the problem is
  * a referrer from somebody else's site is not onsite either
  * a declared bot is still not recorded at all, as before
  * /go/ is disallowed in robots.txt
  * the redirect still goes where it should, whatever the verdict

    python -m tools.test_click_onsite
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta

os.environ["TRACKDAYFINDER_DATA"] = tempfile.mkdtemp(prefix="clickonsite-")
os.environ.setdefault("TDF_SECRET", "test-only-secret")

HOST = "https://trackdayfinder.co.uk"


def main() -> int:
    from fastapi.testclient import TestClient
    from sqlmodel import select

    from app import models
    from app.main import app
    from app.models import Click, Event, init_db, session

    init_db()
    with session() as s:
        ev = Event(dedup_key="zztest-1", source="zztest_org", organiser="ZZTEST Org",
                   circuit="ZZTEST Circuit", circuit_raw="ZZTEST Circuit",
                   event_date=date.today() + timedelta(days=30),
                   booking_url="https://example.com/book/zztest")
        s.add(ev)
        s.commit()
        s.refresh(ev)
        eid = ev.id

    client = TestClient(app, base_url=HOST)
    bad: list[str] = []

    def clicks():
        with session() as s:
            return list(s.exec(select(Click).where(Click.event_id == eid)))

    def go(**headers):
        return client.get("/go/%d" % eid, headers=headers, follow_redirects=False)

    # --- from one of our own pages -----------------------------------------
    r = go(referer=HOST + "/?circuit=ZZTEST")
    rows = clicks()
    print("  from our own page ....... %s -> %s, recorded=%d onsite=%s"
          % (r.status_code, (r.headers.get("location") or "")[:34], len(rows),
             rows[-1].onsite if rows else "-"))
    if r.status_code != 302 or "example.com" not in (r.headers.get("location") or ""):
        bad.append("the redirect broke: %s %s" % (r.status_code, r.headers.get("location")))
    if len(rows) != 1 or not rows[-1].onsite:
        bad.append("a click from our own page was not marked onsite")

    # --- no referrer: recorded, but not counted ----------------------------
    go()
    rows = clicks()
    print("  no referrer ............. recorded=%d onsite=%s"
          % (len(rows), rows[-1].onsite if rows else "-"))
    if len(rows) != 2:
        bad.append("a referrer-less click was dropped — a real person with a "
                   "privacy extension would vanish with it")
    elif rows[-1].onsite:
        bad.append("a referrer-less click was counted as onsite")

    # --- somebody else's site ----------------------------------------------
    go(referer="https://example.net/some/page")
    rows = clicks()
    print("  foreign referrer ........ recorded=%d onsite=%s"
          % (len(rows), rows[-1].onsite if rows else "-"))
    if len(rows) != 3 or rows[-1].onsite:
        bad.append("a click from another site was counted as onsite")

    # --- a declared bot is still not recorded ------------------------------
    before = len(clicks())
    go(**{"user-agent": "Mozilla/5.0 (compatible; ZZTESTbot/1.0; +http://example.com/bot)"})
    after = len(clicks())
    print("  declared bot ............ recorded=%s" % (after > before))
    if after != before:
        bad.append("a declared bot was recorded")

    # --- what the counts would say -----------------------------------------
    real = sum(1 for c in clicks() if c.onsite)
    print("  countable / recorded .... %d / %d" % (real, len(clicks())))
    if real != 1:
        bad.append("expected exactly 1 countable click, got %d" % real)

    # --- robots -------------------------------------------------------------
    rb = client.get("/robots.txt").text
    print("  robots.txt disallows /go/ %s" % ("Disallow: /go/" in rb))
    if "Disallow: /go/" not in rb:
        bad.append("/go/ is not disallowed — crawlers keep walking every booking link")
    if "Disallow: /api/" not in rb:
        bad.append("the existing /api/ rule was lost")

    for b in bad:
        print("FAIL: %s" % b)
    print("  %s" % ("OK: countable clicks are the ones that came from a page"
                    if not bad else "%d problem(s)" % len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
