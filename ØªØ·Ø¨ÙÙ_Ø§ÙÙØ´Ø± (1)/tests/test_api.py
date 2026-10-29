from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from automation.server import create_app


def test_account_source_ai_media_and_backup_api(settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["dry_run"] is True
        assert health.json()["database"] == "bot_memory.db"

        created = client.post("/api/accounts", json={
            "name": "حساب API", "platform": "x", "username": "api_account",
            "proxy_url": "http://user:password@example.com:8080",
            "phone_replacement": "+966500000000", "min_delay_sec": 0, "max_delay_sec": 0,
            "settings": {"template": {"mode": "rebuild"}},
        })
        assert created.status_code == 201, created.text
        account = created.json()
        account_id = account["id"]
        assert "proxy_url" not in account and "password" not in created.text
        assert account["proxy_masked"] == "http://user:***@example.com:8080"
        assert account["sources"] == [] and account["profile"] == {}

        source = client.post(f"/api/accounts/{account_id}/sources", json={
            "platform": "x", "handle": "source", "url": "https://x.com/source",
        })
        assert source.status_code == 201, source.text
        source_id = source.json()["id"]
        duplicate = client.post(f"/api/accounts/{account_id}/sources", json={
            "platform": "x", "handle": "source", "url": "https://x.com/source",
        })
        assert duplicate.status_code == 409

        accounts = client.get("/api/accounts").json()
        assert accounts[0]["sources"][0]["id"] == source_id
        dashboard = client.get("/api/dashboard").json()
        assert dashboard["accounts"][0]["sources"][0]["handle"] == "source"

        instruction = client.post("/api/chat", json={"account_id": account_id, "message": "استبعد إعلانات المقاهي"})
        assert instruction.status_code == 201
        chat = client.get(f"/api/chat?account_id={account_id}").json()
        assert [item["role"] for item in chat] == ["user", "assistant"]

        ai = client.patch("/api/ai/config", json={"model": "auto", "timeout_seconds": 30})
        assert ai.status_code == 200
        assert ai.json()["key_configured"] is False
        assert "api_key" not in ai.text.lower()

        state = {"cookies": [{"name": "session", "value": "secret", "domain": ".x.com"}], "origins": []}
        cookies = client.post(f"/api/accounts/{account_id}/cookies", files={
            "file": ("session.json", json.dumps(state).encode(), "application/json"),
        })
        assert cookies.status_code == 200, cookies.text

        buffer = io.BytesIO()
        Image.new("RGB", (48, 48), "#65e6bd").save(buffer, format="PNG")
        asset = client.post(
            f"/api/accounts/{account_id}/assets", data={"kind": "logo"},
            files={"file": ("logo.png", buffer.getvalue(), "image/png")},
        )
        assert asset.status_code == 200, asset.text
        preview = client.post(f"/api/accounts/{account_id}/template-preview")
        assert preview.status_code == 200, preview.text
        image = client.get(preview.json()["preview_url"])
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG")

        backup = client.post("/api/maintenance/backup")
        assert backup.status_code == 200, backup.text
        download = client.get(backup.json()["download_url"])
        assert download.status_code == 200
        assert download.content.startswith(b"\x1f\x8b")
        assert client.get("/api/backups/..%2F..%2F.env").status_code in {404, 422}

        assert client.delete(f"/api/sources/{source_id}").status_code == 200
        deleted = client.delete(f"/api/accounts/{account_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["safety_archive"].endswith(".tar.gz")
        assert client.get(f"/api/accounts/{account_id}").status_code == 404


def test_review_validation_and_unknown_confirmation(settings, db, discovered_post: dict) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        post_id = discovered_post["id"]
        missing_reason = client.post(f"/api/posts/{post_id}/review", json={"action": "reject", "comment": ""})
        assert missing_reason.status_code == 422
        rejected = client.post(f"/api/posts/{post_id}/review", json={
            "action": "reject", "comment": "إعلان غير مناسب", "processed_text": "نص معدل",
        })
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"

        db.update_post(post_id, {"status": "publish_unknown", "error": "غامض"})
        confirmed = client.post(f"/api/posts/{post_id}/confirm", json={"status": "failed", "note": "لم يصل"})
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "failed"
        again = client.post(f"/api/posts/{post_id}/confirm", json={"status": "published"})
        assert again.status_code == 409
