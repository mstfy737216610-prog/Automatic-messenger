from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .ai import AIError, AIProvider
from .browser import BrowserError, import_storage_state, playwright_proxy
from .config import PROJECT_ROOT, Settings, get_settings, mask_proxy
from .db import Database
from .maintenance import archive_account, cleanup_files, create_backup
from .models import (
    AccountInput,
    AccountPatch,
    AIConfigPatch,
    ChatInput,
    ReviewInput,
    SourceInput,
    SourcePatch,
)
from .pipeline import AutomationPipeline
from .worker import AutomationWorker

log = logging.getLogger(__name__)


class ConfirmInput(BaseModel):
    status: str = Field(pattern="^(published|failed)$")
    note: str = Field(default="", max_length=1000)


class TestAIInput(BaseModel):
    model: str | None = Field(default=None, max_length=150)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_directories()
    db = Database(settings.database_path)
    pipeline = AutomationPipeline(settings, db)
    ai = AIProvider(settings, db)
    worker = AutomationWorker(settings, db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker.start()
        try:
            yield
        finally:
            await worker.stop()

    app = FastAPI(title="مرسال", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.settings = settings
    app.state.worker = worker

    @app.middleware("http")
    async def security_middleware(request: Request, call_next: Any):
        if settings.web_username and settings.web_password:
            expected_user = settings.web_username.encode()
            expected_password = settings.web_password.get_secret_value().encode()
            import base64
            authorized = False
            header = request.headers.get("authorization", "")
            if header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(header[6:], validate=True)
                    user, password = decoded.split(b":", 1)
                    authorized = hmac.compare_digest(user, expected_user) and hmac.compare_digest(password, expected_password)
                except (ValueError, TypeError):
                    authorized = False
            if not authorized:
                return JSONResponse({"detail": "تسجيل الدخول مطلوب"}, status_code=401,
                                    headers={"WWW-Authenticate": 'Basic realm="Mirsal", charset="UTF-8"'})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse({"detail": "بعض الحقول غير صالحة", "errors": jsonable_encoder(exc.errors())}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        log.exception("Unhandled request error: %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "حدث خطأ داخلي؛ راجع سجل النشاط"}, status_code=500)

    def account_or_404(account_id: str) -> dict[str, Any]:
        account = db.get_account(account_id)
        if not account:
            raise HTTPException(404, "الحساب غير موجود")
        return account

    def post_or_404(post_id: str) -> dict[str, Any]:
        post = db.get_post(post_id)
        if not post:
            raise HTTPException(404, "المنشور غير موجود")
        return post

    def account_details(account: dict[str, Any]) -> dict[str, Any]:
        result = Database.public_account(account)
        result["sources"] = db.list_sources(account["id"])
        result["profile"] = db.learning_context(account["id"]).get("profile", {})
        return result

    async def limited_upload(file: UploadFile, maximum: int) -> bytes:
        chunks, size = [], 0
        while chunk := await file.read(1024 * 128):
            size += len(chunk)
            if size > maximum:
                raise HTTPException(413, "حجم الملف تجاوز الحد المسموح")
            chunks.append(chunk)
        return b"".join(chunks)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True, "version": __version__, "dry_run": settings.dry_run,
            "publishing_enabled": settings.publishing_enabled,
            "scheduler": settings.scheduler_enabled,
            "ai": ai.public_config(),
            "chromium_configured": bool(settings.chromium_executable),
            "ffmpeg_configured": bool(shutil.which("ffmpeg")),
            "tesseract_configured": bool(shutil.which("tesseract")),
            "database": str(settings.database_path.name),
        }

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return {
            "stats": db.stats(),
            "accounts": [account_details(a) for a in db.list_accounts()],
            "recent_posts": db.list_posts(limit=8),
            "events": db.list_events(limit=8),
        }

    @app.get("/api/accounts")
    def accounts() -> list[dict[str, Any]]:
        return [account_details(account) for account in db.list_accounts()]

    @app.post("/api/accounts", status_code=201)
    def create_account(data: AccountInput) -> dict[str, Any]:
        if data.proxy_url:
            try:
                playwright_proxy(data.proxy_url)
            except BrowserError as exc:
                raise HTTPException(422, str(exc)) from exc
        account = db.create_account(data.model_dump())
        db.add_event("account_created", f"أُضيف حساب {account['name']}", account["id"])
        return account_details(account)

    @app.get("/api/accounts/{account_id}")
    def get_account(account_id: str) -> dict[str, Any]:
        return account_details(account_or_404(account_id))

    @app.patch("/api/accounts/{account_id}")
    def update_account(account_id: str, data: AccountPatch) -> dict[str, Any]:
        current = account_or_404(account_id)
        updates = data.model_dump(exclude_unset=True)
        minimum = updates.get("min_delay_sec", current["min_delay_sec"])
        maximum = updates.get("max_delay_sec", current["max_delay_sec"])
        if maximum < minimum:
            raise HTTPException(422, "أقصى تأخير يجب ألا يقل عن أدنى تأخير")
        if updates.get("proxy_url"):
            try:
                playwright_proxy(updates["proxy_url"])
            except BrowserError as exc:
                raise HTTPException(422, str(exc)) from exc
        account = db.update_account(account_id, updates)
        db.add_event("account_updated", "حُدّثت إعدادات الحساب", account_id)
        return account_details(account)

    @app.delete("/api/accounts/{account_id}")
    def delete_account(account_id: str) -> dict[str, Any]:
        account_or_404(account_id)
        archive = archive_account(settings, account_id)
        db.delete_account(account_id)
        shutil.rmtree(settings.data_dir / "accounts" / account_id, ignore_errors=True)
        return {"ok": True, "safety_archive": archive.name}

    @app.post("/api/accounts/{account_id}/monitor", status_code=202)
    def monitor_account(account_id: str) -> dict[str, Any]:
        account_or_404(account_id)
        job = db.enqueue("monitor", account_id, max_attempts=2)
        return {"queued": True, "job_id": job, "detail": "أُضيف فحص المصادر إلى الطابور"}

    @app.post("/api/accounts/{account_id}/check-session")
    async def check_session(account_id: str) -> dict[str, str]:
        account_or_404(account_id)
        return await pipeline.check_session(account_id)

    @app.post("/api/accounts/{account_id}/cookies")
    async def upload_cookies(account_id: str, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        account = account_or_404(account_id)
        content = await limited_upload(file, 5 * 1024 * 1024)
        try:
            payload = json.loads(content.decode("utf-8"))
            path = import_storage_state(settings, account, payload)
        except (ValueError, UnicodeDecodeError, BrowserError) as exc:
            raise HTTPException(422, f"ملف الجلسة غير صالح: {exc}") from exc
        db.update_account(account_id, {"session_status": "unknown", "last_error": None})
        db.add_event("session_imported", "استُوردت الجلسة؛ افحصها قبل تفعيل النشر", account_id)
        return {"ok": True, "file": path.name, "status": "unknown"}

    @app.post("/api/accounts/{account_id}/assets")
    async def upload_asset(account_id: str, kind: Annotated[str, Form()],
                           file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        account = account_or_404(account_id)
        if kind not in {"logo", "template"}:
            raise HTTPException(422, "نوع الملف يجب أن يكون logo أو template")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise HTTPException(422, "الصيغ المدعومة: PNG وJPG وWebP")
        content = await limited_upload(file, 12 * 1024 * 1024)
        target_dir = settings.data_dir / "accounts" / account_id / "assets"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{kind}{suffix}"
        target.write_bytes(content)
        from PIL import Image
        try:
            with Image.open(target) as image:
                image.verify()
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(422, "الملف ليس صورة صالحة") from exc
        account_settings = dict(account.get("settings", {}))
        account_settings[f"{kind}_path"] = str(target.relative_to(settings.data_dir))
        db.update_account(account_id, {"settings": account_settings})
        return {"ok": True, "kind": kind, "preview_url": f"/api/accounts/{account_id}/asset/{kind}"}

    @app.get("/api/accounts/{account_id}/asset/{kind}")
    def get_asset(account_id: str, kind: str) -> FileResponse:
        account = account_or_404(account_id)
        if kind not in {"logo", "template"}:
            raise HTTPException(404, "الملف غير موجود")
        relative = account.get("settings", {}).get(f"{kind}_path")
        if not relative:
            raise HTTPException(404, "لم يُرفع ملف بعد")
        path = (settings.data_dir / relative).resolve()
        try:
            path.relative_to(settings.data_dir.resolve())
        except ValueError as exc:
            raise HTTPException(403, "مسار غير مسموح") from exc
        if not path.is_file():
            raise HTTPException(404, "الملف غير موجود")
        return FileResponse(path)

    @app.post("/api/accounts/{account_id}/template-preview")
    async def template_preview(account_id: str) -> dict[str, Any]:
        account = account_or_404(account_id)
        target = settings.data_dir / "accounts" / account_id / "assets/template-preview.png"
        await asyncio.to_thread(
            pipeline.media.render_text_template,
            "جدول محاضرات الأسبوع\nالأحد: رياضيات — القاعة ٢٤\nللاستفسار والمساعدة الطلابية، تواصل معنا.",
            account, target,
        )
        return {"preview_url": f"/api/accounts/{account_id}/asset-preview?v={target.stat().st_mtime}"}

    @app.get("/api/accounts/{account_id}/asset-preview")
    def asset_preview(account_id: str) -> FileResponse:
        account_or_404(account_id)
        path = settings.data_dir / "accounts" / account_id / "assets/template-preview.png"
        if not path.exists():
            raise HTTPException(404, "أنشئ المعاينة أولًا")
        return FileResponse(path)

    @app.get("/api/accounts/{account_id}/sources")
    def sources(account_id: str) -> list[dict[str, Any]]:
        account_or_404(account_id)
        return db.list_sources(account_id)

    @app.post("/api/accounts/{account_id}/sources", status_code=201)
    def add_source(account_id: str, data: SourceInput) -> dict[str, Any]:
        account_or_404(account_id)
        if urlsplit(data.url).scheme not in {"http", "https"}:
            raise HTTPException(422, "رابط المصدر يجب أن يبدأ بـ http أو https")
        try:
            source = db.add_source(account_id, data.model_dump())
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise HTTPException(409, "هذا المصدر مضاف بالفعل") from exc
            raise
        db.add_event("source_added", f"أُضيف المصدر {source['handle']}", account_id)
        return source

    @app.patch("/api/sources/{source_id}")
    def update_source(source_id: str, data: SourcePatch) -> dict[str, Any]:
        if not db.get_source(source_id):
            raise HTTPException(404, "المصدر غير موجود")
        source = db.update_source(source_id, data.model_dump(exclude_unset=True))
        return source

    @app.delete("/api/sources/{source_id}")
    def delete_source(source_id: str) -> dict[str, bool]:
        if not db.delete_source(source_id):
            raise HTTPException(404, "المصدر غير موجود")
        return {"ok": True}

    @app.get("/api/posts")
    def posts(account_id: str | None = None, status: str | None = None,
              limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)) -> list[dict[str, Any]]:
        return db.list_posts(account_id, status, limit, offset)

    @app.get("/api/posts/{post_id}")
    def get_post(post_id: str) -> dict[str, Any]:
        return post_or_404(post_id)

    @app.post("/api/posts/{post_id}/review")
    async def review(post_id: str, data: ReviewInput) -> dict[str, Any]:
        post_or_404(post_id)
        try:
            return await pipeline.review_post(post_id, data.action, data.comment, data.processed_text)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/posts/{post_id}/reprocess", status_code=202)
    def reprocess(post_id: str) -> dict[str, Any]:
        post = post_or_404(post_id)
        if post["status"] in {"publishing", "published", "publish_unknown"}:
            raise HTTPException(409, "لا يمكن إعادة المعالجة في هذه الحالة")
        db.update_post(post_id, {"status": "new", "error": None})
        job = db.enqueue("process", post["account_id"], post_id)
        return {"queued": True, "job_id": job}

    @app.post("/api/posts/{post_id}/confirm")
    def confirm_publish(post_id: str, data: ConfirmInput) -> dict[str, Any]:
        post = post_or_404(post_id)
        if post["status"] != "publish_unknown":
            raise HTTPException(409, "هذا الإجراء مخصص لنتائج النشر غير المؤكدة")
        db.update_post(post_id, {"status": data.status, "user_comment": data.note})
        db.add_event("publish_confirmed", data.note or f"أكد المستخدم الحالة: {data.status}", post["account_id"], "warning")
        return post_or_404(post_id)

    @app.get("/api/posts/{post_id}/media/{index}/{kind}")
    def post_media(post_id: str, index: int, kind: str) -> FileResponse:
        post = post_or_404(post_id)
        if kind not in {"original", "processed"} or index < 0 or index >= len(post.get("media", [])):
            raise HTTPException(404, "الوسائط غير موجودة")
        media = post["media"][index]
        relative = media.get("processed_path" if kind == "processed" else "local_path")
        if not relative:
            raise HTTPException(404, "الملف غير موجود")
        path = (settings.data_dir / relative).resolve()
        try:
            path.relative_to(settings.data_dir.resolve())
        except ValueError as exc:
            raise HTTPException(403, "مسار غير مسموح") from exc
        if not path.is_file():
            raise HTTPException(404, "الملف غير موجود")
        return FileResponse(path)

    @app.get("/api/ai/config")
    def ai_config() -> dict[str, Any]:
        return ai.public_config()

    @app.patch("/api/ai/config")
    def update_ai_config(data: AIConfigPatch) -> dict[str, Any]:
        current = ai.public_config()
        updates = data.model_dump(exclude_unset=True)
        base_url = updates.get("base_url", current["base_url"])
        if urlsplit(base_url).scheme not in {"http", "https"}:
            raise HTTPException(422, "عنوان المزود غير صالح")
        db.set_setting("ai.config", {
            "base_url": str(base_url).rstrip("/"), "model": updates.get("model", current["model"]),
            "timeout_seconds": updates.get("timeout_seconds", current["timeout_seconds"]),
        })
        return ai.public_config()

    @app.get("/api/ai/models")
    async def ai_models() -> dict[str, Any]:
        try:
            return {"models": await ai.list_models()}
        except AIError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/ai/test")
    async def test_ai(data: TestAIInput | None = None) -> dict[str, Any]:
        try:
            return await ai.test_connection(data.model if data else None)
        except AIError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/chat")
    def chat(account_id: str | None = None) -> list[dict[str, Any]]:
        return db.list_chat(account_id)

    @app.post("/api/chat", status_code=201)
    def add_chat(data: ChatInput) -> dict[str, Any]:
        if data.account_id:
            account_or_404(data.account_id)
        db.add_chat(data.account_id, "user", data.message)
        instruction_id = db.add_instruction(data.account_id, data.message)
        response = "حُفظت التعليمة وستدخل في سياق الفلترة القادمة. راجع أول النتائج قبل تشغيل النشر التلقائي."
        db.add_chat(data.account_id, "assistant", response)
        db.add_event("instruction_added", data.message[:500], data.account_id)
        return {"id": instruction_id, "reply": response}

    @app.post("/api/accounts/{account_id}/profile/rebuild")
    async def rebuild_profile(account_id: str) -> dict[str, Any]:
        account_or_404(account_id)
        try:
            return await pipeline.rebuild_profile(account_id)
        except (AIError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/events")
    def events(account_id: str | None = None, limit: int = Query(100, ge=1, le=300)) -> list[dict[str, Any]]:
        return db.list_events(account_id, limit)

    @app.get("/api/proxies")
    def proxies() -> dict[str, Any]:
        path = PROJECT_ROOT / "proxies.txt"
        values = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    values.append(line)
        assigned = {a.get("proxy_url"): a["name"] for a in db.list_accounts() if a.get("proxy_url")}
        return {"count": len(values), "proxies": [{"masked": mask_proxy(value), "assigned_to": assigned.get(value)}
                                                    for value in values]}

    @app.post("/api/accounts/{account_id}/proxy/auto")
    def assign_proxy(account_id: str) -> dict[str, Any]:
        account_or_404(account_id)
        path = PROJECT_ROOT / "proxies.txt"
        values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.lstrip().startswith("#")] if path.exists() else []
        used = {a.get("proxy_url") for a in db.list_accounts() if a["id"] != account_id}
        available = next((value for value in values if value not in used), None)
        if not available:
            raise HTTPException(409, "لا يوجد بروكسي غير مستخدم في proxies.txt")
        try:
            playwright_proxy(available)
        except BrowserError as exc:
            raise HTTPException(422, str(exc)) from exc
        db.update_account(account_id, {"proxy_url": available})
        db.add_event("proxy_assigned", "عُيّن بروكسي ثابت للحساب", account_id)
        return account_details(db.get_account(account_id))

    @app.post("/api/maintenance/backup")
    def backup() -> dict[str, Any]:
        path = create_backup(settings, db)
        return {"ok": True, "file": path.name, "download_url": f"/api/backups/{path.name}"}

    @app.get("/api/backups/{name}")
    def download_backup(name: str) -> FileResponse:
        if not re.fullmatch(r"mirsal-\d{8}-\d{6}\.tar\.gz", name):
            raise HTTPException(404, "النسخة غير موجودة")
        path = settings.data_dir / "backups" / name
        if not path.exists():
            raise HTTPException(404, "النسخة غير موجودة")
        return FileResponse(path, filename=name, media_type="application/gzip")

    @app.post("/api/maintenance/cleanup")
    def cleanup() -> dict[str, Any]:
        return {"database": db.cleanup(settings.log_retention_days),
                "files": cleanup_files(settings, settings.media_retention_days)}

    dist = PROJECT_ROOT / "dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Any:
        if full_path.startswith("api/") or full_path == "api":
            return JSONResponse({"detail": "المسار غير موجود"}, status_code=404)
        index = dist / "index.html"
        if not index.exists():
            return JSONResponse({"detail": "الواجهة غير مبنية؛ نفّذ npm run build"}, status_code=503)
        return FileResponse(index)

    return app
