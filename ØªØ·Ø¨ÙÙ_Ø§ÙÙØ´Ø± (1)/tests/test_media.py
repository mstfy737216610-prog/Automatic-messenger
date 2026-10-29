from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from automation.media import MediaProcessor


@pytest.mark.asyncio
async def test_arabic_template_and_ocr(settings, account: dict, tmp_path: Path) -> None:
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract unavailable")
    languages = await asyncio.to_thread(subprocess.check_output, ["tesseract", "--list-langs"], text=True)
    if "ara" not in languages.splitlines():
        pytest.skip("Arabic Tesseract data unavailable")

    processor = MediaProcessor(settings)
    output = tmp_path / "arabic-template.png"
    processor.render_text_template("جدول محاضرات الجامعة\nالأحد: رياضيات — القاعة ٢٤", account, output)
    with Image.open(output) as image:
        assert image.size == (1080, 1350)
        assert image.mode == "RGB"

    # لوحة OCR بسيطة تقلل تأثير الزخارف على دقة الاختبار.
    source = tmp_path / "ocr-source.png"
    image = Image.new("RGB", (1400, 360), "white")
    draw = ImageDraw.Draw(image)
    font = processor._font(100, bold=True)
    text, kwargs = processor._prepare_text("جدول محاضرات الجامعة")
    draw.text((1320, 170), text, font=font, fill="black", anchor="rm", **kwargs)
    image.save(source)
    extracted = await processor.ocr_image(source)
    assert extracted.strip()
    assert "جامع" in extracted or "محاضر" in extracted


@pytest.mark.asyncio
async def test_overlay_and_video_processing(settings, account: dict, tmp_path: Path) -> None:
    processor = MediaProcessor(settings)
    account["settings"] = {
        "template": {
            "mode": "overlay",
            "redactions": [{"x": 0.0, "y": 0.0, "w": 0.4, "h": 0.2}],
            "video_delogo": [{"x": 0, "y": 0, "w": 32, "h": 24}],
            "video_color_tweak": True,
            "watermark_opacity": 0.5,
        }
    }
    source = tmp_path / "source.png"
    Image.new("RGB", (640, 480), "#2870b0").save(source)
    output = tmp_path / "overlay.png"
    await processor.process_image(source, account, output)
    with Image.open(output) as result:
        assert result.size == (640, 480)

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg unavailable")
    video = tmp_path / "source.mp4"
    await asyncio.to_thread(subprocess.run, [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=12",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", "0.6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video),
    ], check=True, timeout=60)
    processed = tmp_path / "processed.mp4"
    await processor.process_video(video, account, processed)
    probe = json.loads(await asyncio.to_thread(subprocess.check_output, [
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
        "-of", "json", str(processed),
    ], text=True))
    streams = probe["streams"]
    assert any(item["codec_type"] == "video" and item["codec_name"] == "h264" for item in streams)
    assert any(item["codec_type"] == "audio" and item["codec_name"] == "aac" for item in streams)
