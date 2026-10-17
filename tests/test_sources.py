import sqlite3

import pytest

from app.db import Database
from app.sources import normalize_target


def test_canonical_gallery_and_host_detection():
    target = normalize_target("ehentai", " http://EXHENTAI.ORG/g/123/ABCDEF0123?p=2#top ")
    assert target.source == "exhentai"
    assert target.album_id == "123"
    assert target.source_url == "https://exhentai.org/g/123/abcdef0123/"


@pytest.mark.parametrize("source, value", [
    ("other", "123"), ("jm", "１２３"), ("jm", "123/456"),
    ("ehentai", "https://e-hentai.org:8000/g/123/0123456789/"),
    ("ehentai", "https://user@e-hentai.org/g/123/0123456789/"),
    ("ehentai", "https://e-hentai.org/s/0123456789/123-1"),
    ("ehentai", "https://[broken/g/123/0123456789/"),
])
def test_reject_invalid_targets(source, value):
    with pytest.raises(ValueError):
        normalize_target(source, value)


def test_legacy_database_migration_preserves_download(tmp_path):
    path = tmp_path / "portal.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE tasks(id TEXT PRIMARY KEY, album_id TEXT NOT NULL, status TEXT NOT NULL, "
            "message TEXT NOT NULL DEFAULT '', zip_path TEXT, zip_size INTEGER, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO tasks VALUES ('old', '123', 'completed', 'done', '/old.zip', 100, 'now', 'now')"
        )
    db = Database(path)
    db.initialize()
    db.initialize()
    task = db.get_task("old")
    assert task["source"] == "jm"
    assert task["source_url"] == ""
    assert task["zip_path"] == "/old.zip"
    assert task["status"] == "completed"


def test_source_aware_deduplication_and_retry(tmp_path):
    db = Database(tmp_path / "portal.sqlite3")
    db.initialize()
    jm = db.create_task("123")
    eh = db.create_task("123", "ehentai", "https://e-hentai.org/g/123/0123456789/")
    ex = db.create_task("123", "exhentai", "https://exhentai.org/g/123/0123456789/")
    # Deduplication must also find tasks older than the API's 100-task window.
    for n in range(124, 225):
        db.create_task(str(n))
    assert db.create_task("123")["id"] == jm["id"]
    assert db.create_task("123", "ehentai", eh["source_url"])["id"] == eh["id"]
    assert len({jm["id"], eh["id"], ex["id"]}) == 3
    db.update_task(ex["id"], status="failed", message="test failure")
    assert db.retry_task(ex["id"])
    retried = db.get_task(ex["id"])
    assert retried["status"] == "queued"
    assert retried["source_url"] == ex["source_url"]


def test_restart_keeps_interrupted_tasks_failed_for_manual_retry(tmp_path):
    db = Database(tmp_path / "portal.sqlite3")
    db.initialize()
    task = db.create_task("123")
    db.claim_next()
    db.initialize()
    assert db.get_task(task["id"])["status"] == "failed"
    assert db.claim_next() is None
    assert db.retry_task(task["id"])
