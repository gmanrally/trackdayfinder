"""UK postcode geocoding (via postcodes.io) + great-circle distance.

postcodes.io is free, no API key required, and returns latitude/longitude
for any valid UK postcode. We cache results in-process indefinitely
because postcode coordinates don't change.
"""
from __future__ import annotations
import math
import re
from typing import Optional
import httpx

_CACHE: dict[str, Optional[tuple[float, float]]] = {}
_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.I)


def _normalise(pc: str) -> str:
    """Strip spaces and uppercase — postcodes.io tolerates either form
    but we use the spaceless variant as the cache key."""
    return re.sub(r"\s+", "", (pc or "").upper())


async def postcode_to_latlng(postcode: str) -> Optional[tuple[float, float]]:
    """Return (lat, lng) for a UK postcode, or None if invalid / not found.
    Cached in-process; misses make one HTTP call to api.postcodes.io."""
    if not postcode:
        return None
    key = _normalise(postcode)
    if not _POSTCODE_RE.match(key):
        return None
    if key in _CACHE:
        return _CACHE[key]
    url = f"https://api.postcodes.io/postcodes/{key}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.get(url)
        if r.status_code != 200:
            _CACHE[key] = None
            return None
        data = r.json()
        result = data.get("result") or {}
        lat = result.get("latitude"); lng = result.get("longitude")
        if lat is None or lng is None:
            _CACHE[key] = None
            return None
        _CACHE[key] = (float(lat), float(lng))
    except Exception:
        _CACHE[key] = None
    return _CACHE[key]


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in miles between two (lat, lng) pairs."""
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * 3958.7613 * math.asin(math.sqrt(h))
