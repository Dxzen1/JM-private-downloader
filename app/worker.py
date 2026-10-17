from __future__ import annotations

import asyncio
import logging
import multiprocessing
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Settings
from .db import Database
from .eh_provider import download_gallery
from .provider import download_album, make_zip
from .sources import SOURCE_PREFIXES

logger = logging.getLogger(__name__)


def _task_child(db_path: str, settings: Settings, task: dict) -> None:
    # Limit the task process, leaving memory available for the web process.
    if sys.platform.startswith("linux"):
        import resource

        limit = settings.task_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    process_task(Database(Path(db_path)), settings, task)


def run_task_isolated(db: Database, settings: Settings, task: dict) -> None:
    process = multiprocessing.get_context("spawn").Process(
        target=_task_child, args=(str(db.path), settings, task)
    )
    message = ""
    try:
        process.start()
        timeout = settings.task_timeout_seconds if task["source"] == "jm" else settings.eh_timeout_seconds + 10
        process.join(timeout)
        if process.is_alive():
            message = "任务运行超时，已停止；请检查后手动重试"
            process.terminate()
            process.join(5)
            if process.is_alive():
                process.kill()
                process.join()
        elif process.exitcode != 0:
            message = "任务进程异常退出，可能超过内存限制；请检查后手动重试"
        elif db.get_task(task["id"])["status"] == "running":
            message = "任务进程未返回结果；请检查后手动重试"
    except Exception:
        logger.exception("Unable to run isolated task %s", task["id"])
        if process.pid is not None and process.is_alive():
            process.kill()
            process.join()
        message = "任务进程无法启动；请检查服务日志"
    finally:
        if process.pid is not None:
            process.close()
    if message:
        db.update_task(task["id"], status="failed", message=message)


def _storage_used(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def process_task(db: Database, settings: Settings, task: dict) -> None:
    task_id = task["id"]
    album_id = task["album_id"]
    source = task["source"]
    work_dir = settings.download_dir / "work" / task_id
    archive_base = settings.download_dir / "ready" / f"{SOURCE_PREFIXES[source]}{album_id}-{task_id[:8]}"
    try:
        limit = int(settings.max_storage_gb * 1024**3)
        if _storage_used(settings.download_dir) >= limit:
            raise RuntimeError("存储空间已达到网站配额，请先删除旧任务")
        shutil.rmtree(work_dir, ignore_errors=True)
        if source == "jm":
            download_album(album_id, work_dir, settings.provider, settings.jm_option_path)
        else:
            download_gallery(
                source, task["source_url"], work_dir, settings.eh_provider,
                settings.eh_option_path, settings.eh_timeout_seconds,
            )
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
            await asyncio.to_thread(run_task_isolated, db, settings, task)
            continue
        now = datetime.now(UTC)
        if now - last_cleanup > timedelta(hours=1):
            await asyncio.to_thread(cleanup_expired, db, settings)
            last_cleanup = now
        try:
            await asyncio.wait_for(stop.wait(), timeout=2)
        except TimeoutError:
            pass
