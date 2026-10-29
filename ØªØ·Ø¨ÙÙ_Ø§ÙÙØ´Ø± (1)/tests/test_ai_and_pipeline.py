from __future__ import annotations

import pytest

from automation.ai import AIError, parse_json_object
from automation.db import Database
from automation.models import AIClassification
from automation.pipeline import AutomationPipeline, replace_phone_numbers


def test_json_parser_accepts_fences_and_surrounding_text() -> None:
    assert parse_json_object('```json\n{"decision":"review"}\n```')["decision"] == "review"
    assert parse_json_object('الناتج: {"ok":true} شكرًا')["ok"] is True
    with pytest.raises(AIError):
        parse_json_object('[{"ok":true}]')
    with pytest.raises(AIError):
        parse_json_object('not json')


@pytest.mark.parametrize(("text", "expected"), [
    ("اتصل 050 123 4567", "اتصل +966500000000"),
    ("اتصل ٠٥٠ ١٢٣ ٤٥٦٧", "اتصل +966500000000"),
    ("اتصل +966 50 123 4567", "اتصل +966500000000"),
    ("رقم قصير 12345", "رقم قصير 12345"),
])
def test_phone_replacement(text: str, expected: str) -> None:
    assert replace_phone_numbers(text, "+966500000000") == expected


def test_phone_replacement_can_be_disabled() -> None:
    text = "اتصل 050 123 4567"
    assert replace_phone_numbers(text, "") == text


@pytest.mark.asyncio
async def test_ai_failure_goes_to_review(settings, db: Database, discovered_post: dict, monkeypatch) -> None:
    pipeline = AutomationPipeline(settings, db)

    async def no_media(*args, **kwargs):
        return []

    async def fail_ai(*args, **kwargs):
        raise AIError("timeout")

    monkeypatch.setattr(pipeline.downloader, "download_all", no_media)
    monkeypatch.setattr(pipeline.ai, "classify_post", fail_ai)
    await pipeline.process_post(discovered_post["id"])
    result = db.get_post(discovered_post["id"])
    assert result["status"] == "pending_review"
    assert result["ai_decision"] == "review"
    assert "timeout" in result["error"]


@pytest.mark.asyncio
async def test_classification_phone_username_and_review(settings, db: Database, discovered_post: dict, monkeypatch) -> None:
    pipeline = AutomationPipeline(settings, db)

    async def no_media(*args, **kwargs):
        return []

    async def classify(*args, **kwargs):
        return AIClassification(
            decision="publish", reason="مساعدة طلابية", category="student_help",
            confidence=0.97, replace_phone=True,
            cleaned_text="للمساعدة تواصل 050 123 4567 أو @source_account",
        )

    monkeypatch.setattr(pipeline.downloader, "download_all", no_media)
    monkeypatch.setattr(pipeline.ai, "classify_post", classify)
    await pipeline.process_post(discovered_post["id"])
    result = db.get_post(discovered_post["id"])
    assert result["status"] == "pending_review"
    assert "+966500000000" in result["processed_text"]
    assert "@my_university" in result["processed_text"]
    assert "050 123 4567" not in result["processed_text"]


@pytest.mark.asyncio
async def test_dry_run_never_calls_publisher(settings, db: Database, discovered_post: dict) -> None:
    pipeline = AutomationPipeline(settings, db)

    async def forbidden(*args, **kwargs):
        raise AssertionError("publisher must not run in dry-run")

    pipeline.publisher.publish = forbidden
    db.update_post(discovered_post["id"], {"status": "queued"})
    await pipeline.publish_post(discovered_post["id"])
    assert db.get_post(discovered_post["id"])["status"] == "ready"


@pytest.mark.asyncio
async def test_publish_unknown_is_not_retried(settings, db: Database, discovered_post: dict, monkeypatch) -> None:
    from automation.browser import PublishUnknown

    settings.dry_run = False
    settings.publishing_enabled = True
    pipeline = AutomationPipeline(settings, db)

    async def unknown(*args, **kwargs):
        raise PublishUnknown("نتيجة غامضة")

    monkeypatch.setattr(pipeline.publisher, "publish", unknown)
    db.update_post(discovered_post["id"], {"status": "queued"})
    await pipeline.publish_post(discovered_post["id"])
    result = db.get_post(discovered_post["id"])
    assert result["status"] == "publish_unknown"
    assert "غامضة" in result["error"]


@pytest.mark.asyncio
async def test_reject_requires_reason_and_is_learned(settings, db: Database, discovered_post: dict) -> None:
    pipeline = AutomationPipeline(settings, db)
    with pytest.raises(ValueError):
        await pipeline.review_post(discovered_post["id"], "reject", "")
    result = await pipeline.review_post(discovered_post["id"], "reject", "إعلان مقهى غير جامعي")
    assert result["status"] == "rejected"
    feedback = db.learning_context(discovered_post["account_id"])["feedback"]
    assert feedback[0]["reason"] == "إعلان مقهى غير جامعي"
