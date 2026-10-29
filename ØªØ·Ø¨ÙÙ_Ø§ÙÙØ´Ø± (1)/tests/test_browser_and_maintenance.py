from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from automation.browser import (
    BrowserError,
    import_storage_state,
    netscape_cookies,
    playwright_proxy,
)
from automation.config import mask_proxy
from automation.maintenance import create_backup


def test_proxy_parsing_and_masking() -> None:
    parsed = playwright_proxy("socks5://user:p%40ss@example.com:1080")
    assert parsed == {"server": "socks5://example.com:1080", "username": "user", "password": "p@ss"}
    assert mask_proxy("socks5://user:p%40ss@example.com:1080") == "socks5://user:***@example.com:1080"
    with pytest.raises(BrowserError):
        playwright_proxy("file:///tmp/socket")


def test_import_storage_state_and_netscape_conversion(settings, account: dict) -> None:
    state = import_storage_state(settings, account, [{
        "name": "session", "value": "secret", "domain": ".x.com", "path": "/",
        "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax",
    }])
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["cookies"][0]["name"] == "session"
    assert saved["origins"] == []
    converted = netscape_cookies(settings, account)
    text = converted.read_text(encoding="utf-8")
    assert "#HttpOnly_.x.com" in text
    assert "session\tsecret" in text


def test_backup_excludes_key_media_and_temporary_cookies(settings, db, account: dict) -> None:
    account_dir = settings.data_dir / "accounts" / account["id"]
    (account_dir / "assets").mkdir(parents=True, exist_ok=True)
    (account_dir / "media" / "post").mkdir(parents=True, exist_ok=True)
    import_storage_state(settings, account, [{
        "name": "session", "value": "secret", "domain": ".x.com",
    }])
    (account_dir / "assets" / "logo.png").write_bytes(b"logo")
    (account_dir / "media" / "post" / "video.mp4").write_bytes(b"media")
    netscape_cookies(settings, account)
    (settings.data_dir / ".env").write_text("AI_API_KEY=do-not-backup", encoding="utf-8")

    backup = create_backup(settings, db)
    with tarfile.open(backup, "r:gz") as archive:
        names = archive.getnames()
        manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
    assert "bot_memory.db" in names
    assert "manifest.json" in names
    assert f"accounts/{account['id']}/session-x.json" in names
    assert f"accounts/{account['id']}/assets/logo.png" in names
    assert "config/selectors.yaml" in names
    assert not any("media" in Path(name).parts for name in names)
    assert not any(Path(name).name.startswith("cookies-") for name in names)
    assert not any(Path(name).name == ".env" for name in names)
    assert "AI_API_KEY" in manifest["excludes"]
