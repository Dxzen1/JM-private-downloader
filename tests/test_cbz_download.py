"""Download regression tests using existing tasks and real image archives."""

import errno
import importlib
import io
import sqlite3
import struct
import zlib
from contextlib import closing
from datetime import UTC, datetime
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient


def png_page(rgb):
    """Produce a valid one-pixel PNG without an imaging dependency."""
    def chunk(kind, payload):
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" + bytes(rgb)))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def saved_archive(tmp_path, monkeypatch):
    download_dir = tmp_path / "downloads"
    ready_dir = download_dir / "ready"
    ready_dir.mkdir(parents=True)
    archive_path = ready_dir / "JM123-legacy.zip"
    pages = {
        "JM123/chapter01/001.png": png_page((255, 0, 0)),
        "JM123/chapter01/002.png": png_page((0, 255, 0)),
        "JM123/章节02/001.png": png_page((0, 0, 255)),
    }
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for name, page in pages.items():
            archive.writestr(name, page)

    # Create the deployed, ZIP-only schema before the current application starts.
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    task_id = "legacy-completed-task"
    now = datetime.now(UTC).isoformat()
    with closing(sqlite3.connect(data_dir / "portal.sqlite3")) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    album_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    zip_path TEXT,
                    zip_size INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id, "123", "completed", "下载完成", str(archive_path),
                    archive_path.stat().st_size, now, now,
                ),
            )

    for name, value in {
        "ADMIN_USERNAME": "tester",
        "ADMIN_PASSWORD": "a-very-strong-test-password",
        "SESSION_SECRET": "1" * 64,
        "SECURE_COOKIE": "false",
        "JM_PROVIDER": "stub",
        "JM_OPTION_PATH": str(tmp_path / "unused-option.yml"),
        "DATA_DIR": str(data_dir),
        "DOWNLOAD_DIR": str(download_dir),
        "TASK_MEMORY_MB": "512",
        "TASK_TIMEOUT_SECONDS": "900",
    }.items():
        monkeypatch.setenv(name, value)
    module = importlib.import_module("app.main")
    module = importlib.reload(module)

    # Deliberately omit the lifespan context: these tests never start a worker.
    client = TestClient(module.app)
    fixture = SimpleNamespace(
        client=client,
        module=module,
        task_id=task_id,
        path=archive_path,
        ready_dir=ready_dir,
        tmp_path=tmp_path,
        pages=pages,
        archive_bytes=archive_path.read_bytes(),
    )
    try:
        yield fixture
    finally:
        client.close()


def login(client):
    response = client.post(
        "/login", data={"username": "tester", "password": "a-very-strong-test-password"}
    )
    assert response.status_code == 200


def download_url(saved, query=""):
    return f"/tasks/{saved.task_id}/download{query}"


@pytest.mark.parametrize("query", ["", "?format=zip"])
def test_existing_zip_download_stays_compatible(saved_archive, query):
    saved = saved_archive
    login(saved.client)
    response = saved.client.get(download_url(saved, query))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="JM123.zip"'
    assert response.content == saved.archive_bytes


def test_old_completed_task_downloads_as_cbz_without_repack(saved_archive):
    saved = saved_archive
    login(saved.client)
    original_files = sorted(
        path.relative_to(saved.ready_dir) for path in saved.ready_dir.rglob("*")
    )
    zip_response = saved.client.get(download_url(saved))
    cbz_response = saved.client.get(download_url(saved, "?format=cbz"))

    assert cbz_response.status_code == 200
    assert cbz_response.headers["content-type"] == "application/vnd.comicbook+zip"
    assert cbz_response.headers["content-disposition"] == 'attachment; filename="JM123.cbz"'
    assert cbz_response.content == zip_response.content == saved.archive_bytes
    with ZipFile(io.BytesIO(cbz_response.content)) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == list(saved.pages)
        for name, page in saved.pages.items():
            assert archive.read(name) == page
    assert saved.path.read_bytes() == saved.archive_bytes
    assert sorted(
        path.relative_to(saved.ready_dir) for path in saved.ready_dir.rglob("*")
    ) == original_files
    assert saved.module.db.get_task(saved.task_id)["zip_path"] == str(saved.path)


@pytest.mark.parametrize("query", ["", "?format=zip", "?format=cbz"])
def test_all_download_formats_require_login(saved_archive, query):
    response = saved_archive.client.get(download_url(saved_archive, query))
    assert response.status_code == 401


@pytest.mark.parametrize("requested_format", ["rar", "pdf", "", "../cbz", "CBZ"])
def test_unknown_format_is_rejected(saved_archive, requested_format):
    saved = saved_archive
    login(saved.client)
    response = saved.client.get(download_url(saved), params={"format": requested_format})
    assert response.status_code == 422
    assert saved.path.read_bytes() == saved.archive_bytes


@pytest.mark.parametrize("requested_format", ["zip", "cbz"])
@pytest.mark.parametrize("location", ["outside", "ready-prefix-sibling", "missing", "directory"])
def test_download_confines_both_formats_to_existing_ready_files(saved_archive, requested_format, location):
    saved = saved_archive
    login(saved.client)
    if location == "outside":
        blocked_path = saved.tmp_path / "outside.zip"
        blocked_path.write_bytes(saved.archive_bytes)
    elif location == "ready-prefix-sibling":
        blocked_path = saved.ready_dir.with_name("ready-other") / "outside.zip"
        blocked_path.parent.mkdir()
        blocked_path.write_bytes(saved.archive_bytes)
    elif location == "missing":
        blocked_path = saved.ready_dir / "missing.zip"
    else:
        blocked_path = saved.ready_dir / "folder.zip"
        blocked_path.mkdir()
    saved.module.db.update_task(saved.task_id, zip_path=str(blocked_path))
    response = saved.client.get(download_url(saved), params={"format": requested_format})
    assert response.status_code == 404


@pytest.mark.parametrize("requested_format", ["zip", "cbz"])
@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_incomplete_tasks_cannot_download_in_either_format(saved_archive, requested_format, status):
    saved = saved_archive
    login(saved.client)
    saved.module.db.update_task(saved.task_id, status=status)
    response = saved.client.get(download_url(saved), params={"format": requested_format})
    assert response.status_code == 404


@pytest.mark.parametrize("requested_format", ["zip", "cbz"])
def test_missing_tasks_cannot_download_in_either_format(saved_archive, requested_format):
    saved = saved_archive
    login(saved.client)
    response = saved.client.get("/tasks/nonexistent/download", params={"format": requested_format})
    assert response.status_code == 404


def test_symlink_outside_ready_is_blocked_for_both_formats(saved_archive):
    saved = saved_archive
    login(saved.client)
    outside_path = saved.tmp_path / "outside.zip"
    outside_path.write_bytes(saved.archive_bytes)
    link_path = saved.ready_dir / "linked.zip"
    try:
        link_path.symlink_to(outside_path)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314 or exc.errno in {
            errno.EPERM, errno.EACCES, errno.ENOSYS, errno.ENOTSUP,
        }:
            pytest.skip("Creating symlinks is unavailable for this test account")
        raise
    saved.module.db.update_task(saved.task_id, zip_path=str(link_path))
    for requested_format in ("zip", "cbz"):
        response = saved.client.get(download_url(saved), params={"format": requested_format})
        assert response.status_code == 404


def test_delete_removes_the_one_archive_and_both_downloads(saved_archive):
    saved = saved_archive
    login(saved.client)
    cbz_response = saved.client.get(download_url(saved, "?format=cbz"))
    assert cbz_response.status_code == 200
    page = saved.client.get("/").text
    csrf = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
    response = saved.client.post(
        f"/tasks/{saved.task_id}/delete", data={"csrf": csrf}, follow_redirects=False
    )
    assert response.status_code == 303
    assert not saved.path.exists()
    assert saved.module.db.get_task(saved.task_id) is None
    assert not list(saved.ready_dir.iterdir())
    for requested_format in ("zip", "cbz"):
        response = saved.client.get(download_url(saved), params={"format": requested_format})
        assert response.status_code == 404
