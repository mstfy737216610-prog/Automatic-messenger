from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import Settings
from .db import Database
from .pipeline import AutomationPipeline

log = logging.getLogger(__name__)


class AutomationWorker:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.pipeline = AutomationPipeline(settings, db)
        self.stop_event = asyncio.Event()
        self.tasks: list[asyncio.Task[Any]] = []

    def start(self) -> None:
        if self.tasks:
            return
        self.stop_event.clear()
        self.tasks = [asyncio.create_task(self.worker_loop(), name="mirsal-worker")]
        if self.settings.scheduler_enabled:
            self.tasks.append(asyncio.create_task(self.scheduler_loop(), name="mirsal-scheduler"))

    async def stop(self) -> None:
        self.stop_event.set()
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    async def worker_loop(self) -> None:
        self.db.recover_stale_jobs()
        while not self.stop_event.is_set():
            job = self.db.claim_job()
            if not job:
                await asyncio.sleep(self.settings.worker_poll_seconds)
                continue
            try:
                await self.run_job(job)
                self.db.complete_job(job["id"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("Job %s failed", job["id"])
                self.db.fail_job(job, f"{type(exc).__name__}: {exc}", retry=job["kind"] not in {"publish", "notify"})
                if job.get("post_id") and job["kind"] == "process":
                    self.db.update_post(job["post_id"], {"status": "failed", "error": str(exc)[:1500]})
                self.db.add_event("job_error", f"{job['kind']}: {str(exc)[:900]}", job.get("account_id"), "error")

    async def scheduler_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                now = datetime.now(UTC)
                for account in self.db.list_accounts(enabled_only=True):
                    last = self._parse(account.get("last_monitor_at"))
                    due = last is None or now - last >= timedelta(seconds=account["monitor_interval_sec"])
                    if due:
                        self.db.enqueue("monitor", account["id"], max_attempts=2)
                if self.settings.auto_cleanup:
                    last_cleanup = self._parse(self.db.get_setting("maintenance.last_cleanup"))
                    if last_cleanup is None or now - last_cleanup >= timedelta(hours=24):
                        self.db.enqueue("cleanup", max_attempts=1)
                        self.db.set_setting("maintenance.last_cleanup", now.isoformat(timespec="seconds"))
            except Exception:
                log.exception("Scheduler tick failed")
            await asyncio.sleep(max(2.0, self.settings.scheduler_poll_seconds))

    async def run_job(self, job: dict[str, Any]) -> Any:
        kind = job["kind"]
        if kind == "monitor":
            return await self.pipeline.monitor_account(job["account_id"])
        if kind == "process":
            return await self.pipeline.process_post(job["post_id"])
        if kind == "publish":
            return await self.pipeline.publish_post(job["post_id"])
        if kind == "notify":
            return await self.pipeline.notify(job["account_id"], job.get("payload", {}).get("text", ""))
        if kind == "cleanup":
            from .maintenance import cleanup_files
            result = {"database": self.db.cleanup(self.settings.log_retention_days),
                      "files": cleanup_files(self.settings, self.settings.media_retention_days)}
            self.db.add_event("cleanup_complete", f"نُظفت السجلات والوسائط القديمة: {result}")
            return result
        raise ValueError(f"نوع مهمة غير معروف: {kind}")

    @staticmethod
    def _parse(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            return None
