from __future__ import annotations

import json
import os
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, Settings
from .db import Database


def create_backup(settings: Settings, db: Database) -> Path:
    settings.ensure_directories()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    destination = settings.data_dir / "backups" / f"mirsal-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="mirsal-backup-", dir=settings.data_dir / "tmp") as temp:
        temp_path = Path(temp)
        snapshot = temp_path / "bot_memory.db"
        source = sqlite3.connect(db.path)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "format": 1,
            "includes": ["bot_memory.db", "account sessions", "profiles", "assets", "selectors.yaml"],
            "excludes": ["AI_API_KEY", "downloaded media", "cookies converted for yt-dlp"],
        }
        (temp_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with tarfile.open(destination, "w:gz", compresslevel=6) as archive:
            archive.add(snapshot, arcname="bot_memory.db")
            archive.add(temp_path / "manifest.json", arcname="manifest.json")
            accounts = settings.data_dir / "accounts"
            if accounts.exists():
                for path in accounts.rglob("*"):
                    if not path.is_file() or path.name.startswith("cookies-") or "media" in path.parts:
                        continue
                    archive.add(path, arcname=str(Path("accounts") / path.relative_to(accounts)))
            selectors = PROJECT_ROOT / "config/selectors.yaml"
            if selectors.exists():
                archive.add(selectors, arcname="config/selectors.yaml")
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return destination


def archive_account(settings: Settings, account_id: str, include_media: bool = False) -> Path:
    source = settings.data_dir / "accounts" / account_id
    if not source.is_dir():
        raise ValueError("مجلد الحساب غير موجود")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    destination = settings.data_dir / "exports" / f"account-{account_id[:8]}-{stamp}.tar.gz"
    with tarfile.open(destination, "w:gz", compresslevel=6) as archive:
        for path in source.rglob("*"):
            if not path.is_file() or path.name.startswith("cookies-"):
                continue
            if not include_media and "media" in path.parts:
                continue
            archive.add(path, arcname=str(Path("accounts") / account_id / path.relative_to(source)))
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return destination


def cleanup_files(settings: Settings, days: int = 90) -> dict[str, Any]:
    cutoff = datetime.now(UTC).timestamp() - timedelta(days=days).total_seconds()
    removed = bytes_freed = 0
    accounts = settings.data_dir / "accounts"
    for path in accounts.rglob("*") if accounts.exists() else []:
        if not path.is_file() or "media" not in path.parts:
            continue
        try:
            stat = path.stat()
            if stat.st_mtime < cutoff:
                bytes_freed += stat.st_size
                path.unlink()
                removed += 1
        except OSError:
            continue
    for path in settings.data_dir.rglob("cookies-*.txt"):
        try:
            path.unlink()
        except OSError:
            pass
    for directory in sorted((p for p in accounts.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True) if accounts.exists() else []:
        try:
            directory.rmdir()
        except OSError:
            pass
    return {"files_removed": removed, "bytes_freed": bytes_freed}
