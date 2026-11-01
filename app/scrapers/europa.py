"""Europa Trackdays — https://en.europatrackdays.com/calendar-full

Aggregator listing ~600 trackdays across UK + EU, server-rendered. We use
it as a *gap-filler* — every event is checked against our existing DB by
(date + canonical circuit + organiser-token overlap) and skipped if already
covered by a primary scraper. Net effect: only events we wouldn't otherwise
see are ingested.

The cards used to carry schema.org microdata and no longer do; see the note
above CARD_SEL for the shape they have now and what is safe to key on.
"""
from __future__ import annotations
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from sqlmodel import select
from ._base import RawEvent, get_html
from ..models import Event, session as db_session

SOURCE_SLUG = "europa"
ORGANISER_BASE = "Europa Trackdays"
LIST_URL = "https://en.europatrackdays.com/calendar-full"
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "debug"

# Map Europa's circuit names (left side of 'CIRCUIT - ORGANISER') to the
# canonical CIRCUIT_COORDS keys we use elsewhere. Anything not in here is
# passed through as-is and may trigger a 'missing coords' audit warning.
CIRCUIT_NAME_MAP = {
    "nurburgring nordschleife":     "Nürburgring (Nordschleife)",
    "nurburgring grand prix":       "Nürburgring (Grand Prix)",
    "nurburgring gp":               "Nürburgring (Grand Prix)",
    "nurburgring":                  "Nürburgring",
    "blyton park":                  "Blyton Park",
    "blyton park driving centre":   "Blyton Park",
    "cervesina":                    "Autodromo di Vairano",  # placeholder; Tazio Nuvolari
    "tazio nuvolari circuit":       "Autodromo di Vairano",
    "ecuyers (beuvardes)":          "Circuit des Ecuyers",
    "ecuyers":                      "Circuit des Ecuyers",
    "circuit des ecuyers":          "Circuit des Ecuyers",
    "folembray":                    "Folembray",
    "circuit de folembray":         "Folembray",
    "mirecourt":                    "Mirecourt",
    "circuit de mirecourt":         "Mirecourt",
    "nogaro":                       "Nogaro",
    "circuit de nogaro":            "Nogaro",
    "zandvoort":                    "Zandvoort",
    "circuit de bresse":            "Bresse",
    "bresse":                       "Bresse",
    "circuits de vendée":           "Fontenay-le-Comte",
    "circuit de croix-en-ternois":  "Croix-en-Ternois",
    "croix-en-ternois":             "Croix-en-Ternois",
    "circuit de clastres":          "Clastres",
    "clastres":                     "Clastres",
    "circuit de ledenon":           "Lédenon",
    "ledenon":                      "Lédenon",
    "lédenon":                      "Lédenon",
    "circuit de fay-de-bretagne":   "Fay de Bretagne",
    "circuit du mas du clos":       "Mas du Clos",
    "mas du clos":                  "Mas du Clos",
    "circuit du mans bugatti":      "Le Mans (Bugatti)",
    "circuit du mans":              "Le Mans (Bugatti)",
    "circuit de chenevières":       "Chenevières",
    "chenevières":                  "Chenevières",
    "circuit du laquais":           "Le Laquais",
    "circuit de torcy":             "Torcy",
    "circuit de zolder":            "Zolder",
    "circuit de zandvoort":         "Zandvoort",
    "circuit de spa-francorchamps": "Spa-Francorchamps",
    "spa-francorchamps":            "Spa-Francorchamps",
    "spa francorchamps":            "Spa-Francorchamps",
    "circuit paul ricard":          "Paul Ricard",
    "circuit d'hockenheim":         "Hockenheim",
    "circuit de dijon-prenois":     "Dijon-Prenois",
    "dijon-prenois":                "Dijon-Prenois",
    "circuit de magny-cours":       "Magny-Cours",
    "magny-cours":                  "Magny-Cours",
    "magny-cours gp":               "Magny-Cours",
    "circuit de lurcy-levis":       "Lurcy-Levis",
    "lurcy-levis":                  "Lurcy-Levis",
    "circuit du bourbonnais":       "Bourbonnais",
    "circuit du luc":               "Le Luc",
    "circuit du var (le luc)":      "Le Luc",
    "bilster berg drive resort":    "Bilster Berg",
    "bilster berg":                 "Bilster Berg",
    "racepark meppen":              "Meppen Racepark",
    "meppen":                       "Meppen Racepark",
    "circuit de mettet":            "Mettet",
    "mettet":                       "Mettet",
    "tt circuit assen":             "TT Circuit Assen",
    "assen":                        "TT Circuit Assen",
    "circuit de barcelone-catalunya": "Barcelona-Catalunya",
    "barcelona-catalunya":          "Barcelona-Catalunya",
    "monza":                        "Monza",
    "imola":                        "Imola",
    "mugello":                      "Mugello",
    "portimao":                     "Portimão",
    "estoril":                      "Estoril",
    "valencia ricardo tormo":       "Valencia (Ricardo Tormo)",
    "jerez":                        "Jerez",
    "autodrom most":                "Autodrom Most",
    "automotodrom brno":            "Automotodrom Brno",
    "pannonia ring":                "Pannonia Ring",
    "slovakia ring":                "Slovakia Ring",
    "sachsenring":                  "Sachsenring",
    "motorsport arena oschersleben": "Motorsport Arena Oschersleben",
    "circuit de l'anneau du rhin":  "Anneau du Rhin",
    "anneau du rhin":               "Anneau du Rhin",
    "red bull ring":                "Red Bull Ring",
    "red bull ring (spielberg)":    "Red Bull Ring",
}

# Cards. Until late 2026 each one was an <a itemscope> carrying schema.org
# microdata — name as "<Circuit> - <Organiser>", a description, and a
# startDate. All of it is gone: the markup is now plain divs with French
# class names, and nothing on the page says schema.org any more. The site
# kept answering 200 with 600-odd events on it, so the scraper went on
# reporting a clean run with nothing found for months.
#
#   <a href="https://en.europatrackdays.com/trackday/33066/anneau-du-rhin-porsche-club-alsace-2026-11-01">
#     <div class="agendaLigne">
#       <div class="agendaElement agendaDate …"><span>Sunday</span>…</div>
#       <div class="agendaElement agendaCircuit"><img alt="France"><span>Anneau du Rhin</span></div>
#       <div class="agendaElement agendaOrganisateur"><span>Porsche Club Alsace</span></div>
#       <div class="agendaElement agendaMeteo">10°</div>
#       <div class="agendaElement agendaResume">Porsche day.</div>
#
# The date is taken from the tail of the href rather than from .agendaDate,
# which gives a localised "Sunday 1 Nov" with no year on it. Every one of
# the 608 links carries a trailing ISO date, and an id that doubles as the
# dedup key — so the one durable thing on the page is the thing we key on.
CARD_SEL = "div.agendaLigne"
HREF_DATE_RE = re.compile(r"/trackday/(\d+)/[a-z0-9-]*?-(\d{4}-\d{2}-\d{2})/?$")
PRICE_RE = re.compile(r"(?:from\s*)?(£|€)\s*([\d.,]+)", re.I)

# The circuit's country comes off the flag image beside its name. The old
# code hard-coded region="EU" on the grounds that UK events here are always
# already covered by a primary scraper — true of most of the 89 UK cards,
# but a small UK organiser nobody else lists would have been filed as EU.
# Ireland groups with UK, matching SOURCE_REGION for trackdays_ie.
UK_COUNTRIES = {"united kingdom", "great britain", "england", "scotland",
                "wales", "northern ireland", "ireland"}


def _card_text(card, cls: str) -> str:
    node = card.css_first(f"div.{cls}")
    if not node:
        return ""
    return " ".join(node.text(separator=" ", strip=True).split())


def _card_country(card) -> str:
    node = card.css_first("div.agendaCircuit img")
    return (node.attributes.get("alt") or "") if node else ""


def _card_href(card) -> str:
    """The enclosing event link. The card is wrapped in its <a>, but walk up
    a few levels rather than assuming the card is the anchor's only child."""
    node = card.parent
    for _ in range(3):
        if node is None:
            return ""
        if (node.tag or "").lower() == "a":
            href = node.attributes.get("href") or ""
            if "/trackday/" in href:
                return href
        node = node.parent
    return ""


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s: str) -> set[str]:
    s = _norm(s)
    return set(re.findall(r"[a-z0-9]+", s))


async def fetch() -> list[RawEvent]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    tree = await get_html(LIST_URL, timeout=40.0)
    html = tree.html or ""
    (DEBUG_DIR / "europa.html").write_text(html, encoding="utf-8", errors="ignore")

    # Build a "covered" index from our existing DB so we can dedup. We
    # store both tokenised sets (for token-overlap match) and the joined
    # alphanumeric string (for substring fallback — handles cases where
    # Europa writes 'DFTrackdays' but our DB has 'DF Trackdays', etc.).
    today = date.today()

    def _flat(s: str) -> str:
        # 'DF Trackdays' / 'DFTrackdays' both → 'dftrackdays'
        return re.sub(r"[^a-z0-9]", "", _norm(s))

    covered: dict[date, list[tuple[set[str], set[str], str, str]]] = {}
    with db_session() as s:
        for e in s.exec(select(Event).where(Event.event_date >= today)).all():
            covered.setdefault(e.event_date, []).append(
                (_tokens(e.circuit), _tokens(e.organiser),
                 _flat(e.circuit), _flat(e.organiser))
            )

    out: list[RawEvent] = []
    seen: set[str] = set()
    for card in tree.css(CARD_SEL):
        href = _card_href(card)
        if not href:
            continue
        m = HREF_DATE_RE.search(href)
        if not m:
            continue
        eid, dstr = m.group(1), m.group(2)
        if eid in seen: continue
        seen.add(eid)
        try:
            event_date = date.fromisoformat(dstr)
        except ValueError:
            continue
        if event_date < today:
            continue

        circuit_raw = _card_text(card, "agendaCircuit")
        organiser = _card_text(card, "agendaOrganisateur") or "Europa Trackdays"
        desc = _card_text(card, "agendaResume")
        if not circuit_raw:
            continue

        circuit = CIRCUIT_NAME_MAP.get(_norm(circuit_raw), circuit_raw)

        # Dedup: same date, then a strong organiser match (token overlap or
        # flattened-string substring) PLUS at least one shared circuit token.
        # Word order on circuit names varies between sources ('Racepark
        # Meppen' vs 'Meppen Racepark'), so circuit-token-overlap is more
        # robust than substring there.
        STOP = {"circuit","de","du","la","le","les","des","et","the","of","and",
                "trackday","trackdays","events","event","day","days"}
        slug_circ_t = _tokens(circuit) - STOP
        slug_org_t = _tokens(organiser) - STOP
        slug_org_flat = _flat(organiser)
        slug_circ_flat = _flat(circuit)
        deduped = False
        for db_circ_t, db_org_t, db_circ_flat, db_org_flat in covered.get(event_date, []):
            db_circ_meaningful = db_circ_t - STOP
            db_org_meaningful = db_org_t - STOP
            org_match = (
                len(slug_org_t & db_org_meaningful) >= 1
                or (len(slug_org_flat) >= 5 and len(db_org_flat) >= 5
                    and (slug_org_flat in db_org_flat or db_org_flat in slug_org_flat))
            )
            circuit_match = (
                len(slug_circ_t & db_circ_meaningful) >= 1
                or (len(slug_circ_flat) >= 5 and len(db_circ_flat) >= 5
                    and (slug_circ_flat in db_circ_flat or db_circ_flat in slug_circ_flat))
            )
            if org_match and circuit_match:
                deduped = True; break
        if deduped:
            continue

        # Price from description ('From €280', 'Starting from £169', etc.)
        currency = "EUR"; price_text = None
        pm = PRICE_RE.search(desc)
        if pm:
            sym, amt = pm.group(1), pm.group(2)
            currency = "GBP" if sym == "£" else "EUR"
            price_text = f"{sym}{amt}"

        # Per-event source slug isn't useful — they all live under 'europa'
        # in our SCRAPERS dict. The display organiser is the Europa-reported
        # one ("Drive Academie", "Curbstone Track Events", ...).
        # All Europa events are EU by definition (the aggregator is FR-based,
        # and even UK events listed here are filtered out as already-covered
        # in the dedup pass above).
        out.append(RawEvent(
            source=SOURCE_SLUG,
            organiser=organiser or ORGANISER_BASE,
            circuit_raw=circuit,
            event_date=event_date,
            booking_url=href,
            title=None,
            price_text=price_text,
            currency=currency,
            session="day",
            external_id=eid,
            region=("UK" if _norm(_card_country(card)) in UK_COUNTRIES else "EU"),
            # Deliberately not the card's own blurb: 129 of them mention a
            # half-day, a morning or an evening as an option on the day, and
            # ingest._infer_session reads notes to relabel the session, so
            # passing it through would retitle a fifth of the listing.
            notes=f"Listed via Europa Trackdays — book at {organiser}.",
        ))
    return out
