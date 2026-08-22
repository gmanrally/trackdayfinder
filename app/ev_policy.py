"""Static EV (electric-vehicle) policy data, hand-curated from organiser
FAQ/terms pages. Listings never carry this, so we curate it — the same
pattern as CIRCUIT_STATIC_NOISE_DB. Provenance: docs/ev_policy_research.md.

Two layers: a circuit-level ban overrides whatever the organiser allows.
Display rule: only rows with a KNOWN policy get a pill — silence is never
a green tick. Policies change, so every claim carries its source URL and
the date we checked it, and copy should say "confirm with the organiser".
"""

CHECKED = "2026-08-22"

# status: "allowed" | "conditions" | "banned"
ORGANISER_EV_POLICY = {
    "msv": {
        "status": "conditions",
        "note": "EVs/hybrids allowed — dedicated bays (not garages); charging billed by the circuit",
        "url": "https://car.msvtrackdays.com/FAQ/Booked",
    },
    "javelin": {
        "status": "conditions",
        "note": "Declare at booking; standard unmodified EVs only; not at Blyton Park, Mallory Park or Anglesey",
        "url": "https://javelintrackdays.co.uk/trackdays/terms",
    },
    "silverstone": {
        "status": "conditions",
        "note": "Approval, risk assessment and vehicle details required at least 14 days before the event",
        "url": "https://www.silverstone.co.uk/terms-and-conditions/car-track-days-terms-conditions",
    },
    "opentrack": {
        "status": "conditions",
        "note": "Allowed except where the circuit bans EVs (e.g. Anglesey)",
        "url": "https://opentrack.co.uk/view-dates",
    },
    "castle_combe": {
        "status": "allowed",
        "note": "EVs welcome on circuit-organised track days; two 7.4kW chargers on site",
        "url": "https://castlecombecircuit.co.uk/2025/12/18/castle-combe-circuit-continues-sustainability-drive-with-all-new-features/",
    },
    "msevents": {
        "status": "allowed",
        "note": "No formal policy published, but Teslas are listed among regular attendees",
        "url": "https://www.motorsport-events.com/pages/trackday-faq",
    },
    "three_sisters": {
        "status": "banned",
        "note": "No electric vehicles of any kind, including hybrids",
        "url": "https://threesisterscircuit.co.uk/cars/car-track-days",
    },
    "trackday_solutions": {
        "status": "banned",
        "note": "Electric vehicles are not allowed",
        "url": "https://www.trackday-solutions.co.uk/faq",
    },
    "skylimit": {
        "status": "banned",
        "note": "EVs (and large SUVs) are not permitted at Skylimit events",
        "url": "https://skylimitevents.com/en/event/113/document/15292",
    },
}

# Circuit-level bans apply regardless of organiser. Keys are canonical
# circuit names. Blyton Park / Mallory Park are single-sourced (Javelin's
# terms) so they stay out until independently verified — they still
# surface through Javelin's own note above.
CIRCUIT_EV_BAN = {
    "Anglesey": {
        "note": "Circuit bans EVs and hybrids, whoever runs the day",
        "url": "https://javelintrackdays.co.uk/trackdays/terms",
    },
    "Three Sisters": {
        "note": "Circuit bans EVs and hybrids",
        "url": "https://threesisterscircuit.co.uk/cars/car-track-days",
    },
}

# The "EV friendly" filter set: sources with a positive published policy.
EV_OK_SOURCES = sorted(
    s for s, p in ORGANISER_EV_POLICY.items() if p["status"] in ("allowed", "conditions")
)
BANNED_CIRCUITS = sorted(CIRCUIT_EV_BAN)


def ev_status(source: str, circuit: str):
    """Resolve the EV policy shown for one event row, or None when unknown.
    A circuit ban wins over the organiser's own policy."""
    ban = CIRCUIT_EV_BAN.get(circuit)
    if ban:
        return {"status": "banned", **ban}
    p = ORGANISER_EV_POLICY.get(source)
    return dict(p) if p else None
