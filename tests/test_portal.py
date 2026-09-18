import importlib
import os
import time

from fastapi.testclient import TestClient


def load_app(tmp_path):
    os.environ.update(
        {
            "ADMIN_USERNAME": "tester",
            "ADMIN_PASSWORD": "a-very-strong-test-password",
            "SESSION_SECRET": "1" * 64,
            "SECURE_COOKIE": "false",
            "JM_PROVIDER": "stub",
            "DATA_DIR": str(tmp_path / "data"),
            "DOWNLOAD_DIR": str(tmp_path / "downloads"),
        }
    )
    import app.main

    return importlib.reload(app.main).app


def login(client):
    response = client.post(
        "/login", data={"username": "tester", "password": "a-very-strong-test-password"}
    )
    assert response.status_code == 200


def csrf_from_page(client):
    page = client.get("/").text
    marker = 'name="csrf" value="'
    return page.split(marker, 1)[1].split('"', 1)[0]


def test_login_required(tmp_path):
    with TestClient(load_app(tmp_path)) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_create_download_and_delete(tmp_path):
    with TestClient(load_app(tmp_path)) as client:
        login(client)
        csrf = csrf_from_page(client)
        response = client.post("/tasks", data={"album_id": "JM123", "csrf": csrf})
        assert response.status_code == 200

        task = None
        for _ in range(30):
            tasks = client.get("/api/tasks").json()
            if tasks and tasks[0]["status"] == "completed":
                task = tasks[0]
                break
            time.sleep(0.1)
        assert task is not None
        archive = client.get(f"/tasks/{task['id']}/download")
        assert archive.status_code == 200
        assert archive.headers["content-type"] == "application/zip"
        assert archive.content.startswith(b"PK")

        response = client.post(
            f"/tasks/{task['id']}/delete", data={"csrf": csrf}, follow_redirects=False
        )
        assert response.status_code == 303


def test_rejects_bad_id_and_csrf(tmp_path):
    with TestClient(load_app(tmp_path)) as client:
        login(client)
        csrf = csrf_from_page(client)
        response = client.post(
            "/tasks", data={"album_id": "not-an-id", "csrf": csrf}, follow_redirects=False
        )
        assert response.status_code == 303
        assert "error=" in response.headers["location"]
        response = client.post("/tasks", data={"album_id": "123", "csrf": "bad"})
        assert response.status_code == 403
