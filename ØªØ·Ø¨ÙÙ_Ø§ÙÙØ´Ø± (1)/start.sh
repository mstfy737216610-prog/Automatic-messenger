#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
cd "$(dirname "$0")"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env || true
  echo "أُنشئ .env؛ أضف AI_API_KEY ثم أعد التشغيل." >&2
  exit 1
fi
if [ ! -f dist/index.html ]; then
  bash build_frontend.sh
fi

export PLAYWRIGHT_BROWSERS_PATH=0
python -m automation doctor
HOST_VALUE="$(python - <<'PY'
from automation.config import get_settings
print(get_settings().host)
PY
)"
PORT_VALUE="$(python - <<'PY'
from automation.config import get_settings
print(get_settings().port)
PY
)"
printf '\nمرسال يعمل على http://%s:%s — أوقفه بـ Ctrl+C\n' "$HOST_VALUE" "$PORT_VALUE"
exec python -m automation serve
