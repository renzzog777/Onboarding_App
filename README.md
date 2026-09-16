# Peripheral Test Webapp

A small webapp for advisors to test the mouse, keyboard, headset, and
webcam on macOS equipment before it's handed off, and automatically
generate a PDF report stored for later consulting.

## How it works

1. The **home page** ("IT Onboarding Tools") shows two tiles: **Peripheral
   Tests** and **Tutorials**.
2. Peripheral Tests: advisor enters their **full name** and **CIM
   number**, then goes through four tests in order: **Mouse -> Keyboard ->
   Headset -> Webcam**. Each uses the browser's device APIs directly - no
   software install needed on the Mac.
3. After the webcam step, a PDF report is generated automatically and
   saved, and the result (`PASS` / `PARTIAL` / `FAIL`) is stored in a local
   SQLite database. The advisor sees their result on screen, but does
   **not** get the PDF - only admins can retrieve it, from History.
4. A password-gated **Admin** area (nav bar, or `/admin/login`) has two
   sections: **History** (search past sessions by name or CIM, download
   any report) and **Manage Tutorials** (upload/delete PDFs and videos).
5. Advisors browse whatever's been uploaded, with thumbnails, on the
   public **Tutorials** page.

## Local development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

This starts a local dev server on `https://<your-ip>:5000` with a
self-signed certificate (needed for camera/mic access from any origin
other than `localhost`). You'll see a browser warning the first time -
click through it.

## Production deployment

See `deploy/README.md` for the full guide: Gunicorn + Nginx + systemd,
first on an internal Ubuntu VM (Boxes on Fedora) and then replicated
as-is on a Hostinger instance.

## Project layout

```
app.py              Flask routes and request handling
database.py         SQLite persistence (sessions + test results)
pdf_report.py        Builds the PDF report and computes pass/fail
templates/           Jinja2 HTML pages
static/css, static/js   Frontend styling and device-test logic
reports/             Generated PDFs + webcam snapshots (created at runtime)
data/                SQLite database file (created at runtime)
uploads/tutorials/   Admin-uploaded PDF/video tutorials (created at runtime)
deploy/              Nginx, systemd, and cert-generation files for hosting
```

## Admin tutorial uploads

`/admin/login` gates `/admin/resources`, where PDFs and videos can be
uploaded (each gets a title + type) and deleted. The password comes from
the `ADMIN_PASSWORD` environment variable - set it in
`deploy/peripheral-test.service` before deploying (see `deploy/README.md`).
Advisors browse everything uploaded, grouped by type, at `/tutorials`.

Video uploads can be large, so `MAX_CONTENT_LENGTH` is set to 2GB in
`app.py` and Nginx's `client_max_body_size`/timeouts are raised to match
in `deploy/nginx.conf` - if you need bigger files than that, both need to
be raised together.

## Notes on the tests

- **Mouse**: detects left/right/middle clicks and scroll direction; also
  flags unintended double-clicks (two clicks under 60ms apart), which
  usually indicates a mouse needing repair.
- **Keyboard**: renders an on-screen ANSI layout, including a numeric
  keypad (matching the Macally keyboards sent to advisors), and
  highlights each key as it's pressed. The report explicitly lists which
  keys were never tested rather than just showing a percentage.
- **Headset**: plays a panned tone to each ear (Web Audio API) for the
  advisor to confirm, and uses `getUserMedia` + an audio analyser to show
  a live microphone level meter.
- **Webcam**: live preview via `getUserMedia`, a snapshot is captured and
  embedded in the PDF so you can visually confirm image quality later.

Overall pass/fail logic lives in `pdf_report.py` (`evaluate_*` functions)
if you want to adjust the thresholds.

## Appearance

The UI is a dark, minimalist theme (`static/css/style.css`) pairing
Fraunces (serif, for headings) with Inter (sans, for body/UI), loaded
from Google Fonts in `base.html`. Since advisors' Macs load that font
CDN over their own internet connection (not the VM's), no server-side
network access is needed for this - but if a Mac has no internet at all,
the page still works fine, just falling back to system fonts.
