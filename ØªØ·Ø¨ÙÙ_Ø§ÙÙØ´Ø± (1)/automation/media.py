from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
    features,
)

from .config import PROJECT_ROOT, Settings


class MediaError(RuntimeError):
    pass


DEFAULT_TEMPLATE: dict[str, Any] = {
    "mode": "rebuild",
    "width": 1080,
    "height": 1350,
    "background": "#f4f6f2",
    "surface": "#fcfdf9",
    "text": "#18201c",
    "muted": "#53615a",
    "accent": "#008f6d",
    "font_size": 62,
    "margin": 84,
    "logo_opacity": 0.09,
    "watermark_opacity": 0.82,
    "redactions": [],
    "video_delogo": [],
    "video_color_tweak": False,
    "source_attribution": False,
}


def _hex(value: str, fallback: str) -> str:
    value = str(value or fallback)
    if len(value) == 7 and value.startswith("#"):
        try:
            int(value[1:], 16)
            return value
        except ValueError:
            pass
    return fallback


class MediaProcessor:
    def __init__(self, settings: Settings):
        self.settings = settings
        # Tajawal يغطي العربية واللاتينية والشرطة الطويلة؛ Noto Sans Arabic وحده لا يغطيها.
        self.font_regular = PROJECT_ROOT / "assets/fonts/Tajawal-Regular.ttf"
        self.font_bold = PROJECT_ROOT / "assets/fonts/Tajawal-Bold.ttf"
        self.default_logo = PROJECT_ROOT / "assets/default_logo.png"

    def template_config(self, account: dict[str, Any]) -> dict[str, Any]:
        config = dict(DEFAULT_TEMPLATE)
        config.update(account.get("settings", {}).get("template", {}))
        for key, fallback in (("background", "#f4f6f2"), ("surface", "#fcfdf9"),
                              ("text", "#18201c"), ("muted", "#53615a"), ("accent", "#008f6d")):
            config[key] = _hex(config.get(key, fallback), fallback)
        return config

    def _logo_path(self, account: dict[str, Any]) -> Path:
        relative = account.get("settings", {}).get("logo_path")
        if relative:
            candidate = (self.settings.data_dir / str(relative)).resolve()
            try:
                candidate.relative_to(self.settings.data_dir.resolve())
                if candidate.is_file():
                    return candidate
            except ValueError:
                pass
        return self.default_logo

    @staticmethod
    def _prepare_text(text: str) -> tuple[str, dict[str, Any]]:
        if features.check("raqm"):
            return text, {"direction": "rtl", "language": "ar"}
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            return get_display(arabic_reshaper.reshape(text)), {}
        except ImportError:
            return text, {}

    def _font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        path = self.font_bold if bold else self.font_regular
        if not path.exists():
            raise MediaError(f"الخط غير موجود: {path}")
        return ImageFont.truetype(str(path), size=size, layout_engine=ImageFont.Layout.RAQM if features.check("raqm") else None)

    def _wrap(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
              max_width: int, direction: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        for paragraph in (text or "").splitlines() or [""]:
            words = paragraph.split()
            if not words:
                lines.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                try:
                    width = draw.textlength(candidate, font=font, **direction)
                except (TypeError, ValueError):
                    width = draw.textlength(candidate, font=font)
                if width <= max_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        return lines

    def render_text_template(self, text: str, account: dict[str, Any], output: Path,
                             source_handle: str = "") -> Path:
        config = self.template_config(account)
        width, height = int(config["width"]), int(config["height"])
        if not (480 <= width <= 3000 and 480 <= height <= 3000):
            raise MediaError("أبعاد القالب يجب أن تكون بين 480 و3000 بكسل")
        template_relative = account.get("settings", {}).get("template_path")
        template_path = (self.settings.data_dir / str(template_relative)).resolve() if template_relative else None
        if template_path and template_path.is_file():
            try:
                template_path.relative_to(self.settings.data_dir.resolve())
                with Image.open(template_path) as original:
                    image = ImageOps.fit(original.convert("RGB"), (width, height), Image.Resampling.LANCZOS)
            except (ValueError, OSError) as exc:
                raise MediaError("تعذّر فتح صورة القالب المرفوعة") from exc
        else:
            image = Image.new("RGB", (width, height), config["background"])
        draw = ImageDraw.Draw(image)
        margin = max(40, min(int(config["margin"]), width // 5))
        accent = config["accent"]
        draw.rounded_rectangle((margin // 2, margin // 2, width - margin // 2, height - margin // 2),
                               radius=34, fill=config["surface"])
        draw.rectangle((margin // 2, margin // 2, width - margin // 2, margin // 2 + 12), fill=accent)

        logo_path = self._logo_path(account)
        if logo_path.exists():
            with Image.open(logo_path) as original:
                logo = original.convert("RGBA")
                logo.thumbnail((int(width * 0.55), int(height * 0.55)), Image.Resampling.LANCZOS)
                alpha = logo.getchannel("A").point(lambda p: int(p * float(config["logo_opacity"])))
                logo.putalpha(alpha)
                layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
                layer.paste(logo, ((width - logo.width) // 2, (height - logo.height) // 2), logo)
                image = Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")
                draw = ImageDraw.Draw(image)

        handle = account.get("username", "") or account["name"]
        small = self._font(max(25, width // 35), bold=True)
        draw.text((width - margin, margin + 12), handle, font=small, fill=accent,
                  anchor="ra", **self._prepare_text(handle)[1])
        draw.line((margin, margin + 86, width - margin, margin + 86), fill=config["muted"], width=2)

        direction = self._prepare_text(text)[1]
        available_width = width - 2 * margin
        available_height = height - (margin * 2 + 260)
        chosen_size = max(30, min(int(config["font_size"]), 110))
        lines: list[str] = []
        while chosen_size >= 30:
            font = self._font(chosen_size, bold=True)
            lines = self._wrap(draw, text.strip() or " ", font, available_width, direction)
            line_height = int(chosen_size * 1.62)
            if len(lines) * line_height <= available_height and len(lines) <= 18:
                break
            chosen_size -= 3
        font = self._font(chosen_size, bold=True)
        lines = self._wrap(draw, text.strip() or " ", font, available_width, direction)
        if len(lines) > 18:
            lines = lines[:18]
            lines[-1] = lines[-1].rstrip(" .،") + "…"
        line_height = int(chosen_size * 1.62)
        y = margin + 150 + max(0, (available_height - len(lines) * line_height) // 2)
        for line in lines:
            shaped, shape_kwargs = self._prepare_text(line)
            draw.text((width - margin, y), shaped, font=font, fill=config["text"], anchor="ra", **shape_kwargs)
            y += line_height

        footer = f"@{source_handle}" if config.get("source_attribution") and source_handle else "مرسال · محتوى مُراجع"
        footer_font = self._font(max(23, width // 42))
        draw.text((width - margin, height - margin - 36), footer, font=footer_font,
                  fill=config["muted"], anchor="ra", **self._prepare_text(footer)[1])
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG", optimize=True)
        return output

    def overlay_image(self, source: Path, account: dict[str, Any], output: Path) -> Path:
        config = self.template_config(account)
        with Image.open(source) as original:
            image = original.convert("RGB")
        image.thumbnail((2160, 2160), Image.Resampling.LANCZOS)
        width, height = image.size
        for region in config.get("redactions", []):
            try:
                x, y, w, h = [float(region[key]) for key in ("x", "y", "w", "h")]
                box = (int(x * width), int(y * height), int((x + w) * width), int((y + h) * height))
                crop = image.crop(box).filter(ImageFilter.GaussianBlur(radius=max(12, width // 45)))
                image.paste(crop, box)
            except (KeyError, TypeError, ValueError):
                raise MediaError("منطقة تعتيم الصورة غير صالحة؛ استخدم x,y,w,h بنسب من 0 إلى 1")
        image = ImageEnhance.Color(image).enhance(1.015)
        logo_path = self._logo_path(account)
        if logo_path.exists():
            base = image.convert("RGBA")
            with Image.open(logo_path) as original:
                logo = original.convert("RGBA")
                logo.thumbnail((max(70, width // 7), max(70, height // 7)), Image.Resampling.LANCZOS)
                alpha = logo.getchannel("A").point(lambda p: int(p * float(config["watermark_opacity"])))
                logo.putalpha(alpha)
                base.alpha_composite(logo, (width - logo.width - width // 35, height - logo.height - height // 35))
            image = base.convert("RGB")
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, format="PNG", optimize=True)
        return output

    async def process_image(self, source: Path, account: dict[str, Any], output: Path,
                            text: str = "", source_handle: str = "") -> Path:
        mode = self.template_config(account).get("mode", "rebuild")
        if mode == "rebuild" and text.strip():
            return await asyncio.to_thread(self.render_text_template, text, account, output, source_handle)
        if mode not in {"rebuild", "overlay"}:
            raise MediaError("وضع معالجة الصورة يجب أن يكون rebuild أو overlay")
        return await asyncio.to_thread(self.overlay_image, source, account, output)

    async def ocr_image(self, source: Path) -> str:
        executable = shutil.which("tesseract")
        if not executable:
            raise MediaError("Tesseract غير مثبت؛ نفّذ pkg install tesseract")
        langs = "ara+eng"
        try:
            listed = await asyncio.create_subprocess_exec(executable, "--list-langs", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, _ = await asyncio.wait_for(listed.communicate(), timeout=15)
            available = set(stdout.decode("utf-8", errors="ignore").splitlines())
            if "ara" not in available:
                raise MediaError("حزمة OCR العربية غير مثبتة؛ راجع README.md")
        except TimeoutError as exc:
            raise MediaError("انتهت مهلة فحص لغات OCR") from exc
        process = await asyncio.create_subprocess_exec(
            executable, str(source), "stdout", "-l", langs, "--psm", "6",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
        if process.returncode != 0:
            raise MediaError(f"فشل OCR: {stderr.decode('utf-8', errors='ignore')[:300]}")
        return stdout.decode("utf-8", errors="replace").strip()

    async def process_video(self, source: Path, account: dict[str, Any], output: Path) -> Path:
        executable = shutil.which("ffmpeg")
        if not executable:
            raise MediaError("FFmpeg غير مثبت؛ نفّذ pkg install ffmpeg")
        config = self.template_config(account)
        metadata = await self.probe(source)
        video_stream = next((stream for stream in metadata.get("streams", [])
                             if stream.get("codec_type") == "video"), {})
        frame_width = int(video_stream.get("width") or 0)
        frame_height = int(video_stream.get("height") or 0)
        filters: list[str] = []
        for region in config.get("video_delogo", []):
            try:
                x, y, w, h = (int(region[key]) for key in ("x", "y", "w", "h"))
            except (KeyError, TypeError, ValueError) as exc:
                raise MediaError("منطقة delogo يجب أن تحتوي x,y,w,h بوحدات البكسل") from exc
            if min(x, y) < 0 or min(w, h) < 2:
                raise MediaError("منطقة delogo تحتاج إحداثيات غير سالبة وعرضًا وارتفاعًا لا يقلان عن بكسلين")
            if frame_width and frame_height and (x + w >= frame_width or y + h >= frame_height):
                raise MediaError("منطقة delogo يجب أن تقع داخل إطار الفيديو مع ترك حافة حولها")
            # مرشح delogo في FFmpeg يرفض المنطقة الملاصقة تمامًا لحدود الإطار.
            safe_x, safe_y = max(1, x), max(1, y)
            if frame_width and frame_height:
                w = min(w, frame_width - safe_x - 1)
                h = min(h, frame_height - safe_y - 1)
            filters.append(f"delogo=x={safe_x}:y={safe_y}:w={w}:h={h}:show=0")
        if config.get("video_color_tweak"):
            filters.append("eq=saturation=1.025:contrast=1.008")
        filters.append("format=yuv420p")
        logo = self._logo_path(account)
        command = [executable, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
        if logo.exists():
            command += ["-i", str(logo)]
            graph = f"[0:v]{','.join(filters)}[base];[1:v]scale=140:-1,format=rgba,colorchannelmixer=aa={float(config['watermark_opacity'])}[logo];[base][logo]overlay=W-w-28:H-h-28[v]"
        else:
            graph = f"[0:v]{','.join(filters)}[v]"
        output.parent.mkdir(parents=True, exist_ok=True)
        command += ["-filter_complex", graph, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", "-max_muxing_queue_size", "1024", str(output)]
        process = await asyncio.create_subprocess_exec(*command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        if process.returncode != 0:
            raise MediaError(f"فشل FFmpeg: {stderr.decode('utf-8', errors='ignore')[-700:]}")
        return output

    async def probe(self, source: Path) -> dict[str, Any]:
        executable = shutil.which("ffprobe")
        if not executable:
            return {}
        process = await asyncio.create_subprocess_exec(
            executable, "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,width,height",
            "-of", "json", str(source), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
        if process.returncode != 0:
            return {}
        return json.loads(stdout.decode("utf-8"))
