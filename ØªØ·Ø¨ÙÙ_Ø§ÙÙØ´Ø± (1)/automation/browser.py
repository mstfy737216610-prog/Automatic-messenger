from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from urllib.parse import unquote, urlsplit

import yaml

from .config import PROJECT_ROOT, Settings


class BrowserError(RuntimeError):
    pass


class PublishUnknown(BrowserError):
    """قد تكون العملية وصلت للمنصة؛ لا يجوز تكرارها تلقائيًا."""


def workflows() -> dict[str, Any]:
    path = PROJECT_ROOT / "config/selectors.yaml"
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def account_dir(settings: Settings, account_id: str) -> Path:
    path = settings.data_dir / "accounts" / account_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_path(settings: Settings, account: dict[str, Any]) -> Path:
    return account_dir(settings, account["id"]) / f"session-{account['platform']}.json"


def playwright_proxy(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    raw = value if "://" in value else f"http://{value}"
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https", "socks5"} or not parts.hostname:
        raise BrowserError("صيغة البروكسي غير صالحة؛ استخدم http:// أو socks5://")
    result = {"server": f"{parts.scheme}://{parts.hostname}{f':{parts.port}' if parts.port else ''}"}
    if parts.username:
        result["username"] = unquote(parts.username)
    if parts.password:
        result["password"] = unquote(parts.password)
    return result


class BrowserRuntime:
    def __init__(self, settings: Settings, account: dict[str, Any], headless: bool | None = None):
        self.settings = settings
        self.account = account
        self.headless = settings.playwright_headless if headless is None else headless
        self.playwright: Any = None
        self.browser: Any = None
        self.context: Any = None

    async def __aenter__(self) -> Self:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserError("Playwright غير مثبت") from exc
        self.playwright = await async_playwright().start()
        launch: dict[str, Any] = {
            "headless": self.headless,
            "args": ["--disable-dev-shm-usage", "--disable-gpu"],
            "proxy": playwright_proxy(self.account.get("proxy_url")),
        }
        if self.settings.chromium_no_sandbox:
            launch["args"].extend(["--no-sandbox", "--disable-setuid-sandbox"])
        if self.settings.chromium_executable:
            launch["executable_path"] = self.settings.chromium_executable
        try:
            self.browser = await self.playwright.chromium.launch(**launch)
        except Exception as exc:
            await self.playwright.stop()
            raise BrowserError(f"تعذّر تشغيل Chromium: {str(exc)[:700]}") from exc
        state = session_path(self.settings, self.account)
        context_options: dict[str, Any] = {
            "locale": "ar",
            "viewport": {"width": 1280, "height": 800},
            "ignore_https_errors": False,
        }
        if state.exists():
            context_options["storage_state"] = str(state)
        self.context = await self.browser.new_context(**context_options)
        self.context.set_default_timeout(30000)
        self.context.set_default_navigation_timeout(45000)
        return self

    async def save_state(self) -> None:
        if not self.context:
            return
        path = session_path(self.settings, self.account)
        await self.context.storage_state(path=str(path))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    async def __aexit__(self, exc_type: type[BaseException] | None,
                        exc: BaseException | None, traceback: TracebackType | None) -> None:
        try:
            await self.save_state()
        finally:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()


def import_storage_state(settings: Settings, account: dict[str, Any], payload: dict[str, Any] | list[Any]) -> Path:
    if isinstance(payload, list):
        payload = {"cookies": payload, "origins": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("cookies"), list):
        raise BrowserError("الملف يجب أن يكون Playwright storage state أو قائمة Cookies")
    cookies = []
    for cookie in payload["cookies"][:1000]:
        if not isinstance(cookie, dict) or not cookie.get("name") or not cookie.get("domain"):
            continue
        item = {
            "name": str(cookie["name"]), "value": str(cookie.get("value", "")),
            "domain": str(cookie["domain"]), "path": str(cookie.get("path", "/")),
            "expires": float(cookie.get("expires", -1)), "httpOnly": bool(cookie.get("httpOnly", False)),
            "secure": bool(cookie.get("secure", True)),
            "sameSite": cookie.get("sameSite") if cookie.get("sameSite") in {"Strict", "Lax", "None"} else "Lax",
        }
        cookies.append(item)
    if not cookies:
        raise BrowserError("لم يُعثر على Cookies صالحة في الملف")
    state = {"cookies": cookies, "origins": payload.get("origins", []) if isinstance(payload.get("origins", []), list) else []}
    path = session_path(settings, account)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def cookie_header(settings: Settings, account: dict[str, Any]) -> str:
    path = session_path(settings, account)
    if not path.exists():
        raise BrowserError("لا توجد جلسة محفوظة؛ استورد Cookies أولًا")
    state = json.loads(path.read_text(encoding="utf-8"))
    pairs = [f"{c['name']}={c['value']}" for c in state.get("cookies", []) if c.get("name")]
    if not pairs:
        raise BrowserError("الجلسة لا تحتوي Cookies")
    return "; ".join(pairs)


def netscape_cookies(settings: Settings, account: dict[str, Any]) -> Path:
    path = session_path(settings, account)
    if not path.exists():
        raise BrowserError("لا توجد جلسة محفوظة لتنزيل الوسائط")
    state = json.loads(path.read_text(encoding="utf-8"))
    target = account_dir(settings, account["id"]) / f"cookies-{account['platform']}.txt"
    lines = ["# Netscape HTTP Cookie File", "# ملف مؤقت مولّد من الجلسة؛ لا تشاركه."]
    for cookie in state.get("cookies", []):
        domain = str(cookie.get("domain", "")).replace("\n", "")
        if not domain:
            continue
        prefix = "#HttpOnly_" if cookie.get("httpOnly") else ""
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires = int(float(cookie.get("expires", -1)))
        if expires <= 0:
            expires = int(time.time()) + 86400
        value = str(cookie.get("value", "")).replace("\t", "").replace("\n", "")
        name = str(cookie.get("name", "")).replace("\t", "").replace("\n", "")
        lines.append("\t".join([prefix + domain, include_subdomains, str(cookie.get("path", "/")),
                                secure, str(expires), name, value]))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


async def validate_session(settings: Settings, account: dict[str, Any]) -> dict[str, str]:
    if not session_path(settings, account).exists():
        return {"status": "missing", "detail": "لا توجد جلسة محفوظة"}
    config = workflows()["platforms"][account["platform"]]
    try:
        async with BrowserRuntime(settings, account) as runtime:
            page = await runtime.context.new_page()
            await page.goto(config["session_url"], wait_until="domcontentloaded")
            if config.get("login_required") and await page.locator(config["login_required"]).count():
                return {"status": "expired", "detail": "المنصة طلبت تسجيل الدخول"}
            if config.get("session_valid") and await page.locator(config["session_valid"]).count():
                return {"status": "valid", "detail": "ظهر مؤشر الجلسة النشطة"}
            return {"status": "unknown", "detail": "فُتحت الصفحة لكن مؤشر الجلسة لم يظهر؛ راجع SELECTORS.md"}
    except BrowserError as exc:
        return {"status": "error", "detail": str(exc)}


class WorkflowPublisher:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def publish(self, account: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
        config = workflows()["platforms"][account["platform"]]["publish"]
        media = [m.get("processed_path") or m.get("local_path") for m in post.get("media", [])]
        media = [str(self.settings.data_dir / m) for m in media if m]
        target_url = account.get("settings", {}).get("telegram_target_url", "")
        values = {"text": post.get("processed_text") or post.get("raw_text") or "", "target_url": target_url}
        if account["platform"] == "telegram" and not target_url:
            raise BrowserError("أضف رابط محادثة تيليجرام في إعدادات الحساب")
        if account["platform"] in {"instagram", "tiktok"} and not media:
            raise BrowserError("هذه المنصة تحتاج ملف وسائط قبل النشر")
        try:
            async with BrowserRuntime(self.settings, account) as runtime:
                page = await runtime.context.new_page()
                for step in config.get("steps", []):
                    if step.get("if_media") and not media:
                        continue
                    await self._run_step(page, step, values, media)
                success = config.get("success")
                if not success:
                    raise PublishUnknown("أُرسلت خطوات النشر لكن لا يوجد مؤشر نجاح موثوق؛ تحقق يدويًا قبل إعادة المحاولة")
                try:
                    await page.locator(success).first.wait_for(state="visible", timeout=20000)
                except Exception as exc:
                    raise PublishUnknown("لم يظهر مؤشر نجاح النشر؛ تحقق يدويًا قبل إعادة المحاولة") from exc
                return {"status": "published", "url": page.url}
        except PublishUnknown:
            raise
        except Exception as exc:
            # بعد بدء مسار النشر لا يمكن الجزم بأن المنصة لم تستلم العملية.
            raise PublishUnknown(f"توقف مسار النشر ونتيجته غير مؤكدة: {str(exc)[:700]}") from exc

    async def _run_step(self, page: Any, step: dict[str, Any], values: dict[str, str], media: list[str]) -> None:
        action = step.get("action")
        value = str(step.get("value", "")).format_map(values)
        selector = step.get("selector", "")
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                if action == "goto":
                    await page.goto(value, wait_until="domcontentloaded")
                elif action == "wait_for":
                    await page.locator(selector).first.wait_for(state="visible")
                elif action == "click":
                    await page.locator(selector).first.click()
                elif action == "fill":
                    locator = page.locator(selector).first
                    await locator.wait_for(state="visible")
                    await locator.fill(value)
                elif action == "upload":
                    locator = page.locator(selector).first
                    await locator.wait_for(state="attached")
                    await locator.set_input_files(media)
                elif action == "press":
                    await page.locator(selector).first.press(value)
                elif action == "wait":
                    await asyncio.sleep(min(30, float(step.get("seconds", 1))))
                else:
                    raise BrowserError(f"إجراء غير معروف في selectors.yaml: {action}")
                return
            except Exception as exc:  # noqa: BLE001 - أخطاء Playwright تُوحّد في BrowserError بعد المحاولة الثانية.
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(0.8)
        if step.get("optional"):
            return
        raise BrowserError(f"فشل إجراء {action}: {str(last_error)[:500]}")
