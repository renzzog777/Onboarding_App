# Docker Deployment (Hostinger VPS)

This replaces the old bare-metal approach in `deploy/` (manual Nginx +
systemd + Python venv directly on Ubuntu). That folder is left in place
for reference/rollback, but this is the recommended path going forward -
it fixes the Python-version/architecture fragility that caused the
PyMuPDF failure, since the app now carries its own known-good runtime
inside the image rather than depending on whatever Python the host ships.

## Files

- `Dockerfile` - builds the app image (Python 3.12 + ffmpeg + poppler-utils)
- `.dockerignore` - keeps secrets/build artifacts out of the image
- `docker-compose.yml` - the two-container production stack (app + Caddy)
- `Caddyfile` - reverse proxy config; Caddy handles HTTPS automatically
- `.env.example` - copy to `.env` on the VPS with a real `ADMIN_PASSWORD`
- `.github/workflows/docker-publish.yml` - CI/CD: builds + pushes the
  image to GHCR on every push to `main` and every `v*` tag

## Quick reference

Full step-by-step walkthroughs for all three stages (CI/CD setup,
choosing a Hostinger plan, and deploying on the VPS) were given directly
in chat. In short, once everything is set up:

**Shipping a code change:**
```bash
git add .
git commit -m "..."
git push          # CI builds + pushes the image automatically
```

**Deploying that change to the VPS:**
```bash
ssh youruser@your-vps-ip
cd /opt/new-hires-app
docker compose pull
docker compose up -d
```

**Checking logs on the VPS:**
```bash
docker compose logs -f app
```

**Rolling back to a specific version** (if you tagged one, e.g. `v1.2.0`):
edit the `image:` line in `docker-compose.yml` to that tag instead of
`:latest`, then `docker compose up -d` again.
