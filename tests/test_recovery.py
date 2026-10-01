from dataclasses import replace

from app.config import Settings
from app.db import Database
from app import worker
from app import provider


def test_interrupted_task_does_not_restart_automatically(tmp_path):
    db = Database(tmp_path / "portal.sqlite3")
    db.initialize()
    task = db.create_task("123")
    db.claim_next()
    db.initialize()
    assert db.get_task(task["id"])["status"] == "failed"
    assert db.claim_next() is None
    db.initialize()
    assert db.get_task(task["id"])["status"] == "failed"
    assert db.retry_task(task["id"])
    assert db.claim_next()["id"] == task["id"]


def test_recovery_preserves_other_tasks(tmp_path):
    db = Database(tmp_path / "portal.sqlite3")
    db.initialize()
    done = db.create_task("100")
    db.claim_next()
    db.update_task(done["id"], status="completed", zip_path="saved.zip", zip_size=10)
    queued = db.create_task("101")
    db.initialize()
    assert db.get_task(done["id"])["zip_path"] == "saved.zip"
    assert db.get_task(done["id"])["status"] == "completed"
    assert db.claim_next()["id"] == queued["id"]


def task_fixture(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data", download_dir=tmp_path / "downloads",
        admin_username="test", admin_password="strong-test-password",
        session_secret="x" * 64, secure_cookie=False, provider="stub",
        jm_option_path=tmp_path / "unused.yml", max_storage_gb=1,
        retention_hours=168, max_album_id_length=12,
    )
    db = Database(settings.data_dir / "portal.sqlite3")
    db.initialize()
    db.create_task("123")
    return db, settings, db.claim_next()


def test_isolated_task_completes_and_persists_result(tmp_path):
    db, settings, task = task_fixture(tmp_path)
    worker.run_task_isolated(db, settings, task)
    saved = db.get_task(task["id"])
    assert saved["status"] == "completed"
    from pathlib import Path
    assert Path(saved["zip_path"]).is_file()


def test_task_timeout_marks_failure_and_allows_next_task(tmp_path):
    db, settings, task = task_fixture(tmp_path)
    settings = replace(settings, task_timeout_seconds=0)
    worker.run_task_isolated(db, settings, task)
    assert db.get_task(task["id"])["status"] == "failed"
    assert "超时" in db.get_task(task["id"])["message"]
    next_task = db.create_task("124")
    worker.run_task_isolated(db, replace(settings, task_timeout_seconds=30), db.claim_next())
    assert db.get_task(next_task["id"])["status"] == "completed"


def test_job_options_bound_parallelism_and_preserve_client_settings(tmp_path):
    options = {"client": {"retry_times": 2}, "download": {"threading": {"image": 8, "photo": 4}}}
    result = provider.prepare_job_options(options, tmp_path)
    assert result["download"]["threading"] == {"image": 1, "photo": 1}
    assert result["client"] == {"retry_times": 2}
    assert result["dir_rule"]["base_dir"] == str(tmp_path)
