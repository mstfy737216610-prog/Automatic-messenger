#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

cd "$(dirname "$0")"
if ! command -v pkg >/dev/null 2>&1; then
  echo "هذا السكربت مخصص لـ Termux على Android." >&2
  exit 1
fi

pkg update -y
pkg install -y x11-repo
pkg install -y python python-pip chromium ffmpeg tesseract curl ca-certificates

if [ ! -d .venv ]; then
  python -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

mkdir -p data tmp
chmod 700 data || true

if ! tesseract --list-langs 2>/dev/null | grep -qx 'ara'; then
  TESSDATA_DIR="${TESSDATA_PREFIX:-${PREFIX:-/data/data/com.termux/files/usr}/share/tessdata}"
  mkdir -p "$TESSDATA_DIR"
  echo "تنزيل بيانات OCR العربية من مشروع Tesseract الرسمي…"
  OCR_DOWNLOADED=false
  for OCR_URL in \
    https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/ara.traineddata \
    https://cdn.jsdelivr.net/gh/tesseract-ocr/tessdata_fast@main/ara.traineddata; do
    if curl -fL --retry 2 --connect-timeout 20 "$OCR_URL" -o "$TESSDATA_DIR/ara.traineddata.part"; then
      mv "$TESSDATA_DIR/ara.traineddata.part" "$TESSDATA_DIR/ara.traineddata"
      OCR_DOWNLOADED=true
      break
    fi
    rm -f "$TESSDATA_DIR/ara.traineddata.part"
  done
  if [ "$OCR_DOWNLOADED" != true ]; then
    echo "تعذّر تنزيل بيانات OCR العربية من المصدرين؛ تحقق من الشبكة ثم أعد التثبيت." >&2
    exit 1
  fi
fi

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env || true
  echo "أُنشئ .env فارغ المفتاح؛ أضف AI_API_KEY قبل اختبار الذكاء الاصطناعي."
fi

if [ ! -f dist/index.html ]; then
  bash build_frontend.sh
fi

export PLAYWRIGHT_BROWSERS_PATH=0
python -m automation doctor
printf '\nاكتمل التثبيت. شغّل: bash start.sh\n'
printf 'الوضع الافتراضي آمن: DRY_RUN=true وPUBLISHING_ENABLED=false\n'
