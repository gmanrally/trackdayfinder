"""A GMR row every PROMO_EVERY events, including across infinite scroll.

What this pins:

  * the row appears once per PROMO_EVERY events on the first page, and not
    before — a list shorter than that carries no advert at all
  * the cadence CONTINUES across chunks. Chunks are date windows, not fixed
    counts, so the server cannot know what the page already holds: the client
    sends it back. Without that the row lands on the 50th of EACH chunk, which
    on a quiet month is every few rows
  * consecutive rows show different products
  * it is labelled, and it spans the table rather than wearing a date and a
    circuit — somebody scanning for a date must not stop on it by mistake
  * GMR_PROMO=0 removes it entirely

Neutral demo events in a throwaway database. Nothing is fetched.

    python -m tools.test_promo_row
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import date, timedelta

os.environ["TRACKDAYFINDER_DATA"] = tempfile.mkdtemp(prefix="promorow-")
os.environ.setdefault("TDF_SECRET", "test-only-secret")

HOST = "https://trackdayfinder.co.uk"
N = 130                     # enough for two promo rows at 50


def main() -> int:
    from fastapi.testclient import TestClient

    from app import partner
    from app.main import app
    from app.models import Event, init_db, session

    every = partner.PROMO_EVERY
    init_db()
    with session() as s:
        for i in range(N):
            s.add(Event(
                dedup_key="zztest-%d" % i, source="zztest_org", organiser="ZZTEST Org",
                circuit="ZZTEST Circuit %d" % (i % 4), circuit_raw="ZZTEST",
                event_date=date.today() + timedelta(days=1 + i // 4),
                booking_url="https://example.com/book/%d" % i))
        s.commit()

    client = TestClient(app, base_url=HOST)
    bad: list[str] = []

    r = client.get("/")
    rows = r.text.count('data-promo="gmr"')
    events_shown = r.text.count('data-iso="')
    print("  first page .............. %d event rows, %d promo row(s)"
          % (events_shown, rows))
    if r.status_code != 200:
        bad.append("the index returned %s" % r.status_code)
    expected = events_shown // every
    if rows != expected:
        bad.append("expected %d promo row(s) for %d events, got %d"
                   % (expected, events_shown, rows))

    # it must not pretend to be an event
    for m in re.finditer(r'<tr class="list-ad"[^>]*>(.*?)</tr>', r.text, re.S):
        if 'data-label="Date"' in m.group(1):
            bad.append("the promo row carries a Date cell — it reads as a trackday")
    if rows and "From the workshop behind this site" not in r.text:
        bad.append("the promo row is not labelled as advertising")

    # --- the cadence has to survive a chunk --------------------------------
    c = client.get("/_chunk", params={"from_offset": 0, "rendered": every - 1})
    data = c.json()
    print("  chunk told 'rendered=%d' ... %d promo row(s) in the chunk"
          % (every - 1, data["html"].count('data-promo="gmr"')))
    if c.status_code != 200:
        bad.append("/_chunk returned %s" % c.status_code)
    if "rendered" not in data:
        bad.append("the chunk does not report a running total — the page cannot "
                   "continue the cadence")
    # Exact, not "at least one": told rendered=every-1, the qualifying rows are
    # the global multiples of `every` inside this chunk. An implementation that
    # ignored the count would place them at the chunk's OWN 50th and 100th and
    # come up one short - which is the bug this whole parameter exists to stop.
    chunk_evs = data["html"].count('data-iso="')
    start = every - 1
    want = sum(1 for i in range(1, chunk_evs + 1) if (start + i) % every == 0)
    got = data["html"].count('data-promo="gmr"')
    if got != want:
        bad.append("chunk continuation wrong: %d promo row(s) over %d events "
                   "from rendered=%d, expected %d" % (got, chunk_evs, start, want))

    c0 = client.get("/_chunk", params={"from_offset": 0, "rendered": 0})
    n0 = c0.json()["html"].count('data-promo="gmr"')
    evs = c0.json()["html"].count('data-iso="')
    print("  chunk told 'rendered=0' ... %d event rows, %d promo row(s)" % (evs, n0))
    if n0 != evs // every:
        bad.append("chunk from zero: expected %d, got %d" % (evs // every, n0))

    # --- different products in consecutive slots ---------------------------
    a, b = partner.promo(1), partner.promo(2)
    print("  slot 1 vs slot 2 ........ %r / %r"
          % ((a or {}).get("head", "")[:26], (b or {}).get("head", "")[:26]))
    if a and b and a["url"] == b["url"] and len(partner.PRODUCTS) > 1:
        bad.append("two promo rows on one page show the same product")

    # --- the off switch -----------------------------------------------------
    partner.ENABLED = False
    off = client.get("/").text.count('data-promo="gmr"')
    partner.ENABLED = True
    print("  GMR_PROMO=0 ............. %d promo row(s)" % off)
    if off:
        bad.append("the promo still renders when switched off")

    for b_ in bad:
        print("FAIL: %s" % b_)
    print("  %s" % ("OK: one row per %d events, and it keeps counting across chunks" % every
                    if not bad else "%d problem(s)" % len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
