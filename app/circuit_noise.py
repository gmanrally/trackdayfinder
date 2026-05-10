"""Per-circuit static noise limits (dB).

Published by the circuits / MSV / Javelin / OpenTrack and broadly stable.
Some circuits run occasional 'open noise' or 'low noise' days that
deviate — those are rare and we accept getting them wrong rather than
fetch every event detail page.

Used at ingest time as a fallback when a scraper didn't supply a noise
value. Keys are canonical circuit names (matching CIRCUIT_COORDS).
"""

# Static dB measured at the standard track noise testing position.
# Drive-by is typically 92 dB at most UK circuits and isn't stored
# yet (Event.noise_limit_db is single-valued).
CIRCUIT_STATIC_NOISE_DB: dict[str, int] = {
    # MSV-operated UK circuits
    "Brands Hatch":          105,
    "Cadwell Park":          105,
    "Donington Park":         98,
    "Oulton Park":           105,
    "Snetterton":            105,
    # Other UK circuits (publicly published values)
    "Anglesey":              105,
    "Bedford Autodrome":     105,
    "Castle Combe":          100,
    "Croft":                 105,
    "Curborough":            105,
    "Goodwood":              105,
    "Knockhill":             105,
    "Llandow":               105,
    "Lydden Hill":           100,
    "Mallory Park":          105,
    "Pembrey":               105,
    "Silverstone":           102,
    "Thruxton":              105,
    # Commonly-run EU circuits (where noise is limited and consistent)
    "Nürburgring (Nordschleife)": 130,
    "Spa-Francorchamps":     100,
    "Zandvoort":              98,
    "Zolder":                100,
    "TT Circuit Assen":      100,
    "Mettet":                102,
    "Bilster Berg":          103,
    "Hockenheim":             95,
}
