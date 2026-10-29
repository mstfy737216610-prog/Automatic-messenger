from __future__ import annotations

from pathlib import Path

import pytest

from automation.config import Settings
from automation.db import Database


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    value = Settings(
        data_dir=tmp_path / "data",
        scheduler_enabled=False,
        worker_poll_seconds=0.01,
        scheduler_poll_seconds=0.01,
        ai_max_retries=0,
        dry_run=True,
        publishing_enabled=False,
    )
    value.ensure_directories()
    return value


@pytest.fixture
def db(settings: Settings) -> Database:
    return Database(settings.database_path)


@pytest.fixture
def account(db: Database) -> dict:
    return db.create_account({
        "name": "حساب الاختبار",
        "platform": "x",
        "username": "my_university",
        "enabled": False,
        "auto_publish": False,
        "review_required": True,
        "phone_replacement": "+966500000000",
        "monitor_interval_sec": 900,
        "min_delay_sec": 0,
        "max_delay_sec": 0,
        "settings": {},
    })


@pytest.fixture
def source(db: Database, account: dict) -> dict:
    return db.add_source(account["id"], {
        "platform": "x",
        "handle": "source_account",
        "url": "https://x.com/source_account",
        "enabled": True,
        "config": {},
    })


@pytest.fixture
def discovered_post(db: Database, account: dict, source: dict) -> dict:
    post_id = db.insert_discovered_post(account["id"], source["id"], {
        "external_id": "post-1",
        "url": "https://x.com/source_account/status/post-1",
        "author": "source_account",
        "text": "مساعدة طلابية للتواصل ٠٥٠ ١٢٣ ٤٥٦٧ @source_account",
        "media": [],
        "raw": {},
    })
    assert post_id
    return db.get_post(post_id)
