# WordPress blog at trackdayfinder.co.uk/blog

Self-hosted WordPress on the VPS, sat behind the existing nginx so it
shares the main site's TLS cert. Theme styling pasted into Customizer →
Additional CSS to mirror the TrackdayFinder look-and-feel.

## 1. Generate three secrets locally (or on VPS)

```bash
openssl rand -hex 24   # → MARIADB_PASSWORD (DB user)
openssl rand -hex 24   # → MARIADB_ROOT_PASSWORD
# (no third secret — WP generates its own salts on first run)
```

## 2. Copy files onto the VPS

From your local checkout:

```bash
scp -r deploy/blog/* root@187.77.181.187:/tmp/blog-deploy/
```

Or `git pull` on the VPS and copy from `/opt/trackdayfinder/deploy/blog/`.

## 3. Bring up the WP + DB stack

On the VPS:

```bash
mkdir -p /opt/trackdayfinder-blog
cp /opt/trackdayfinder/deploy/blog/docker-compose.yml /opt/trackdayfinder-blog/
nano /opt/trackdayfinder-blog/docker-compose.yml   # replace the three CHANGE_ME_ values
cd /opt/trackdayfinder-blog
docker compose up -d
docker compose logs -f blog                         # wait for "ready to handle connections"
```

Then make WP's files reachable by nginx (it needs the same root the
container sees as `/var/www/html`):

```bash
mkdir -p /var/www
ln -s /var/lib/docker/volumes/trackdayfinder-blog_blog-wp-data/_data /var/www/blog
ls /var/www/blog                                    # should list wp-admin, wp-content, etc.
```

## 4. nginx routing

Edit your existing main-site vhost (HTTPS block):

```bash
nano /etc/nginx/sites-available/trackdayfinder.co.uk
```

Paste the contents of `nginx.snippet.conf` (both blocks) INSIDE the
`server { ... }` for port 443. Test + reload:

```bash
nginx -t && systemctl reload nginx
```

## 5. WordPress first-run setup

Visit `https://trackdayfinder.co.uk/blog/` in your browser. WordPress
should display the install wizard. Pick a language and fill in:

- Site Title: `TrackdayFinder Blog`
- Admin username: anything but `admin`
- Strong password
- Your email

After login, set permalinks to `Post name`:
**Settings → Permalinks → Post name → Save**

(Pretty URLs only work because the nginx snippet's `try_files` falls
through to `index.php`.)

## 6. Apply the TrackdayFinder skin

Choose any modern block-friendly theme — Twenty Twenty-Five or
Twenty Twenty-Four are fine — then:

**Appearance → Editor → Styles → Additional CSS**

(Older themes: **Appearance → Customize → Additional CSS**.)

Paste the whole contents of `theme-customizer.css`. Save.

The blog will then carry the same navy/red palette, Inter typeface, card
surfaces, and accent colours as the main site.

## 7. (Optional) Header logo + nav matching the main site

In the WP block editor:

- **Editor → Template Parts → Header** — replace the default with:
  - Image block: upload `app/static/logo-light.svg` from this repo
  - Navigation block with links pointing back to the main site
    (`/`, `/circuits`, `/organisers`, `/map`, `/calendar`)
- **Editor → Template Parts → Footer** — change to a simple copyright
  line: `© {year} GMRacing.co.uk · TrackdayFinder.co.uk`

## 8. Tell your SEO tool about the blog

In `seo-studio` (or whichever SEO tool you're plugging in), add the
site:
- URL: `https://trackdayfinder.co.uk/blog/`
- WP REST API: `https://trackdayfinder.co.uk/blog/wp-json/`
- Auth: create an Application Password in **Users → Profile → Application
  Passwords** and use it for publishing.

## Backups

The two named volumes hold all state:

```bash
docker run --rm -v trackdayfinder-blog_blog-db-data:/data \
    -v $(pwd):/backup alpine \
    tar czf /backup/blog-db-$(date +%F).tar.gz -C / data

docker run --rm -v trackdayfinder-blog_blog-wp-data:/data \
    -v $(pwd):/backup alpine \
    tar czf /backup/blog-wp-$(date +%F).tar.gz -C / data
```

Schedule those via cron weekly and rsync them off the box.

## Updating WordPress

WP core, themes, and plugins can be updated from the WP admin UI as
normal. Updating the container itself (PHP version, security patches):

```bash
cd /opt/trackdayfinder-blog
docker compose pull
docker compose up -d
```
