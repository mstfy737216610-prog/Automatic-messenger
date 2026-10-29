from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from .browser import (
    BrowserError,
    BrowserRuntime,
    cookie_header,
    netscape_cookies,
    session_path,
    workflows,
)
from .config import Settings
from .models import DiscoveredPost, MediaItem

log = logging.getLogger(__name__)


class ConnectorError(RuntimeError):
    pass


def _post_id(url: str, text: str = "") -> str:
    patterns = [r"/status/(\d+)", r"/video/(\d+)", r"/(?:p|reel)/([A-Za-z0-9_-]+)"]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return hashlib.sha256(f"{url}|{text[:300]}".encode()).hexdigest()[:24]


def _serialize(post: DiscoveredPost) -> dict[str, Any]:
    value = asdict(post)
    value["published_at"] = post.published_at.isoformat() if post.published_at else None
    return value


class TwscrapeReader:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def read(self, account: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            os.environ.setdefault("TWS_TELEMETRY", "0")
            from twscrape import API, gather
        except ImportError as exc:
            raise ConnectorError("twscrape غير مثبت") from exc
        database = self.settings.data_dir / "accounts" / account["id"] / "x-twscrape.db"
        try:
            api = API(str(database), proxy=account.get("proxy_url") or None,
                      raise_when_no_account=True, wait_timeout=5)
            await api.pool.add_account_cookies("destination", cookie_header(self.settings, account))
            user = await api.user_by_login(source["handle"])
            if not user:
                raise ConnectorError(f"لم يُعثر على حساب المصدر: {source['handle']}")
            limit = int(source.get("config", {}).get("limit", 20))
            tweets = await gather(api.user_tweets(user.id, limit=max(1, min(limit, 50))))
        except Exception as exc:
            raise ConnectorError(f"فشل سحب X: {str(exc)[:700]}") from exc
        results = []
        for tweet in tweets:
            raw = tweet.dict()
            media = self._media(raw.get("media"), str(tweet.url))
            results.append(_serialize(DiscoveredPost(
                external_id=str(tweet.id), url=str(tweet.url), author=str(tweet.user.username),
                text=str(tweet.rawContent or ""), published_at=tweet.date,
                media=media, raw=raw,
            )))
        return results

    @staticmethod
    def _media(raw_media: Any, post_url: str) -> list[MediaItem]:
        items: list[MediaItem] = []
        if not raw_media:
            return items
        candidates = raw_media if isinstance(raw_media, list) else []
        if isinstance(raw_media, dict):
            for key in ("photos", "videos", "animated_gifs"):
                value = raw_media.get(key, [])
                if isinstance(value, list):
                    candidates.extend(value)
        for media in candidates[:8]:
            if not isinstance(media, dict):
                continue
            kind = "video" if media.get("type") in {"video", "animated_gif"} or media.get("video_info") else "image"
            url = media.get("media_url_https") or media.get("url")
            if kind == "video":
                variants = media.get("video_info", {}).get("variants", [])
                mp4s = [v for v in variants if isinstance(v, dict) and str(v.get("url", "")).endswith(".mp4")]
                if mp4s:
                    url = max(mp4s, key=lambda v: int(v.get("bitrate", 0) or 0)).get("url")
                if not url:
                    url = post_url
            if url:
                items.append(MediaItem(kind=kind, url=str(url)))
        return items


class BrowserReader:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def read(self, account: dict[str, Any], source: dict[str, Any]) -> list[dict[str, Any]]:
        platform_config = workflows()["platforms"][source["platform"]]
        selectors = dict(platform_config.get("source", {}))
        selectors.update(source.get("config", {}).get("selectors", {}))
        if not selectors.get("item"):
            raise ConnectorError("محددات المصدر غير موجودة")
        try:
            async with BrowserRuntime(self.settings, account) as runtime:
                page = await runtime.context.new_page()
                await page.goto(source["url"], wait_until="domcontentloaded")
                await page.locator(selectors["item"]).first.wait_for(state="attached", timeout=30000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.55)")
                await asyncio.sleep(1.2)
                return await self._extract(page, source, selectors)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"فشل المتصفح أثناء سحب {source['handle']}: {str(exc)[:700]}") from exc

    async def _extract(self, page: Any, source: dict[str, Any], selectors: dict[str, str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        limit = max(1, min(int(source.get("config", {}).get("limit", 20)), 50))
        items = page.locator(selectors["item"])
        count = min(await items.count(), limit)
        for index in range(count):
            item = items.nth(index)
            try:
                link_locator = item.locator(selectors.get("link", "a")).first
                url = await link_locator.get_attribute("href") if await link_locator.count() else source["url"]
                if not url:
                    continue
                url = await page.evaluate("(url) => new URL(url, location.href).href", url)
                text = ""
                if selectors.get("text") and await item.locator(selectors["text"]).count():
                    locator = item.locator(selectors["text"]).first
                    if source["platform"] == "tiktok" and await locator.evaluate("el => el.tagName === 'IMG'"):
                        text = await locator.get_attribute("alt") or ""
                    else:
                        text = (await locator.inner_text()).strip()
                media: list[MediaItem] = []
                if selectors.get("image"):
                    images = item.locator(selectors["image"])
                    for image_index in range(min(await images.count(), 4)):
                        src = await images.nth(image_index).get_attribute("src")
                        if src and src.startswith(("http://", "https://")):
                            media.append(MediaItem(kind="image", url=src))
                is_video = "/video/" in url or "/reel/" in url
                if selectors.get("video") and await item.locator(selectors["video"]).count():
                    is_video = True
                if is_video:
                    media.append(MediaItem(kind="video", url=url))
                if not text and not media:
                    continue
                results.append(_serialize(DiscoveredPost(
                    external_id=_post_id(url, text), url=url, author=source["handle"], text=text[:10000], media=media,
                )))
            except Exception as exc:  # noqa: BLE001 - عنصر DOM تالف لا يجب أن يسقط بقية المصدر.
                log.debug("تعذّر استخراج العنصر %s من %s: %s", index, source["handle"], exc)
        return results


class ReaderFactory:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.browser = BrowserReader(settings)
        self.x_reader = TwscrapeReader(settings)

    def for_source(self, account: dict[str, Any], source: dict[str, Any]) -> Any:
        engine = source.get("config", {}).get("reader", "auto")
        if source["platform"] == "x" and engine in {"auto", "twscrape"}:
            if session_path(self.settings, account).exists():
                return self.x_reader
            if engine == "twscrape":
                raise ConnectorError("اخترت twscrape لكن لا توجد جلسة X محفوظة")
        return self.browser


class MediaDownloader:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def download_all(self, account: dict[str, Any], post: dict[str, Any]) -> list[dict[str, Any]]:
        output_dir = self.settings.data_dir / "accounts" / account["id"] / "media" / post["id"] / "original"
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded = []
        for index, item in enumerate(post.get("media", [])[:6]):
            media = dict(item)
            if media.get("local_path") and (self.settings.data_dir / media["local_path"]).exists():
                downloaded.append(media)
                continue
            try:
                if media.get("kind") == "video":
                    path = await asyncio.to_thread(self._download_video, account, media["url"], output_dir, index)
                else:
                    path = await self._download_image(account, media["url"], output_dir / f"image-{index}.img")
                media["local_path"] = str(path.relative_to(self.settings.data_dir))
                downloaded.append(media)
            except Exception as exc:
                raise ConnectorError(f"فشل تنزيل وسائط المنشور {index + 1}: {str(exc)[:600]}") from exc
        return downloaded

    def _download_video(self, account: dict[str, Any], url: str, output_dir: Path, index: int) -> Path:
        try:
            import yt_dlp
        except ImportError as exc:
            raise ConnectorError("yt-dlp غير مثبت") from exc
        options: dict[str, Any] = {
            "outtmpl": str(output_dir / f"video-{index}-%(id)s.%(ext)s"),
            "noplaylist": True, "quiet": True, "no_warnings": True,
            "max_filesize": self.settings.max_download_mb * 1024 * 1024,
            "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
            "merge_output_format": "mp4", "overwrites": True,
            "retries": 2, "socket_timeout": 30,
        }
        if account.get("proxy_url"):
            options["proxy"] = account["proxy_url"]
        try:
            options["cookiefile"] = str(netscape_cookies(self.settings, account))
        except BrowserError:
            pass
        before = set(output_dir.glob(f"video-{index}-*"))
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([url])
        created = [p for p in set(output_dir.glob(f"video-{index}-*")) - before if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
        if not created:
            candidates = [p for p in output_dir.glob(f"video-{index}-*") if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
            created = candidates
        if not created:
            raise ConnectorError("اكتمل yt-dlp دون ملف فيديو صالح")
        return max(created, key=lambda p: p.stat().st_mtime)

    async def _download_image(self, account: dict[str, Any], url: str, target: Path) -> Path:
        if not url.startswith(("https://", "http://")):
            raise ConnectorError("رابط الصورة غير صالح")
        headers = {"User-Agent": "Mozilla/5.0", "Referer": url}
        try:
            headers["Cookie"] = cookie_header(self.settings, account)
        except BrowserError:
            pass
        maximum = self.settings.max_download_mb * 1024 * 1024
        timeout = httpx.Timeout(60, connect=15)
        async with (
            httpx.AsyncClient(timeout=timeout, follow_redirects=True, proxy=account.get("proxy_url") or None) as client,
            client.stream("GET", url, headers=headers) as response,
        ):
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";")[0]
            if content_type and not content_type.startswith(("image/", "application/octet-stream")):
                raise ConnectorError(f"المحتوى ليس صورة: {content_type}")
            size = 0
            with target.open("wb") as handle:
                async for chunk in response.aiter_bytes(1024 * 128):
                    size += len(chunk)
                    if size > maximum:
                        raise ConnectorError("حجم الصورة تجاوز الحد المسموح")
                    handle.write(chunk)
            if size == 0:
                raise ConnectorError("الصورة المنزلة فارغة")
        extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
        final = target.with_suffix(extensions.get(content_type, ".img"))
        target.replace(final)
        return final
