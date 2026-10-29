from __future__ import annotations

import asyncio
import random
import re
from datetime import UTC, datetime
from typing import Any

from .ai import AIError, AIProvider
from .browser import BrowserError, PublishUnknown, WorkflowPublisher, validate_session
from .config import Settings
from .connectors import ConnectorError, MediaDownloader, ReaderFactory
from .db import Database
from .media import MediaError, MediaProcessor

PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+|00)?[0-9٠-٩][0-9٠-٩\s().\-]{6,}[0-9٠-٩]")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def replace_phone_numbers(text: str, replacement: str) -> str:
    if not replacement.strip():
        return text

    def replace(match: re.Match[str]) -> str:
        original = match.group(0)
        digits = re.sub(r"\D", "", original.translate(ARABIC_DIGITS))
        if 7 <= len(digits) <= 15:
            prefix = "+" if original.lstrip().startswith("+") and not replacement.startswith("+") else ""
            return prefix + replacement
        return original

    return PHONE_PATTERN.sub(replace, text)


class AutomationPipeline:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.ai = AIProvider(settings, db)
        self.readers = ReaderFactory(settings)
        self.downloader = MediaDownloader(settings)
        self.media = MediaProcessor(settings)
        self.publisher = WorkflowPublisher(settings)

    async def monitor_account(self, account_id: str) -> dict[str, int]:
        account = self._account(account_id)
        sources = self.db.list_sources(account_id, enabled_only=True)
        if not sources:
            self.db.update_account(account_id, {"last_monitor_at": datetime.now(UTC).isoformat(timespec="seconds")})
            self.db.add_event("monitor_empty", "لا توجد مصادر نشطة لهذا الحساب", account_id, "warning")
            return {"sources": 0, "discovered": 0, "new": 0, "failed": 0}
        discovered = new = failed = 0
        errors = []
        for source in sources:
            try:
                reader = self.readers.for_source(account, source)
                posts = await reader.read(account, source)
                discovered += len(posts)
                for post in posts:
                    post_id = self.db.insert_discovered_post(account_id, source["id"], post)
                    if post_id:
                        new += 1
                        self.db.enqueue("process", account_id, post_id)
                self.db.update_source(source["id"], {
                    "last_sync_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "last_seen_id": posts[0]["external_id"] if posts else source.get("last_seen_id"),
                    "last_error": None,
                })
            except Exception as exc:  # noqa: BLE001 - عزل فشل كل مصدر وتسجيله ثم متابعة البقية.
                failed += 1
                message = str(exc)[:1000]
                errors.append(message)
                self.db.update_source(source["id"], {"last_error": message})
                self.db.add_event("source_error", message, account_id, "error", {"source": source["handle"]})
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self.db.update_account(account_id, {"last_monitor_at": now, "last_run_at": now,
                                            "last_error": " | ".join(errors)[:1500] if errors else None})
        self.db.add_event("monitor_complete", f"فُحص {len(sources)} مصادر: {new} جديد من {discovered}", account_id,
                          "warning" if failed else "info", {"new": new, "discovered": discovered, "failed_sources": failed})
        return {"sources": len(sources), "discovered": discovered, "new": new, "failed": failed}

    async def process_post(self, post_id: str) -> None:
        post = self._post(post_id)
        account = self._account(post["account_id"])
        source = self.db.get_source(post["source_id"]) if post.get("source_id") else None
        self.db.update_post(post_id, {"status": "filtering", "error": None})
        try:
            media = await self.downloader.download_all(account, post)
            self.db.update_post(post_id, {"media": media})
            post["media"] = media
        except (ConnectorError, MediaError) as exc:
            self.db.update_post(post_id, {"status": "failed", "error": str(exc)})
            raise
        ocr_text = ""
        image = next((m for m in media if m.get("kind") == "image" and m.get("local_path")), None)
        if image and account.get("settings", {}).get("ocr_images", True):
            try:
                ocr_text = await self.media.ocr_image(self.settings.data_dir / image["local_path"])
            except MediaError as exc:
                self.db.add_event("ocr_warning", str(exc), account["id"], "warning", {"post_id": post_id})
        try:
            result = await self.ai.classify_post(account, source, post, ocr_text)
        except AIError as exc:
            self.db.update_post(post_id, {
                "status": "pending_review", "ai_decision": "review",
                "ai_reason": f"تعذّر الذكاء الاصطناعي؛ يلزم قرار بشري: {exc}",
                "ai_confidence": 0, "error": str(exc),
            })
            self.db.add_event("ai_unavailable", f"منشور {post_id} ينتظر مراجعة بشرية: {exc}", account["id"], "warning")
            return
        template_mode = account.get("settings", {}).get("template", {}).get("mode", "rebuild")
        base_text = ocr_text if ocr_text and template_mode == "rebuild" else post.get("raw_text", "")
        processed = (result.cleaned_text or base_text or post.get("raw_text", "")).strip()
        if result.replace_phone or result.category == "student_help":
            processed = replace_phone_numbers(processed, account.get("phone_replacement", ""))
        if account.get("settings", {}).get("replace_username", True) and account.get("username"):
            old_handle = source.get("handle") if source else post.get("author", "")
            if old_handle:
                processed = re.sub(rf"@{re.escape(old_handle)}\b", "@" + account["username"].lstrip("@"), processed, flags=re.IGNORECASE)
        updates = {
            "processed_text": processed, "ai_decision": result.decision, "ai_reason": result.reason,
            "ai_confidence": result.confidence, "category": result.category, "important": result.important,
            "error": None,
        }
        if result.decision == "ignore":
            self.db.update_post(post_id, {**updates, "status": "ignored"})
            self.db.add_feedback(account["id"], post_id, "ignore", result.reason, result.category)
            self.db.add_event("post_ignored", result.reason, account["id"], metadata={"post_id": post_id})
            return
        try:
            media = await self._process_media(account, post, processed)
        except MediaError as exc:
            self.db.update_post(post_id, {**updates, "status": "failed", "error": str(exc)})
            raise
        updates["media"] = media
        threshold = float(account.get("settings", {}).get("auto_confidence", 0.88))
        automatic = (account.get("auto_publish") and not account.get("review_required")
                     and result.decision == "publish" and result.confidence >= threshold)
        if result.decision == "publish" and automatic:
            self.db.update_post(post_id, {**updates, "status": "queued"})
            self.db.enqueue("publish", account["id"], post_id, max_attempts=1)
            self.db.add_event("post_queued", f"اجتاز الفلترة بثقة {result.confidence:.0%} ودخل طابور النشر", account["id"],
                              metadata={"post_id": post_id})
        else:
            self.db.update_post(post_id, {**updates, "status": "pending_review"})
            self.db.add_event("review_needed", result.reason, account["id"], metadata={"post_id": post_id})
        if result.important:
            self.db.add_event("important_post", result.reason, account["id"], "warning", {"post_id": post_id})
            self._queue_notification(account, f"منشور مهم في {account['name']}: {result.reason}\n{post.get('url', '')}")

    async def _process_media(self, account: dict[str, Any], post: dict[str, Any], text: str) -> list[dict[str, Any]]:
        output_dir = self.settings.data_dir / "accounts" / account["id"] / "media" / post["id"] / "processed"
        output_dir.mkdir(parents=True, exist_ok=True)
        result = []
        for index, media in enumerate(post.get("media", [])):
            item = dict(media)
            if not item.get("local_path"):
                result.append(item)
                continue
            source = self.settings.data_dir / item["local_path"]
            if item.get("kind") == "video":
                output = output_dir / f"video-{index}.mp4"
                await self.media.process_video(source, account, output)
            else:
                output = output_dir / f"image-{index}.png"
                await self.media.process_image(source, account, output, text=text, source_handle=post.get("author", ""))
            item["processed_path"] = str(output.relative_to(self.settings.data_dir))
            result.append(item)
        return result

    async def review_post(self, post_id: str, action: str, comment: str = "",
                          processed_text: str | None = None) -> dict[str, Any]:
        post = self._post(post_id)
        account = self._account(post["account_id"])
        if post["status"] in {"published", "publishing", "publish_unknown"}:
            raise ValueError("لا يمكن تغيير مراجعة منشور في هذه الحالة")
        if processed_text is not None:
            post["processed_text"] = processed_text.strip()
        if action == "reject":
            if not comment.strip():
                raise ValueError("سبب الرفض مطلوب ليتعلم النظام من القرار")
            self.db.update_post(post_id, {"status": "rejected", "user_comment": comment.strip(),
                                          "processed_text": post["processed_text"]})
            self.db.add_feedback(account["id"], post_id, "reject", comment, post.get("category"))
            self.db.add_event("post_rejected", comment, account["id"], metadata={"post_id": post_id})
        else:
            if not any(m.get("processed_path") for m in post.get("media", [])) and post.get("media"):
                text = post.get("processed_text") or post.get("raw_text", "")
                media = await self._process_media(account, post, text)
                self.db.update_post(post_id, {"media": media})
            self.db.update_post(post_id, {"status": "queued", "user_comment": comment.strip(),
                                          "processed_text": post["processed_text"], "error": None})
            if comment.strip():
                self.db.add_feedback(account["id"], post_id, "approve", comment, post.get("category"))
            self.db.enqueue("publish", account["id"], post_id, max_attempts=1)
            self.db.add_event("post_approved", "اعتمد المستخدم المنشور", account["id"], metadata={"post_id": post_id})
        return self._post(post_id)

    async def publish_post(self, post_id: str) -> None:
        post = self._post(post_id)
        account = self._account(post["account_id"])
        if post["status"] == "published":
            return
        if self.settings.dry_run or not self.settings.publishing_enabled:
            self.db.update_post(post_id, {"status": "ready", "error": None})
            self.db.add_event("dry_run_ready", "تم تجهيز المنشور دون إرساله للمنصة (وضع الاختبار)", account["id"],
                              metadata={"post_id": post_id})
            return
        delay = random.uniform(account["min_delay_sec"], account["max_delay_sec"])
        if delay:
            await asyncio.sleep(delay)
        self.db.update_post(post_id, {"status": "publishing", "error": None})
        try:
            result = await self.publisher.publish(account, post)
            self.db.update_post(post_id, {"status": "published", "published_at_target": datetime.now(UTC).isoformat(timespec="seconds"),
                                          "raw": {**post.get("raw", {}), "target_result": result}})
            self.db.add_event("post_published", "تأكد نجاح النشر على المنصة", account["id"], metadata={"post_id": post_id})
        except PublishUnknown as exc:
            self.db.update_post(post_id, {"status": "publish_unknown", "error": str(exc)})
            self.db.add_event("publish_unknown", str(exc), account["id"], "warning", {"post_id": post_id})
        except BrowserError as exc:
            self.db.update_post(post_id, {"status": "failed", "error": str(exc)})
            self.db.add_event("publish_failed", str(exc), account["id"], "error", {"post_id": post_id})

    async def check_session(self, account_id: str) -> dict[str, str]:
        account = self._account(account_id)
        result = await validate_session(self.settings, account)
        self.db.update_account(account_id, {"session_status": result["status"], "last_error": result["detail"] if result["status"] in {"error", "expired"} else None})
        self.db.add_event("session_check", result["detail"], account_id,
                          "info" if result["status"] == "valid" else "warning")
        return result

    async def rebuild_profile(self, account_id: str) -> dict[str, Any]:
        account = self._account(account_id)
        posts = self.db.list_posts(account_id, limit=25)
        profile = await self.ai.rebuild_profile(account, posts)
        path = self.settings.data_dir / "accounts" / account_id / "profile.json"
        import json
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        self.db.add_event("profile_rebuilt", "حُدّث ملف اللهجة والموضوعات من السجل", account_id)
        return profile

    async def notify(self, account_id: str, text: str) -> None:
        account = self._account(account_id)
        if self.settings.dry_run or not self.settings.publishing_enabled:
            self.db.add_event("notification_dry_run", text, account_id)
            return
        pseudo = {"processed_text": text, "raw_text": text, "media": []}
        try:
            await self.publisher.publish(account, pseudo)
            self.db.add_event("notification_sent", "أُرسل تنبيه تيليجرام", account_id)
        except BrowserError as exc:
            self.db.add_event("notification_unknown", str(exc), account_id, "warning")

    def _queue_notification(self, account: dict[str, Any], text: str) -> None:
        target = account.get("settings", {}).get("notifications", {}).get("telegram_account_id")
        if target:
            self.db.enqueue("notify", target, payload={"text": text}, max_attempts=1)

    def _account(self, account_id: str) -> dict[str, Any]:
        account = self.db.get_account(account_id)
        if not account:
            raise ValueError("الحساب غير موجود")
        return account

    def _post(self, post_id: str) -> dict[str, Any]:
        post = self.db.get_post(post_id)
        if not post:
            raise ValueError("المنشور غير موجود")
        return post
