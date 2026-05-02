# Deploying KeeperKit

This directory ships everything needed to run the KeeperKit demo server on a
plain Ubuntu/Debian box behind nginx.

## One-shot install

```bash
ssh root@your-server
curl -sSfL https://raw.githubusercontent.com/danilaverbena/keeperkit/main/deploy/install.sh | bash
```

Optional env vars before the pipe:

```bash
export KEEPERHUB_API_KEY=kh_…       # leave unset to run in mock mode
export OPENAI_API_KEY=sk-…          # leave unset to fall back to the heuristic agent
export KEEPERKIT_DOMAIN=keeperkit.example.com
```

After the script finishes:

```bash
curl -s http://localhost/api/health   # must say "ok": true
systemctl status keeperkit            # service should be active (running)
journalctl -u keeperkit -f            # tail logs
```

## Files

| File | Purpose |
|---|---|
| [`install.sh`](install.sh) | Idempotent installer (clone → venv → systemd → nginx). |
| [`keeperkit.service`](keeperkit.service) | Systemd unit running `python -m keeperkit.server`. |
| [`keeperkit.nginx.conf`](keeperkit.nginx.conf) | Reverse proxy from `:80` to `:8000`. |

## Updating

```bash
ssh root@your-server
cd /opt/keeperkit
git pull --rebase
.venv/bin/pip install -e ".[server,langchain]"
systemctl restart keeperkit
```

## Adding HTTPS (optional)

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d keeperkit.example.com
systemctl reload nginx
```
