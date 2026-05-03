#!/usr/bin/env bash
# One-shot installer for a fresh Hostinger VPS (Ubuntu 22.04 / 24.04).
# Run as root or via sudo. Usage:
#   curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/deploy/install.sh | sudo DOMAIN=trackdayfinder.example.com bash
# Or after cloning the repo:
#   sudo DOMAIN=trackdayfinder.example.com bash deploy/install.sh

set -euo pipefail

DOMAIN="${DOMAIN:?Set DOMAIN=your-domain.tld}"
EMAIL="${EMAIL:-admin@$DOMAIN}"
APP_DIR="${APP_DIR:-/opt/trackdayfinder}"
REPO_URL="${REPO_URL:-}"   # optional: git clone URL

apt-get update
apt-get install -y ca-certificates curl gnupg git nginx ufw

# Docker (official repo)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Get the source
if [ ! -d "$APP_DIR" ]; then
    if [ -n "$REPO_URL" ]; then
        git clone "$REPO_URL" "$APP_DIR"
    else
        echo "$APP_DIR doesn't exist and REPO_URL not set — clone the repo manually then re-run."
        exit 1
    fi
fi

cd "$APP_DIR"
docker compose up -d --build

# nginx — install HTTP-only config first; certbot rewrites it with HTTPS.
sed "s/YOUR-DOMAIN.COM/$DOMAIN/g" deploy/nginx.conf > /etc/nginx/sites-available/trackdayfinder
ln -sf /etc/nginx/sites-available/trackdayfinder /etc/nginx/sites-enabled/trackdayfinder
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# certbot via snap
apt-get install -y snapd
snap install core; snap refresh core
snap install --classic certbot
ln -sf /snap/bin/certbot /usr/bin/certbot

# Issue cert AND let certbot edit the nginx config to add the HTTPS server
# block + 80 -> 443 redirect (idempotent — re-running is safe).
certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" \
    --non-interactive --agree-tos -m "$EMAIL" --redirect

nginx -t && systemctl reload nginx

# Firewall: only 22, 80, 443
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo
echo "OK. Visit https://$DOMAIN"
echo "  Logs:        cd $APP_DIR && docker compose logs -f"
echo "  Update:      cd $APP_DIR && git pull && docker compose up -d --build"
echo "  Manual scrape: docker compose exec app python -m app.cli refresh"
