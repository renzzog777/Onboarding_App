# Peripheral Test Webapp - production image
#
# python:3.12-slim is intentional: it sidesteps the exact problem we hit
# deploying straight onto Ubuntu Server (Python 3.14 + ARM64 had no
# PyMuPDF wheel and a broken source build). Docker decouples the app's
# Python version from whatever the host VPS ships - this image carries
# its own, known-good runtime everywhere it runs.

FROM python:3.12-slim

# ffmpeg -> video tutorial thumbnails, poppler-utils (pdftoppm) -> PDF
# thumbnails. Both are subprocess-based, not compiled Python packages -
# the same lesson from the PyMuPDF failure: prefer a system tool over a
# C-extension wheel when one exists, it travels far better across
# platforms.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# These are mount points for the volumes defined in docker-compose.yml -
# created here too so the app works even if run without compose (e.g.
# `docker run` directly, or a first build before volumes attach).
RUN mkdir -p data reports/snapshots reports/recordings uploads/tutorials/thumbnails

EXPOSE 8000

CMD ["gunicorn", "--workers", "3", "--timeout", "300", "--bind", "0.0.0.0:8000", "app:app"]
