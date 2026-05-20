# Self-hosted Umami analytics

One-time setup on the VPS to bring up a free, GDPR-friendly analytics
dashboard at `https://analytics.trackdayfinder.co.uk`, with the tracking
script loaded by the main site when the right env vars are set.

## 1. DNS

Add an A record:

```
analytics.trackdayfinder.co.uk   A   187.77.181.187
```

Wait for it to resolve (`nslookup analytics.trackdayfinder.co.uk` from
anywhere) before continuing.

## 2. Generate two secrets

On the VPS:

```bash
openssl rand -hex 32  # → use for APP_SECRET
openssl rand -hex 20  # → use for POSTGRES_PASSWORD
```

## 3. Start Umami

```bash
mkdir -p /opt/trackdayfinder-analytics
# Copy this folder's docker-compose.yml into /opt/trackdayfinder-analytics/
# Edit the two CHANGE_ME placeholders (POSTGRES_PASSWORD + APP_SECRET).
cd /opt/trackdayfinder-analytics
docker compose up -d
docker compose logs -f umami   # wait until you see "Listening on 3000"
```

## 4. nginx vhost + TLS

```bash
cp nginx.analytics.conf /etc/nginx/sites-available/analytics.trackdayfinder.co.uk
ln -s ../sites-available/analytics.trackdayfinder.co.uk /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d analytics.trackdayfinder.co.uk
```

## 5. First-run setup in Umami

Visit `https://analytics.trackdayfinder.co.uk` and sign in with
`admin` / `umami`. **Immediately change the admin password.**

Click **Settings → Websites → Add website**:
- Name: TrackdayFinder
- Domain: trackdayfinder.co.uk

After saving, click into the website and copy the **Website ID** (UUID)
from the **Tracking code** section.

## 6. Tell the app to load the tracking script

Edit `/opt/trackdayfinder/docker-compose.yml`, under the app service
`environment:` section, add:

```yaml
- UMAMI_SRC=https://analytics.trackdayfinder.co.uk/script.js
- UMAMI_WEBSITE_ID=<paste the website UUID here>
```

Then:

```bash
cd /opt/trackdayfinder
docker compose up -d
```

Visit `https://trackdayfinder.co.uk` and check view-source — you should
see `<script defer src="https://analytics.trackdayfinder.co.uk/script.js" data-website-id="…">`
just before `</head>`.

## What Umami records

- Pageviews (URL, referrer, country, device, browser, OS) — no IPs stored
- Outbound clicks to organisers (Umami auto-tracks `<a target="_blank">`
  with the `data-umami-event` attribute, otherwise just the URL)
- No cookies, no cross-site tracking — UK GDPR-friendly, no banner needed

## Internal `Click` table

The `/go/<id>` redirect already records clicks into your DB with bot
filtering. Umami is the *visitor-side* analytics; the internal table
remains the source of truth for booking-click counts per organiser /
circuit / event, and you can see it at `/admin/clicks?token=<token>`.
