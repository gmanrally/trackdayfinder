# TrackdayFinder

Aggregates UK trackday listings by scraping organiser websites directly, normalises them, and serves a single search/filter UI.

## Quickstart (local)

```powershell
cd "C:\Users\Graham Work\trackdayfinder"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
python -m app.cli refresh        # run all scrapers once
python -m app.main                # web UI on http://127.0.0.1:8766
```

## Layout

- `app/scrapers/` — one module per source. Each exposes `async def fetch() -> list[RawEvent]`.
- `app/models.py` — SQLModel schema (Event, ScrapeRun).
- `app/normalise.py` — circuit-name canonicalisation, dedup keys.
- `app/ingest.py` — runs scrapers, upserts into the DB.
- `app/main.py` — FastAPI app + nightly scheduler (03:00 local).
- `data/trackdays.db` — SQLite store.
- `Dockerfile` / `docker-compose.yml` / `deploy/` — production deploy bundle.

## Sources (10)

MSV (car + bike), Javelin, OpenTrack, Circuit Days, Silverstone (car + bike),
RMA, MOT, No Limits, Goldtrack, Motorsport Events.

## Adding a source

1. Copy `app/scrapers/_template.py` to `app/scrapers/<name>.py`.
2. Implement `fetch()` returning `list[RawEvent]`.
3. Register it in `app/scrapers/__init__.py`.

## Deploy (Hostinger VPS / any Ubuntu host)

```bash
git clone <your-repo> /opt/trackdayfinder
cd /opt/trackdayfinder
sudo DOMAIN=yourdomain.com EMAIL=you@yourdomain.com bash deploy/install.sh
```

Updates: `cd /opt/trackdayfinder && git pull && docker compose up -d --build`
