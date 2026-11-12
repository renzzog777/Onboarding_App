# IT Onboarding Tools — Onboarding Test Webapp

A self-service webapp for IT advisors to test the mouse, keyboard, headset,
webcam and network connection on macOS equipment before it's handed off to
an employee, and
automatically generate a PDF report for IT's records. It also hosts a
library of macOS setup tutorials (PDFs) that advisors can browse.

Built with Flask, SQLite, and vanilla JavaScript using native browser
device APIs — no software installation required on the advisor's Mac.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Environment Variables](#environment-variables)
- [Local Development](#local-development)
- [Deployment](#deployment)
  - [Option A — Dokploy (recommended, current production setup)](#option-a--dokploy-recommended-current-production-setup)
  - [Option B — Docker Compose + Caddy + Watchtower](#option-b--docker-compose--caddy--watchtower)
  - [Option C — Bare-metal (systemd + Nginx)](#option-c--bare-metal-systemd--nginx)
- [Database](#database)
- [Security Notes](#security-notes)

---

## Features

### Home page
A dark, minimalist landing page ("IT Onboarding Tools") with two entry
points: **Onboarding Tests** and **Tutorials**.

### Onboarding testing flow
An advisor enters the employee's **full name** and **CIM number**, selects
whether the Mac is on **Wi-Fi or Ethernet** (with a hint pointing to
System Settings → Network → Ethernet for advisors who aren't sure), and is
walked through five tests in order:

1. **Mouse test** — click zone detects left/right/middle clicks and scroll
   up/down. Flags an **unintended double-click** (two clicks under 60ms
   apart), which usually indicates a mouse needing repair.
2. **Keyboard test** — an interactive on-screen ANSI keyboard layout
   (including the numeric keypad, matching the Macally keyboards sent to
   advisors) highlights each key as it's physically pressed. Function keys
   (F1–F12) are intentionally excluded, since macOS commonly maps them to
   system shortcuts (brightness, volume, Mission Control) rather than
   passing through a plain keypress. The report explicitly lists any keys
   that were never tested rather than just showing a percentage.
3. **Headset test** — plays a panned tone to each ear (Web Audio API) for
   the advisor to confirm, shows a live microphone level meter
   (`getUserMedia` + an audio analyser), and **requires** the advisor to
   record themselves counting from 1 to 10. The recording is saved on the
   server, tagged with the employee's name, CIM number, and session ID,
   and is downloadable later from the admin History page — the test
   cannot be completed without a recording.
4. **Webcam test** — live camera preview with snapshot capture. The
   advisor **cannot continue** unless they either capture a
   snapshot or provide a written explanation for why one couldn't be
   taken (e.g. "camera hardware failed to initialize") — enforced both in
   the browser and on the server, so this can't be bypassed.
5. **Network test** — runs in the browser (Terminal is restricted on
   advisor Macs) against Cloudflare's public speed-test servers
   (`speed.cloudflare.com`), measuring the same metrics as macOS's
   `networkQuality`. The section **fails** if any minimum is missed:

   | Metric | Minimum |
   |---|---|
   | Downlink capacity | 20 Mbps |
   | Uplink capacity | 5 Mbps |
   | Idle latency | 50 ms or less |
   | Responsiveness | Medium or better (Low < 200, Medium 200–999, High 1000+ RPM) |

   Jitter and latency under load are also recorded. Thresholds live in
   `NETWORK_THRESHOLDS` in `pdf_report.py`. If the test can't run, the
   advisor must explain why (section becomes `PARTIAL`).

   Best-effort findings are shown as **warnings that never fail the
   report**: the advisor answers how the Mac is connected (directly to the
   ISP modem, router, Wi-Fi extender, mesh, cellular gateway — a web page
   can't see the local network, so this is advisor-reported); the server
   looks up who owns the Mac's public IP (Team Cymru whois, no API key,
   `network_lookup.py`) to flag cellular carriers, satellite, iCloud
   Private Relay–style relays, and data-centre/VPN/security providers;
   and `1.1.1.1/cdn-cgi/trace` flags Cloudflare WARP. The server needs
   outbound access to `whois.cymru.com:43` for the provider lookup; if
   it's blocked, the report just shows the provider as unknown.

After the network step, a **PDF report is generated automatically** and the
result (`PASS` / `PARTIAL` / `FAIL` per section and overall) is saved.
Advisors see their result on screen but do **not** get the PDF — only
admins can retrieve it, from History.

### PDF report contents
- Employee name, CIM number, session ID
- **Test Started** (the moment "Start Test" was clicked) and **Report
  Generated** timestamps, tracked separately
- Network connection type (Wi-Fi/Ethernet) and the advisor's client IP
  address
- Overall PASS/PARTIAL/FAIL banner
- A detailed, per-section breakdown (buttons detected, keys tested,
  audio/mic confirmation, webcam snapshot embedded inline, or the
  advisor's explanation if one wasn't captured, network speeds against
  the minimums, internet provider, and connection/VPN warnings)

### Admin area (password-gated)
Accessible via **Admin** in the nav, gated by an `ADMIN_PASSWORD`
environment variable:

- **History** — every test session, searchable by name or CIM number,
  showing status, network type, and download links for the PDF report and
  voice recording. Admins can **permanently delete** a session, which
  removes its PDF, webcam snapshot, and voice recording from disk along
  with the database record.
- **Manage Tutorials** — upload PDF guides (with a title; PDFs only,
  100 MB max), or delete existing ones. Thumbnails are generated
  automatically from the first page of each PDF via `pdftoppm`
  (poppler-utils). Generation is best-effort — a failed thumbnail never
  blocks the upload, it just falls back to a text placeholder.

### Public Tutorials page
Advisors browse the uploaded PDF guides, each shown with its thumbnail,
and can download them directly.

### Tutorials assistant (optional)
An **Ask the assistant** panel on the Tutorials page answers advisors'
questions using **only** the uploaded PDF guides, with links to the guide
each answer came from. It uses Gemini API File Search (Google chunks,
embeds and searches the PDFs, so there's no vector database to run) and is
adapted from the
[Chatbot_onboarding](https://github.com/juandpg1205/Chatbot_onboarding)
proof of concept.

- **Knowledge base = the Tutorials page.** Uploading a PDF in Manage
  Tutorials indexes it in the background (a minute or two); deleting it
  removes it from the index. The Manage Tutorials table shows each guide's
  *Indexed* / *Indexing* status. Guides uploaded before the key was set are
  indexed at the next app start.
- **Guardrails** (OWASP Top 10 for LLM Applications): answers only from the
  documents, refuses other topics and prompt-injection attempts, discards
  any answer without a citation, renders answers as plain text, English
  only, and caps usage (500 characters per question, 10 questions per
  minute per visitor, 800 output tokens, 85 s per question).
- **Hidden** unless `GEMINI_API_KEY` is set.
- **Privacy:** on the free tier of the Gemini API, Google may use what you
  send to improve its products. Only upload guides you're allowed to share
  outside your organization.

### Appearance
A dark, minimalist theme pairing **Fraunces** (serif, for headings) with
**Inter** (sans, for body/UI), loaded from Google Fonts. A muted brass/gold
accent color is used throughout rather than a generic bright accent.

---

## Tech Stack

- **Backend:** Python, Flask, Gunicorn
- **Database:** SQLite (no separate database server)
- **PDF generation:** ReportLab
- **PDF thumbnails:** `pdftoppm` (poppler-utils)
- **Tutorials assistant:** Gemini API File Search (`google-genai`)
- **Frontend:** Server-rendered Jinja2 templates, vanilla JavaScript (no
  framework, no build step), native browser APIs (`getUserMedia`,
  `MediaRecorder`, Web Audio API, Canvas)
- **Containerization:** Docker (Python 3.12-slim base image)

---

## Project Structure

```
app.py                  Flask routes and request handling
database.py              SQLite persistence (sessions + tutorial resources)
pdf_report.py            Builds the PDF report and computes pass/fail
network_lookup.py        Public-IP owner lookup for the network test (cellular/VPN flags)
chatbot.py               Tutorials assistant (Gemini File Search) + knowledge base sync
templates/               Jinja2 HTML pages
static/css, static/js    Styling and per-test device logic
reports/                 Generated PDFs, webcam snapshots, voice recordings
data/                    SQLite database file (created at runtime)
uploads/tutorials/       Admin-uploaded PDF tutorials + thumbnails

Dockerfile               Production image (Python 3.12-slim + poppler-utils)
.dockerignore
docker-compose.yml        App + Caddy (reverse proxy/HTTPS) + Watchtower (auto-updates)
Caddyfile                 Reverse proxy config for the docker-compose path
.env.example              Template for the environment variables
.github/workflows/        GitHub Actions - builds & publishes a Docker image to GHCR
                           (used by the docker-compose path; not required by Dokploy,
                           which builds directly from the Dockerfile in this repo)

deploy/                   Legacy bare-metal deployment files (Nginx config,
                           systemd service) - see Option C below
```

All three deployment paths (Dokploy, Docker Compose, bare-metal) live
side by side in this repo. Pick the one matching how you're actually
hosting it — see below.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ADMIN_PASSWORD` | Yes | Gates `/admin/*` (History, Manage Tutorials). Without it, the app falls back to an insecure default (`changeme`) and logs a warning — never leave this unset in production. |
| `GEMINI_API_KEY` | No | Google AI Studio API key (https://aistudio.google.com → Get API key) for the Tutorials assistant. Leave unset to hide the assistant. |
| `GEMINI_MODEL` | No | Primary Gemini model (default `gemini-3.5-flash`); fallbacks are listed in `chatbot.py`. Change it if Google renames or retires the model. |

---

## Local Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

This starts a local dev server on `https://<your-ip>:5000` with a
self-signed certificate — browsers require HTTPS (or `localhost`) for
camera/microphone access, which is why the dev server enables TLS even
locally. You'll see a certificate warning the first time; click through it.

You'll also need poppler installed locally (`brew install poppler` on
macOS) for PDF tutorial thumbnail generation to work in development.

---

## Deployment

### Option A — Dokploy (recommended, current production setup)

[Dokploy](https://dokploy.com) is a self-hosted deployment platform
(installed on the VPS itself) that builds directly from this repo's
`Dockerfile` and manages its own reverse proxy + automatic HTTPS — no
separate Nginx/Caddy config or GHCR image needed for this path.

1. In Dokploy: **Create Project → Create Service → Application**.
2. **General tab:** Provider = GitHub, select this repo and the branch
   you push to (confirm it matches what you actually push to — this has
   been a real source of confusion, see note below). Enable **Auto
   Deploy** so every push triggers a rebuild automatically via webhook.
3. **Build:** Build Type = Dockerfile, path `./Dockerfile`, context `.`.
4. **Environment tab:** add `ADMIN_PASSWORD=<a-real-password>`.
5. **Volumes tab (critical):** Dokploy re-clones the repo fresh on every
   deploy, which would wipe anything bind-mounted from inside the repo
   checkout. Use Dokploy's **named Volumes** (not bind mounts) with these
   mount paths: `/app/data`, `/app/reports`, `/app/uploads`. Getting this
   wrong means the database and uploaded files vanish on the next deploy.
6. **Domains tab:** add your domain, Port `8000` (matches Gunicorn's port
   in the Dockerfile), enable HTTPS via Let's Encrypt.
7. Point your domain's DNS **A record** at the VPS's IP before deploying —
   Let's Encrypt can only issue a certificate once it can verify the
   domain resolves here.
8. Open the firewall: `sudo ufw allow OpenSSH && sudo ufw allow 80/tcp &&
   sudo ufw allow 443/tcp && sudo ufw enable`.
9. Click **Deploy**.

**From then on:** `git push` to the branch Dokploy is watching triggers an
automatic rebuild and redeploy — no manual steps on the server at all.

> **Branch note:** Dokploy's "Branch" field must exactly match the branch
> you actually push to. If they don't match (e.g. Dokploy watching `main`
> while you push to `master`, or vice versa), pushes silently never
> trigger a deploy. Check Dokploy's General tab if updates stop appearing.

### Option B — Docker Compose + Caddy + Watchtower

An alternative for a VPS without Dokploy, using the `docker-compose.yml`,
`Caddyfile`, and `.env` files directly:

1. Set up CI/CD: this repo's GitHub Actions workflow
   (`.github/workflows/docker-publish.yml`) builds a multi-arch image and
   pushes it to GHCR on every push to the branch it's configured for.
2. On the VPS: install Docker (`curl -fsSL https://get.docker.com | sh`),
   create a folder with just `docker-compose.yml`, `Caddyfile` (with your
   real domain), and `.env` (copied from `.env.example` with a real
   password).
3. `docker login ghcr.io` (if the package is private), then:
   `docker compose pull && docker compose up -d`.
4. Point your domain's DNS at the VPS, open the firewall (same as
   Option A, step 8).

**Watchtower** (bundled as a third container in `docker-compose.yml`)
checks GHCR every 5 minutes and automatically pulls + restarts the app
container when a new image is published — so once this is running,
updates are hands-off here too: push to GitHub, wait a few minutes, done.

### Option C — Bare-metal (systemd + Nginx)

The original deployment path, kept in `deploy/` for reference. Runs the
Flask app directly via a Python virtualenv + Gunicorn, managed by a
systemd service, with Nginx as the reverse proxy/TLS terminator. See
`deploy/README.md` for the full walkthrough. Generally more manual to
maintain than Options A or B — recommended only if you specifically don't
want Docker involved.

---

## Database

SQLite, stored at `data/tests.db`, with two tables:

- **`sessions`** — one row per test session: employee info, timestamps,
  network type/IP, each test's results (stored as JSON per section), the
  overall result, and the path to the generated PDF.
- **`resources`** — uploaded tutorials: title, type (always "pdf"), stored
  filename, original filename, and thumbnail filename.

Schema changes are applied automatically at startup via a lightweight
`ALTER TABLE` migration pattern — no manual migration steps are needed
when pulling in an update that adds a new column.

---

## Security Notes

- Always set a real `ADMIN_PASSWORD` before deploying anywhere reachable
  by advisors or the internet.
- Advisors never have access to download PDF reports or voice recordings
  directly — only admins, via the History page.
- The admin login is a single shared password (no per-user accounts) —
  appropriate for a small internal IT team, not a substitute for real
  authentication if this app's audience grows.
