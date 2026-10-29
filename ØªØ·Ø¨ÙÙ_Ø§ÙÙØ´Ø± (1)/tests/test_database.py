from __future__ import annotations

from datetime import UTC, datetime, timedelta

from automation.db import Database


def test_dedup_survives_post_cleanup(db: Database, account: dict, source: dict) -> None:
    payload = {
        "external_id": "persistent-1",
        "url": "https://x.com/source_account/status/persistent-1",
        "author": "source_account",
        "text": "منشور لا يجب تكراره",
        "media": [],
        "raw": {},
    }
    post_id = db.insert_discovered_post(account["id"], source["id"], payload)
    assert post_id
    assert db.insert_discovered_post(account["id"], source["id"], payload) is None

    old = (datetime.now(UTC) - timedelta(days=120)).isoformat(timespec="seconds")
    db.update_post(post_id, {"status": "ignored"})
    with db.transaction() as conn:
        conn.execute("UPDATE posts SET created_at=? WHERE id=?", (old, post_id))
    result = db.cleanup(90)
    assert result["posts"] == 1
    assert db.get_post(post_id) is None
    assert db.insert_discovered_post(account["id"], source["id"], payload) is None


def test_active_jobs_are_unique_and_claimed_atomically(db: Database, account: dict) -> None:
    first = db.enqueue("monitor", account["id"], max_attempts=2)
    duplicate = db.enqueue("monitor", account["id"], max_attempts=2)
    assert first
    assert duplicate is None
    claimed = db.claim_job()
    assert claimed and claimed["id"] == first and claimed["attempts"] == 1
    assert db.claim_job() is None
    db.fail_job(claimed, "temporary", retry=True)
    assert db.claim_job() is None  # backoff still active
    with db.transaction() as conn:
        row = conn.execute("SELECT status,attempts,last_error FROM jobs WHERE id=?", (first,)).fetchone()
    assert row["status"] == "queued" and row["attempts"] == 1
    assert "temporary" in row["last_error"]


def test_learning_context_and_public_account_masking(db: Database) -> None:
    account = db.create_account({
        "name": "مقنّع", "platform": "x", "username": "masked",
        "proxy_url": "socks5://user:secret@example.com:1080",
        "settings": {"template": {"mode": "overlay"}},
    })
    db.add_instruction(account["id"], "استبعد الإعلانات العامة")
    db.add_instruction(None, "قاعدة عامة")
    db.add_feedback(account["id"], None, "reject", "إعلان غير مناسب", "advertisement")
    db.save_profile(account["id"], {"dialect": "خليجية", "topics": ["جداول"]})

    public = Database.public_account(account)
    assert "proxy_url" not in public
    assert public["proxy_masked"] == "socks5://user:***@example.com:1080"
    assert public["settings"]["template"]["mode"] == "overlay"
    context = db.learning_context(account["id"])
    assert len(context["instructions"]) == 2
    assert context["feedback"][0]["reason"] == "إعلان غير مناسب"
    assert context["profile"]["dialect"] == "خليجية"
