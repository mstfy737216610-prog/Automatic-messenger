from __future__ import annotations

import argparse
import asyncio
import json
import platform
import shutil
import sys
from pathlib import Path

from . import __version__
from .ai import AIError, AIProvider
from .browser import BrowserRuntime, import_storage_state, session_path, workflows
from .config import PROJECT_ROOT, get_settings
from .db import Database
from .maintenance import archive_account, cleanup_files, create_backup
from .pipeline import AutomationPipeline


def _db() -> Database:
    settings = get_settings()
    return Database(settings.database_path)


def doctor() -> int:
    settings = get_settings()
    db = _db()
    checks: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))

    add("Python", sys.version_info >= (3, 11), platform.python_version())
    add("SQLite قابل للكتابة", db.path.exists(), str(db.path))
    add("واجهة الويب المبنية", (PROJECT_ROOT / "dist/index.html").exists(), "npm run build عند الحاجة")
    ffmpeg = shutil.which("ffmpeg")
    add("FFmpeg", bool(ffmpeg), ffmpeg or "pkg install ffmpeg")
    tesseract = shutil.which("tesseract")
    add("Tesseract", bool(tesseract), tesseract or "pkg install tesseract")
    chromium = settings.chromium_executable
    add("Chromium", bool(chromium), chromium or "pkg install chromium بعد تفعيل x11-repo")
    add("مفتاح AI", bool(settings.ai_api_key and settings.ai_api_key.get_secret_value()), "مضبوط" if settings.ai_api_key else "راجع .env")
    add("وضع عدم النشر", settings.dry_run or not settings.publishing_enabled,
        f"DRY_RUN={settings.dry_run}, PUBLISHING_ENABLED={settings.publishing_enabled}")
    width = max(len(name) for name, _, _ in checks)
    for name, ok, detail in checks:
        print(f"{'✓' if ok else '✗'} {name:<{width}}  {detail}")
    # عدم توفر Chromium/AI يمنع الأتمتة لكنه لا يمنع تشغيل الواجهة وإدارة الإعدادات.
    return 0


async def login(account_id: str) -> int:
    settings = get_settings()
    account = _db().get_account(account_id)
    if not account:
        print("الحساب غير موجود", file=sys.stderr)
        return 2
    config = workflows()["platforms"][account["platform"]]
    print("سيفتح Chromium. سجّل الدخول يدويًا وأكمل أي تحقق، ثم عد هنا واضغط Enter.")
    print("على Termux تحتاج Termux:X11 للمتصفح المرئي، أو استخدم import-cookies من متصفحك.")
    async with BrowserRuntime(settings, account, headless=False) as runtime:
        page = await runtime.context.new_page()
        await page.goto(config["session_url"], wait_until="domcontentloaded")
        await asyncio.to_thread(input, "اضغط Enter بعد ظهور حسابك داخل الصفحة… ")
        await runtime.save_state()
    print(f"حُفظت الجلسة في: {session_path(settings, account)}")
    return 0


async def monitor(account_id: str) -> int:
    result = await AutomationPipeline(get_settings(), _db()).monitor_account(account_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def models() -> int:
    try:
        values = await AIProvider(get_settings(), _db()).list_models()
        print("\n".join(values))
        return 0
    except AIError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mirsal", description="مرسال — أتمتة محلية على Termux")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="فحص البيئة دون كشف الأسرار")
    sub.add_parser("serve", help="تشغيل الواجهة والعامل")
    login_parser = sub.add_parser("login", help="تسجيل دخول يدوي وحفظ الجلسة")
    login_parser.add_argument("account_id")
    import_parser = sub.add_parser("import-cookies", help="استيراد storage state أو Cookies JSON")
    import_parser.add_argument("account_id")
    import_parser.add_argument("file", type=Path)
    monitor_parser = sub.add_parser("monitor", help="فحص مصادر حساب مرة واحدة")
    monitor_parser.add_argument("account_id")
    sub.add_parser("models", help="عرض نماذج مزود الذكاء الاصطناعي")
    sub.add_parser("backup", help="نسخة مضغوطة للجلسات وقاعدة البيانات")
    sub.add_parser("cleanup", help="حذف السجلات والوسائط الأقدم من مدة الاحتفاظ")
    archive_parser = sub.add_parser("archive-account", help="ضغط ملفات حساب واحد")
    archive_parser.add_argument("account_id")
    archive_parser.add_argument("--include-media", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    if args.command == "doctor":
        raise SystemExit(doctor())
    if args.command == "serve":
        import uvicorn
        uvicorn.run("automation.server:create_app", factory=True, host=settings.host, port=settings.port,
                    log_level=settings.log_level.lower())
        return
    if args.command == "login":
        raise SystemExit(asyncio.run(login(args.account_id)))
    if args.command == "import-cookies":
        account = _db().get_account(args.account_id)
        if not account:
            raise SystemExit("الحساب غير موجود")
        payload = json.loads(args.file.read_text(encoding="utf-8"))
        path = import_storage_state(settings, account, payload)
        print(f"حُفظت الجلسة: {path}")
        return
    if args.command == "monitor":
        raise SystemExit(asyncio.run(monitor(args.account_id)))
    if args.command == "models":
        raise SystemExit(asyncio.run(models()))
    db = _db()
    if args.command == "backup":
        print(create_backup(settings, db))
        return
    if args.command == "archive-account":
        print(archive_account(settings, args.account_id, args.include_media))
        return
    if args.command == "cleanup":
        result = {"database": db.cleanup(settings.log_retention_days),
                  "files": cleanup_files(settings, settings.media_retention_days)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
