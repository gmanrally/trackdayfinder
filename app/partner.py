"""The GMR card that sits beside the sister-site strip.

GM Racing, TrackdayFinder and MotorsportEventFinder are the same workshop, so
this is own-brand advertising rather than a paid placement. It says so: UK ad
rules want a marketing communication to be identifiable as one, and "from the
same workshop" is both the honest line and the one most likely to be trusted
by somebody who has just used the site for free.

Deliberately not a banner. It inherits the sibling strip's tone - a card, a
sentence, a link - because the thing that makes the strip work is that it does
not feel sold at.

The product rotates by day rather than at random: deterministic output keeps a
cached page honest, and a visitor who reloads twice does not see the shop
flicker through its catalogue.
"""
from __future__ import annotations

import os
from datetime import date

ENABLED = os.environ.get("GMR_PROMO", "1") != "0"
BASE = "https://gmracing.co.uk"
UTM = "utm_source=trackdayfinder&utm_medium=partner&utm_campaign=sibling_strip"

# still: a few KB, loaded on every page. anim: ~300KB, fetched only on hover,
# so the turntable costs nothing to the people who never look at it.
PRODUCTS = [
    {
        "slug": "honda-k20-race-kit-car-itb-kit",
        "still": "/static/gmr/9-still.webp",
        "anim": "/static/gmr/9.webp",
        "head": "Individual throttle bodies for the K20",
        "blurb": "Complete carbon induction kits, built to your engine "
                 "and made in the UK.",
    },
    {
        "slug": "peugeot-306-405-gti6-mi16-plug-and-play-itb-kit",
        "still": "/static/gmr/29-still.webp",
        "anim": "/static/gmr/29.webp",
        "head": "Plug and play ITBs for the Mi16",
        "blurb": "Bolt-on throttle bodies for the 306 and 405 GTi6 "
                 "— no engine changes needed.",
    },
    {
        "slug": "gmr-airbox-for-dcoe",
        "still": "/static/gmr/11-still.webp",
        "anim": "/static/gmr/11.webp",
        "head": "Carbon airboxes, made to fit",
        "blurb": "Flow-developed enclosed induction for SF/OBX and "
                 "DCOE throttle bodies.",
    },
]


def promo() -> dict | None:
    """Today's card, or None when the promo is switched off."""
    if not ENABLED:
        return None
    p = PRODUCTS[date.today().toordinal() % len(PRODUCTS)]
    return {**p, "url": f"{BASE}/product/{p['slug']}?{UTM}",
            "shop_url": f"{BASE}/shop?{UTM}"}
