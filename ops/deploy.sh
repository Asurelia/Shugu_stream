#!/usr/bin/env bash
# Redeploy Shugu on the VPS after a `git push` from the dev machine.
# Safe to rerun — each step is idempotent. Call with `./ops/deploy.sh`.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "▶ Shugu deploy — $(date -Is)"
echo "▶ Pulling latest from origin…"
git pull --ff-only

echo "▶ Installing frontend deps (npm ci is fast if lockfile unchanged)…"
cd "$ROOT/frontend"
if [[ -f package-lock.json ]]; then
  npm ci --no-audit --no-fund
else
  npm install --no-audit --no-fund
fi

echo "▶ Building frontend (Next production)…"
npx next build

echo "▶ Installing / refreshing backend deps (pyproject.toml)…"
cd "$ROOT/backend"
if [[ ! -d venv ]]; then
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install --quiet --disable-pip-version-check -e .
deactivate

echo "▶ Restarting PM2 services…"
pm2 restart shugu-frontend shugu-backend --update-env
pm2 save >/dev/null

echo "✔ Deploy done."
