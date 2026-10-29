#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
cd "$(dirname "$0")"

if ! command -v npm >/dev/null 2>&1; then
  if command -v pkg >/dev/null 2>&1; then
    pkg install -y nodejs-lts
  else
    echo "ثبّت Node.js 20 أو أحدث ثم أعد المحاولة." >&2
    exit 1
  fi
fi
npm ci
npm run build
