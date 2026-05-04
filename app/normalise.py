import hashlib
import re
from datetime import date

# Canonical circuit names. Keys are lowercase tokens that may appear in
# scraped strings; the value is the canonical display name.
CIRCUIT_ALIASES = {
    "silverstone": "Silverstone",
    "donington": "Donington Park",
    "brands hatch": "Brands Hatch",
    "brands": "Brands Hatch",
    "snetterton": "Snetterton",
    "oulton": "Oulton Park",
    "cadwell": "Cadwell Park",
    "castle combe": "Castle Combe",
    "anglesey": "Anglesey",
    "trac mon": "Anglesey",
    "bedford": "Bedford Autodrome",
    "thruxton": "Thruxton",
    "croft": "Croft",
    "knockhill": "Knockhill",
    "pembrey": "Pembrey",
    "blyton": "Blyton Park",
    "rockingham": "Rockingham",
    "mallory": "Mallory Park",
    "lydden": "Lydden Hill",
    "goodwood": "Goodwood",
    "llandow": "Llandow",
    "curborough": "Curborough",
    # ---- Europe ----
    "spa": "Spa-Francorchamps",
    "francorchamps": "Spa-Francorchamps",
    # Specific circuit-layout aliases must come before the generic "nurburgring"
    # alias so we don't lose the layout (Nordschleife / GP) distinction.
    "nordschleife": "Nürburgring (Nordschleife)",
    "nordschl": "Nürburgring (Nordschleife)",
    "nürburgring (nordschleife)": "Nürburgring (Nordschleife)",
    "nurburgring (nordschleife)": "Nürburgring (Nordschleife)",
    "nürburgring (grand prix)": "Nürburgring (Grand Prix)",
    "nurburgring (grand prix)": "Nürburgring (Grand Prix)",
    "nurburgring": "Nürburgring (Grand Prix)",
    "nürburgring": "Nürburgring (Grand Prix)",
    "zandvoort": "Zandvoort",
    "hockenheim": "Hockenheim",
    "magny-cours": "Magny-Cours",
    "magny cours": "Magny-Cours",
    "imola": "Imola",
    "mugello": "Mugello",
    "le mans": "Le Mans (Bugatti)",
    "paul ricard": "Paul Ricard",
    "navarra": "Circuito de Navarra",
    "portimao": "Portimão",
    "portimão": "Portimão",
    "estoril": "Estoril",
    "barcelona": "Barcelona-Catalunya",
    "catalunya": "Barcelona-Catalunya",
    "monza": "Monza",
    "assen": "TT Circuit Assen",
    "valencia": "Valencia (Ricardo Tormo)",
    "jerez": "Jerez",
}


def canonical_circuit(raw: str) -> str:
    s = re.sub(r"\s+", " ", raw or "").strip().lower()
    for token, canonical in CIRCUIT_ALIASES.items():
        if token in s:
            return canonical
    return raw.strip() if raw else "Unknown"


# Static EUR -> GBP rate; refreshed manually. UI footer disclaims as indicative.
EUR_TO_GBP = 0.85


def parse_price(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"[£€]\s*([\d,]+(?:\.\d+)?)", text)
    if not m:
        m = re.search(r"([\d,]+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def to_gbp(amount: float | None, currency: str) -> float | None:
    if amount is None:
        return None
    cur = (currency or "GBP").upper()
    if cur == "GBP":
        return amount
    if cur == "EUR":
        return round(amount * EUR_TO_GBP, 2)
    return amount  # unknown -> treat as GBP


def parse_noise(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d{2,3})\s*db", text, flags=re.I)
    return int(m.group(1)) if m else None


def make_dedup_key(source: str, circuit: str, event_date: date, organiser: str,
                   external_id: str | None = None, session: str | None = None) -> str:
    parts = [source, organiser.lower(), circuit.lower(), event_date.isoformat()]
    if external_id:
        parts.append(external_id.lower())
    elif session:
        parts.append(session.lower())
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
