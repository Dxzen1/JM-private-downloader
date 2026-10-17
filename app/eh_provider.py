from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path
from urllib.parse import urlsplit

from .provider import ProviderError


def download_gallery(
    source: str, source_url: str, output_dir: Path, provider: str,
    option_path: Path, timeout_seconds: int = 7200,
) -> None:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    if provider == "stub":
        (output_dir / "001.txt").write_text("stub download\n", encoding="utf-8")
        return

    options = {}
    if option_path.exists():
        try:
            raw = json.loads(option_path.read_text(encoding="utf-8"))
            options = raw.get("extractor", {}).get("exhentai", {})
            if not isinstance(options, dict):
                raise ValueError
        except (OSError, ValueError, AttributeError):
            raise ProviderError("E 站配置读取失败，请检查 eh-option.json 的 JSON 格式和文件权限") from None

    # Only import connection/authentication options. Paths and side effects belong to the portal.
    options = {key: options[key] for key in ("cookies", "proxy", "user-agent", "original") if key in options}
    cookies = options.get("cookies")
    if cookies is not None:
        if isinstance(cookies, str):
            if not Path(cookies).is_absolute() or not Path(cookies).is_file():
                raise ProviderError("E 站 Cookie 文件不存在，请在配置中填写容器内的绝对路径")
            jar = MozillaCookieJar(cookies)
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
            except (OSError, LoadError):
                raise ProviderError("E 站 Cookie 文件读取失败，请检查 cookies.txt 格式和读取权限") from None
            domain = urlsplit(source_url).netloc
            cookies = {
                c.name: c.value for c in jar
                if c.domain.lstrip(".") == domain and (not c.expires or not c.is_expired())
            }
        elif not isinstance(cookies, dict):
            raise ProviderError("E 站 cookies 必须为 Cookie 对象或 cookies.txt 文件的绝对路径")
        options["cookies"] = cookies
    if source == "exhentai" or cookies is not None:
        if not cookies or not all(
            isinstance(cookies.get(name), str) and cookies[name]
            for name in ("ipb_member_id", "ipb_pass_hash")
        ):
            raise ProviderError("E 站需要登录 Cookie：请配置目标域名的有效 ipb_member_id 和 ipb_pass_hash")
    options = {
        "original": False,
        **options,
        "base-directory": str(output_dir),
        "directory": [],
        "filename": "{num:>04}.{extension}",
        "domain": urlsplit(source_url).netloc,
        "source": "gallery",
        "cookies-update": False,
        "gp": "stop",
        "limits-action": "stop",
        "fallback-retries": 2,
        "retries": 2,
        "timeout": 30,
    }
    config = {"extractor": {"exhentai": options}, "cache": {"file": ":memory:"}}

    # Keep credentials outside the directory that will be archived.
    with tempfile.TemporaryDirectory(prefix="eh-download-") as temp_dir:
        config_path = Path(temp_dir) / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        config_path.chmod(0o600)
        command = [
            sys.executable, "-m", "gallery_dl", "--config-ignore", "--config", str(config_path),
            "--no-input", "--no-colors", source_url,
        ]
        with tempfile.TemporaryFile() as errors:
            try:
                result = subprocess.run(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                    cwd=output_dir, timeout=timeout_seconds, check=False,
                )
            except subprocess.TimeoutExpired:
                raise ProviderError("E 站下载超时，可稍后重试或调整 EH_TIMEOUT_SECONDS") from None
            except OSError:
                raise ProviderError("E 站下载组件无法启动，请检查服务器运行环境") from None
            if result.returncode:
                errors.seek(max(0, errors.tell() - 8192))
                stderr = errors.read().decode("utf-8", errors="replace").lower()
                # Component output can contain URLs or credentials; expose only a diagnostic category.
                if "unsupported url" in stderr or "no module named" in stderr:
                    message = "gallery-dl 未安装或不支持 E 站，请安装官方 PyPI 发行版并重建容器"
                elif any(word in stderr for word in ("429", "509", "image limit", "quota")):
                    message = "E 站下载额度或请求频率受限，请等待额度恢复后重试"
                elif any(word in stderr for word in (
                    "403", "401", "login", "cookie", "panda", "challenge", "authorization", "authentication",
                )):
                    message = "E 站登录或访问校验失败，请更新 Cookie 并确认账号和服务器能访问该画廊"
                elif any(word in stderr for word in ("404", "not found", "notfound", "unavailable")):
                    message = "E 站画廊不存在、已删除或当前账号没有访问权限"
                else:
                    message = "E 站下载失败，请检查画廊访问权限、Cookie、网络和下载额度后重试"
                raise ProviderError(message)

    images = [p for p in output_dir.rglob("*") if p.is_file()]
    if any(p.suffix == ".part" for p in images):
        raise ProviderError("E 站图片未完整下载，请重试")
    if not any(
        p.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".jxl"}
        and p.stat().st_size > 0 for p in images
    ):
        raise ProviderError("E 站未下载到图片，请检查 Cookie、画廊权限及下载额度")
