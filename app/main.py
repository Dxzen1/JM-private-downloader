from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import Settings
from .db import Database
from .worker import worker_loop

BASE_DIR = Path(__file__).resolve().parent
settings = Settings.from_env()
settings.validate()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.download_dir.mkdir(parents=True, exist_ok=True)
db = Database(settings.data_dir / "portal.sqlite3")
db.initialize()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def require_auth(request: Request) -> None:
    if not authenticated(request):
        raise HTTPException(status_code=401, detail="请先登录")


def verify_csrf(request: Request, token: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="请求校验失败，请刷新页面重试")


def public_task(task: dict) -> dict:
    return {
        "id": task["id"],
        "album_id": task["album_id"],
        "status": task["status"],
        "message": task["message"],
        "zip_size": task["zip_size"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(worker_loop(db, settings, stop))
    yield
    stop.set()
    await task


app = FastAPI(title="JM 私人下载站", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="jm_portal_session",
    max_age=60 * 60 * 24 * 7,
    same_site="strict",
    https_only=settings.secure_cookie,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    if request.url.path != "/static/style.css":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    if authenticated(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error},
    )


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user_ok = secrets.compare_digest(username, settings.admin_username)
    password_ok = secrets.compare_digest(password, settings.admin_password)
    if not (user_ok and password_ok):
        return RedirectResponse("/login?error=用户名或密码错误", status_code=303)
    request.session.clear()
    request.session["authenticated"] = True
    csrf_token(request)
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    require_auth(request)
    verify_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    if not authenticated(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"tasks": db.list_tasks(), "csrf": csrf_token(request)},
    )


@app.post("/tasks")
def create_task(request: Request, album_id: str = Form(...), csrf: str = Form(...)):
    require_auth(request)
    verify_csrf(request, csrf)
    normalized = album_id.strip().upper()
    if normalized.startswith("JM"):
        normalized = normalized[2:]
    if not normalized.isdigit() or not (1 <= len(normalized) <= settings.max_album_id_length):
        return RedirectResponse("/?error=" + quote("请输入有效的漫画数字 ID"), status_code=303)
    existing = next(
        (
            item
            for item in db.list_tasks()
            if item["album_id"] == normalized and item["status"] in {"queued", "running"}
        ),
        None,
    )
    if existing is None:
        db.create_task(normalized)
    return RedirectResponse("/", status_code=303)


@app.get("/api/tasks")
def api_tasks(request: Request):
    require_auth(request)
    return JSONResponse([public_task(task) for task in db.list_tasks()])


@app.get("/tasks/{task_id}/download")
def download(request: Request, task_id: str):
    require_auth(request)
    task = db.get_task(task_id)
    if not task or task["status"] != "completed" or not task["zip_path"]:
        raise HTTPException(status_code=404, detail="文件不存在或尚未完成")
    path = Path(task["zip_path"]).resolve()
    ready_dir = (settings.download_dir / "ready").resolve()
    if ready_dir not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"JM{task['album_id']}.zip",
    )


@app.post("/tasks/{task_id}/retry")
def retry(request: Request, task_id: str, csrf: str = Form(...)):
    require_auth(request)
    verify_csrf(request, csrf)
    if not db.retry_task(task_id):
        raise HTTPException(status_code=409, detail="只有失败任务可以重试")
    return RedirectResponse("/", status_code=303)


@app.post("/tasks/{task_id}/delete")
def delete(request: Request, task_id: str, csrf: str = Form(...)):
    require_auth(request)
    verify_csrf(request, csrf)
    task = db.delete_task(task_id)
    if not task:
        raise HTTPException(status_code=409, detail="任务不存在或正在运行")
    if task.get("zip_path"):
        Path(task["zip_path"]).unlink(missing_ok=True)
    return RedirectResponse("/", status_code=303)
