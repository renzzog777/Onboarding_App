# Deployment Guide

This app is meant to be deployed the same way in both places, so what you
build on the UTM VM should carry over almost unchanged to Hostinger:

    Advisor's Mac (browser)
            |  HTTPS
            v
        Nginx (TLS termination, reverse proxy)
            |  HTTP, 127.0.0.1:8000
            v
        Gunicorn (WSGI server running app.py)
            |
            v
        SQLite (data/tests.db) + PDF files (reports/)

Why HTTPS matters here: browsers block camera/microphone access
(`getUserMedia`) on any origin that isn't `https://` or `localhost`. Since
advisors will reach this over the network (not localhost), TLS is required
even for internal testing - that's why the stack below always runs behind
Nginx with a certificate, self-signed for now, real once you're on
Hostinger.

## 1. Create the Ubuntu Server ARM64 VM in UTM

1. Download the **ARM64** Ubuntu Server ISO (not amd64) from
   `ubuntu.com/download/server/arm` - this matters since UTM on Apple
   Silicon needs an ARM64 guest image.
2. In UTM, create a new VM and choose **Virtualize**, not **Emulate**.
   "Virtualize" uses Apple's Virtualization framework to run the ARM64
   guest close to native speed; "Emulate" would software-emulate a whole
   different CPU architecture and is dramatically slower - you only want
   that if you were forced to run an x86_64 guest, which isn't the case
   here.
3. Attach the ISO, allocate resources (2 vCPU / 2GB RAM is plenty for this
   app), and make sure **UEFI Boot** is enabled in the VM's settings - UTM
   turns this on by default for its Linux template, but double check if
   you customized the VM, since ARM64 Linux needs UEFI to boot.
4. **Networking**: UTM defaults new VMs to **Shared Network** (NAT),
   which isolates the VM behind your Mac - advisors on other machines
   can't reach it directly. In the VM's network settings, switch to
   **Bridged (Advanced)** and select your active interface (Wi-Fi or
   Ethernet) so the VM gets its own IP on your LAN, same idea as the
   Boxes bridging from before.
   - If bridged networking is flaky on your Wi-Fi (this can happen on
     some Mac Wi-Fi chipsets/routers), fall back to **Shared Network**
     and add port-forward rules in UTM (host `80`/`443` -> guest
     `80`/`443`) so advisors reach `https://<your-mac-ip>` instead.
5. Install Ubuntu Server, then note the VM's IP with `ip a`.

Everything below is unchanged by the switch to ARM64/UTM - it's still
plain Ubuntu Server, and every package used (Nginx, Python, Gunicorn,
certbot) has ARM64 builds, so `apt install` and `pip install -r
requirements.txt` work exactly as written.

## 2. Base packages on the VM

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip nginx git ufw ffmpeg poppler-utils
```

`ffmpeg` generates video tutorial thumbnails; `poppler-utils` (specifically
`pdftoppm`) generates PDF thumbnails. Both are plain system tools invoked
as subprocesses - no PDF/video-processing Python package is needed, which
avoids a real problem: PyMuPDF (an earlier approach) has no prebuilt wheel
for newer Python versions on ARM64, and its source build breaks against
Python 3.14's headers. If you already tried installing PyMuPDF, no need to
remove it - it's just unused; `requirements.txt` no longer lists it.

## 3. Deploy the app

```bash
sudo mkdir -p /opt/peripheral_test_app
sudo chown $USER:$USER /opt/peripheral_test_app
# copy the project here, e.g.:
#   scp -r peripheral_test_app/* youruser@vm-ip:/opt/peripheral_test_app/
cd /opt/peripheral_test_app

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

Create the data/report directories and hand ownership to the service user
(the systemd unit runs as `www-data`):

```bash
mkdir -p data reports/snapshots uploads/tutorials
sudo chown -R www-data:www-data /opt/peripheral_test_app
```

## 4. Gunicorn as a systemd service

Before copying the unit file, open `deploy/peripheral-test.service` and set
a real `ADMIN_PASSWORD` - this gates the `/admin` tutorial-upload pages.
Leaving the placeholder means the app falls back to an insecure default.

```bash
sudo cp deploy/peripheral-test.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now peripheral-test
sudo systemctl status peripheral-test
```

## 5. TLS certificate (internal VM - self-signed)

```bash
chmod +x deploy/generate_self_signed_cert.sh
./deploy/generate_self_signed_cert.sh
```

Advisors will get a browser warning the first time they visit; they click
through it once (e.g. "Advanced" -> "Proceed") and camera/mic access will
work normally after that.

## 6. Nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/peripheral-test
sudo ln -s /etc/nginx/sites-available/peripheral-test /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

## 7. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

If you bridged the VM onto your LAN, this is enough - advisors on the same
network browse to `https://<vm-ip>` (accepting the certificate warning
once).

## 8. Replicating on Hostinger later

Same steps 2-7, on the Hostinger VPS, with two differences:

- **DNS**: point a real domain (or subdomain) at the Hostinger server's
  public IP before starting.
- **Certificate**: skip step 5 (self-signed) entirely. Instead:

  ```bash
  sudo apt install -y certbot python3-certbot-nginx
  sudo certbot --nginx -d yourdomain.com
  ```

  Certbot edits `deploy/nginx.conf`'s cert lines in place to point at a
  real Let's Encrypt certificate and sets up auto-renewal - no browser
  warning for advisors, and no manual cert management going forward.

Everything else (systemd unit, Nginx proxy config, Gunicorn, the Flask app
itself) is identical between the two environments, which is the point of
testing on the UTM VM first.

## 9. Updating the app after the first deploy

Once the VM is running, don't run `git` there at all - it just leads to
ownership and credential headaches for no benefit. Instead, keep your
repo and all commits on your Mac, and use `deploy/deploy.sh` to push
code over `rsync`+SSH and restart the service in one step:

1. Open `deploy/deploy.sh` and edit the three variables at the top
   (`VM_USER`, `VM_HOST`, `VM_PATH`) to match your VM.
2. Make it executable once: `chmod +x deploy/deploy.sh`
3. From then on, whenever you've made changes on your Mac:
   ```bash
   ./deploy/deploy.sh
   ```
   This copies your code to the VM (skipping `venv/`, `__pycache__/`,
   `.git/`, and - importantly - `data/` and `reports/`, so the live
   database and saved PDFs on the VM are never touched or overwritten),
   then restarts `peripheral-test` automatically.

You'll be prompted for your VM password (or nothing, if you've set up
SSH keys) since it connects over plain SSH - no GitHub token, no git
identity, no permission changes on the VM ever required.

## Backups

`data/tests.db` and `reports/` are the only stateful pieces - everything
else is code. Back these two up periodically (e.g. `rsync` to your Mac,
outside the VM) so historical reports survive a VM rebuild.
