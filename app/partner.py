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
        "blurb": "Complete carbon composite induction kits, built to your "
                 "engine and made in the UK.",
    },
    {
        "slug": "peugeot-306-405-gti6-mi16-plug-and-play-itb-kit",
        "still": "/static/gmr/29-still.webp",
        "anim": "/static/gmr/29.webp",
        "head": "Plug and play ITBs for the GTi6 Mi16",
        "blurb": "Bolt-on throttle bodies for the 306 and 405 "
                 "\u2014 no engine changes needed.",
    },
    {
        "slug": "gmr-airbox-for-dcoe",
        "still": "/static/gmr/11-still.webp",
        "anim": "/static/gmr/11.webp",
        "head": "Carbon composite airboxes, made to fit",
        "blurb": "Flow-developed enclosed induction for SF/OBX and "
                 "DCOE throttle bodies.",
    },
    # The accessories. Cheaper, and what somebody who already has throttle
    # bodies is actually short of. No turntable rendered for these yet, so
    # they run as a still.
    {
        "slug": "gmr-sf-throttle-linkage",
        "still": "/static/gmr/20-still.webp",
        "anim": "",
        "head": "Throttle linkage for SF/OBX bodies",
        "blurb": "Three parts, one adjustment, and a quadrant shaped for "
                 "control at small openings.",
    },
    {
        "slug": "gmr-velocity-stacks-straight",
        "still": "/static/gmr/25-still.webp",
        "anim": "",
        "head": "Velocity stacks, made to your spacing",
        "blurb": "Carbon composite trumpets in any length, bored to suit "
                 "your throttle bodies.",
    },
    {
        "slug": "gmr-throttle-body-idle-vacuum-manifold",
        "still": "/static/gmr/14-still.webp",
        "anim": "",
        "head": "Idle vacuum manifold for ITBs",
        "blurb": "Brings every runner into one tapping. SF/OBX and DCOE "
                 "versions.",
    },
    {
        "slug": "gmr-sf-obx-throttle-body-idle-vacuum-manifold-copy",
        "still": "/static/gmr/30-still.webp",
        "anim": "",
        "head": "K20 vacuum manifold",
        "blurb": "One tapping off all four runners, for SF/OBX bodies on a "
                 "K20.",
    },
    {
        "slug": "honda-k20-tps-adaptor-kit",
        "still": "/static/gmr/32-still.webp",
        "anim": "",
        "head": "Keep the factory K20 throttle sensor",
        "blurb": "Carries the OEM TPS onto SF/OBX bodies \u2014 same plug, "
                 "same calibration.",
    },
]


# How many events between GMR rows in the list. One in fifty is roughly
# one per screenful of scrolling on a desktop - often enough to be seen,
# rare enough that the list still reads as a list.
PROMO_EVERY = 50


def promo(slot: int = 0) -> dict | None:
    """Today's card, or None when the promo is switched off.

    `slot` walks the catalogue so two promo rows on one page are not the
    same product. Still deterministic per day: a cached page stays honest
    and a reload does not flicker the shop through its range.
    """
    if not ENABLED:
        return None
    p = PRODUCTS[(date.today().toordinal() + int(slot or 0)) % len(PRODUCTS)]
    return {**p, "url": f"{BASE}/product/{p['slug']}?{UTM}",
            "shop_url": f"{BASE}/shop?{UTM}"}
