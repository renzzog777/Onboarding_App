#!/bin/bash
# Generates a self-signed certificate for internal testing (Boxes VM).
# On Hostinger, skip this entirely and use certbot for a real Let's
# Encrypt certificate instead.
set -e

sudo mkdir -p /etc/ssl/peripheral-test

sudo openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout /etc/ssl/peripheral-test/selfsigned.key \
  -out /etc/ssl/peripheral-test/selfsigned.crt \
  -subj "/CN=peripheral-test.local"

echo ""
echo "Self-signed certificate created at /etc/ssl/peripheral-test/"
echo "Advisors will see a browser certificate warning the first time they"
echo "visit - they need to click through it (e.g. Advanced -> Proceed) to"
echo "reach the site and allow camera/mic access."
