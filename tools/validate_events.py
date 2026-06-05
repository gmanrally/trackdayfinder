"""Audit every event in the DB and surface anything that looks wrong.

Default mode: report-only — prints what each check would flag/delete.
With `--fix`: applies the safe cleanups (past dates, holiday rejects,
stale last_seen). Cross-source duplicate suspects are always reported
but never auto-deleted — they need a human eye.

Run from /opt/trackdayfinder:
    docker compose exec -T app python < tools/validate_events.py             # report only
    docker compose exec -T app python -c "import sys; sys.argv=['x','--fix']; exec(open('tools/validate_events.py').read())"  # apply fixes
"""
from __future__ import annotations
import sys
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from sqlmodel import select
from app.main import db_session
from app.models import Event

FIX = "--fix" in sys.argv
STALE_DAYS = 14

# Major holidays where no legitimate trackday runs.
def _is_holiday(d: date) -> bool:
    md = (d.month, d.day)
    return md in {(12, 25), (12, 26), (1, 1)}

# Booking URLs that point to a bare organiser homepage rather than a specific
# event page are low-confidence — they often come from aggregator rows where
# the source couldn't extract a real link.
HOMEPAGE_RE = re.compile(r"^https?://[^/]+/?$", re.I)


def _norm_tokens(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return set(re.findall(r"[a-z0-9]+", s))


def main() -> int:
    today = date.today()
    now = datetime.utcnow()
    cutoff_stale = now - timedelta(days=STALE_DAYS)

    with db_session() as s:
        all_events = s.exec(select(Event)).all()

    past = [e for e in all_events if e.event_date < today]
    upcoming = [e for e in all_events if e.event_date >= today]

    holiday = [e for e in upcoming if _is_holiday(e.event_date)]
    stale = [e for e in upcoming if e.last_seen and e.last_seen < cutoff_stale]
    missing_org = [e for e in upcoming if not (e.organiser or "").strip()]
    missing_circuit = [e for e in upcoming if not (e.circuit or "").strip()]
    homepage_urls = [
        e for e in upcoming
        if e.booking_url and HOMEPAGE_RE.match(e.booking_url)
    ]

    # Cross-source duplicates: same circuit + date + organiser-token overlap
    # across different sources.
    by_circ_date: dict[tuple[str, date], list[Event]] = defaultdict(list)
    for e in upcoming:
        by_circ_date[(e.circuit, e.event_date)].append(e)
    dup_groups = []
    for (circ, d), evs in by_circ_date.items():
        if len(evs) < 2:
            continue
        # cluster by organiser tokens
        seen_clusters: list[tuple[set[str], list[Event]]] = []
        for e in evs:
            otok = _norm_tokens(e.organiser)
            placed = False
            for toks, group in seen_clusters:
                if len(otok & toks) >= 1:
                    group.append(e)
                    toks.update(otok)
                    placed = True
                    break
            if not placed:
                seen_clusters.append((otok, [e]))
        for _, group in seen_clusters:
            if len(group) >= 2 and len({e.source for e in group}) >= 2:
                dup_groups.append(group)

    # ============ Report ============
    print(f"\nDB total: {len(all_events)}   upcoming: {len(upcoming)}   past: {len(past)}\n")
    sections: list[tuple[str, list[Event], bool, str]] = [
        ("Past-dated rows (delete)",                past,            True,  "by source"),
        ("Holiday rows (delete: 25 Dec / 26 Dec / 1 Jan)", holiday, True,  "by source"),
        ("Stale rows (last_seen > %d days)" % STALE_DAYS, stale,    True,  "by source"),
        ("Empty organiser",                          missing_org,    True,  "by source"),
        ("Empty circuit",                            missing_circuit, True,  "by source"),
        ("Booking URL is organiser homepage only",   homepage_urls,  False, "by source"),
    ]
    for label, group, is_fixable, mode in sections:
        flag = "(would fix)" if (is_fixable and not FIX) else ("(fixed)" if is_fixable and FIX else "(report only)")
        print(f"== {label}: {len(group)} {flag}")
        if not group:
            continue
        if mode == "by source":
            c = Counter(e.source for e in group)
            for k, n in c.most_common(): print(f"   {n:5d}  {k}")
        print()

    # Duplicate groups — sample 10
    print(f"== Cross-source duplicates (same circuit+date, overlapping organiser tokens): {len(dup_groups)} groups (report only)")
    for group in dup_groups[:10]:
        e0 = group[0]
        print(f"   {e0.event_date} {e0.circuit}")
        for e in group:
            print(f"      src={e.source:18s} org={(e.organiser or '').strip():35s}  £{e.price_gbp or '-'}  url={(e.booking_url or '')[:60]}")

    # ============ Fix ============
    if FIX:
        to_delete: set[int] = set()
        for group_evs in (past, holiday, stale, missing_org, missing_circuit):
            for e in group_evs:
                if e.id is not None:
                    to_delete.add(e.id)
        if to_delete:
            with db_session() as s:
                for ev_id in to_delete:
                    obj = s.get(Event, ev_id)
                    if obj is not None:
                        s.delete(obj)
                s.commit()
            print(f"\nDeleted {len(to_delete)} events.")
        else:
            print("\nNo deletions required.")
    else:
        print("\nReport-only run. Re-run with --fix to apply the deletions above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
