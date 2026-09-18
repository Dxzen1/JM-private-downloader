from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Settings
from .db import Database
from .provider import download_album, make_zip

logger = logging.getLogger(__name__)


def _storage_used(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def process_task(db: Database, settings: Settings, task: dict) -> None:
    task_id = task["id"]
    album_id = task["album_id"]
    work_dir = settings.download_dir / "work" / task_id
    archive_base = settings.download_dir / "ready" / f"JM{album_id}-{task_id[:8]}"
    try:
        limit = int(settings.max_storage_gb * 1024**3)
        if _storage_used(settings.download_dir) >= limit:
            raise RuntimeError("存储空间已达到网站配额，请先删除旧任务")
        shutil.rmtree(work_dir, ignore_errors=True)
        download_album(album_id, work_dir, settings.provider, settings.jm_option_path)
        db.update_task(task_id, message="正在生成 ZIP")
        zip_path = make_zip(work_dir, archive_base)
        db.update_task(
            task_id,
            status="completed",
            message="下载完成",
            zip_path=str(zip_path),
            zip_size=zip_path.stat().st_size,
        )
    except Exception as exc:
        logger.exception("Task %s failed", task_id)
        db.update_task(task_id, status="failed", message=str(exc)[:500])
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def cleanup_expired(db: Database, settings: Settings) -> None:
    cutoff = datetime.now(UTC) - timedelta(hours=settings.retention_hours)
    for task in db.list_tasks(1000):
        if task["status"] == "running":
            continue
        try:
            updated = datetime.fromisoformat(task["updated_at"])
        except ValueError:
            continue
        if updated < cutoff:
            if task.get("zip_path"):
                Path(task["zip_path"]).unlink(missing_ok=True)
            db.delete_task(task["id"])


async def worker_loop(db: Database, settings: Settings, stop: asyncio.Event) -> None:
    last_cleanup = datetime.min.replace(tzinfo=UTC)
    while not stop.is_set():
        task = db.claim_next()
        if task:
            await asyncio.to_thread(process_task, db, settings, task)
            continue
        now = datetime.now(UTC)
        if now - last_cleanup > timedelta(hours=1):
            await asyncio.to_thread(cleanup_expired, db, settings)
            last_cleanup = now
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            pass
