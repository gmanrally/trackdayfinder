from . import (
    msv, javelin, opentrack, circuit_days, silverstone, rma,
    mot, nolimits, goldtrack, msevents, goodwood,
    slipandgrip, trackobsession,
)

SCRAPERS = {
    "msv": msv,
    "javelin": javelin,
    "opentrack": opentrack,
    "circuit_days": circuit_days,
    "silverstone": silverstone,
    "rma": rma,
    "mot": mot,
    "nolimits": nolimits,
    "goldtrack": goldtrack,
    "msevents": msevents,
    "goodwood": goodwood,
    "slipandgrip": slipandgrip,
    "trackobsession": trackobsession,
}

# Display names — for the UI Source filter dropdown and the events table.
ORGANISER_DISPLAY = {
    "msv": "MSV Trackdays",
    "javelin": "Javelin Trackdays",
    "opentrack": "OpenTrack",
    "circuit_days": "Circuit Days",
    "silverstone": "Silverstone",
    "rma": "RMA Track Days",
    "mot": "MOT Trackdays",
    "nolimits": "No Limits Trackdays",
    "goldtrack": "Goldtrack",
    "msevents": "Motorsport Events",
    "goodwood": "Goodwood Motor Circuit",
    "slipandgrip": "Slip and Grip Automotive",
    "trackobsession": "Track Obsession",
}
