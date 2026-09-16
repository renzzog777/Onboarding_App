#!/bin/bash
# deploy.sh
# Run this FROM YOUR MAC, from inside the project folder (the one with
# app.py, templates/, deploy/, etc.). It syncs your code to the VM over
# SSH and restarts the service - no git, no GitHub credentials, and no
# permission wrangling ever needed on the VM itself.
#
# Usage: ./deploy/deploy.sh
set -euo pipefail

# --- Edit these three for your setup ---
VM_USER="renzzo"                       # your username on the Ubuntu VM
VM_HOST="192.168.1.50"                 # the VM's LAN IP (from `ip a` on the VM)
VM_PATH="/opt/peripheral_test_app"     # where the app lives on the VM
# ----------------------------------------

# This script lives in <project>/deploy/, so the project root is one level up.
LOCAL_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Syncing $LOCAL_PATH -> $VM_USER@$VM_HOST:$VM_PATH ..."

rsync -avz --delete \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '.DS_Store' \
  --exclude 'data' \
  --exclude 'reports' \
  "$LOCAL_PATH"/ "$VM_USER@$VM_HOST:$VM_PATH"/

echo "Restarting the service on the VM..."
ssh "$VM_USER@$VM_HOST" "sudo systemctl restart peripheral-test"

echo "Done. Check it with:"
echo "  ssh $VM_USER@$VM_HOST 'systemctl status peripheral-test'"
