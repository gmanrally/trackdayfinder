# EV policy research across all scraped sources

Researched 2026-08-22 (four parallel web-research passes over official FAQ/terms/rules
pages). Basis for a future `ORGANISER_EV_POLICY` static table + `CIRCUIT_EV_BAN`
overrides (same pattern as `CIRCUIT_STATIC_NOISE_DB`). Confidence: high = read on the
organiser's own page; medium = ambiguous/secondary; low = inference.

## Explicit bans (organiser-level)

| Source | Policy | Evidence | Conf |
|---|---|---|---|
| three_sisters | **No EVs of any kind, including hybrids** | "Three Sisters Circuit will not allow electric vehicles of any kind - including hybrids" — threesisterscircuit.co.uk/cars/car-track-days | high |
| trackday_solutions | **No EVs** (with open-wheelers, superkarts, SUVs) | "Open wheelers, Super karts, SUVs and Electric vehicles are not allowed." — trackday-solutions.co.uk/faq | high |
| skylimit | **No EVs** (with large SUVs), all venues, EN/NL/DE/FR | "electric vehicles (EVs) and large SUVs are not permitted" — skylimitevents.com/en/event/113/document/15292 | high |

## Allowed with conditions

| Source | Conditions | Evidence | Conf |
|---|---|---|---|
| msv | EV/HEV/PHEV allowed; not permitted in garages, dedicated bays; charging billed as high power usage | car.msvtrackdays.com/FAQ/Booked | high |
| javelin | Declare at booking; standard unmodified EVs only; **banned at Blyton Park, Mallory Park, Anglesey** (Anglesey also bans hybrids) | javelintrackdays.co.uk/trackdays/terms | high |
| silverstone | Governing-body approval + risk assessment + vehicle details ≥14 days before event; EV charge points on site | silverstone.co.uk/terms-and-conditions/car-track-days-terms-conditions | high |
| opentrack | General terms silent; Anglesey listings state "No Electric or Hybrid vehicles permitted"; elsewhere allowed by omission | opentrack.co.uk/view-dates | medium |

## Allowed

| Source | Notes | Evidence | Conf |
|---|---|---|---|
| castle_combe | "EVs are welcome on any circuit-organised Car Track Day"; 2× Autel 7.4kW chargers (Boost eCharge) | castlecombecircuit.co.uk 2025-12-18 sustainability post | high |
| msevents | No formal policy but FAQ lists Teslas among attending cars | motorsport-events.com/pages/trackday-faq | medium |

## No published policy

goodwood, pembrey, llandow (hosted a 2021 EV-only day in practice), kirkistown,
circuit_days, nolimits (bikes), goldtrack, rma, mot, slipandgrip, trackobsession,
ventrax, ollies_secret, trackdays_events (aggregator, no EV attribute),
rsr_nurburg, destination_nurburgring/dnevents (min 1200cc rule implies ICE framing but
no EV mention), gedlich, curbstone, df_trackdays, europa (aggregator, no EV filter),
paddock_gt (no functioning website).

Special cases:
- **lotus_on_track** — admission not addressed, but event pages: "Strictly no electric
  vehicle charging from garage" (medium).
- **nurburgring_tf** — official Fahrordnung/safety rules are powertrain-neutral
  (road-legal per StVZO); public fast chargers on site. EVs run Touristenfahrten as a
  matter of course, but no explicit EV policy page exists (high).

## Circuit-level bans (override organiser policy)

| Circuit | Scope | Sources |
|---|---|---|
| Anglesey | EVs **and hybrids** banned | Javelin terms + OpenTrack listings + Ventrax research note (3 independent) |
| Three Sisters | EVs and hybrids banned | Circuit's own site |
| Blyton Park | EVs banned | Javelin terms only (single source — verify before publishing) |
| Mallory Park | EVs banned | Javelin terms only (single source — verify before publishing) |

## Design implications

1. Two layers: `ORGANISER_EV_POLICY` (allowed / conditions / not_allowed / unknown)
   + `CIRCUIT_EV_BAN` overriding to banned regardless of organiser.
2. Publishing "banned" claims about third parties needs a source URL + last-checked
   date on the event page tooltip/detail, and a "policies change — confirm with the
   organiser" hedge everywhere.
3. ~70% of sources publish nothing → default display must be "check with organiser",
   never a green tick by omission (msevents/nurburgring_tf style medium evidence
   should display as "reported OK" not "allowed").
