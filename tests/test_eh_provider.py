import json
import subprocess
from pathlib import Path

import pytest

from app.eh_provider import download_gallery
from app.provider import ProviderError


def test_download_keeps_credentials_outside_archive(tmp_path, monkeypatch):
    config = tmp_path / "eh-option.json"
    config.write_text(json.dumps({"extractor": {"exhentai": {
        "cookies": {"ipb_member_id": "private-member", "ipb_pass_hash": "private-secret"},
    }}}))
    output = tmp_path / "images"
    configs = []

    def run(command, **kwargs):
        path = Path(command[command.index("--config") + 1])
        configs.append(path)
        assert output not in path.parents
        options = json.loads(path.read_text())["extractor"]["exhentai"]
        assert options["cookies"]["ipb_pass_hash"] == "private-secret"
        assert options["cookies-update"] is False
        assert options["domain"] == "exhentai.org"
        assert options["limits-action"] == "stop"
        assert command[-1] == "https://exhentai.org/g/123/0123456789/"
        (Path(options["base-directory"]) / "0001.jpg").write_bytes(b"test-image")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("app.eh_provider.subprocess.run", run)
    download_gallery("exhentai", "https://exhentai.org/g/123/0123456789/", output, "gallery-dl", config)
    assert [p.name for p in output.iterdir()] == ["0001.jpg"]
    assert not configs[0].exists()


@pytest.mark.parametrize("stderr, message", [
    (b"HTTP 403 private-secret", "登录或访问校验失败"),
    (b"Image limit exceeded! private-secret", "下载额度"),
    (b"Unsupported URL private-secret", "不支持 E 站"),
])
def test_failed_download_redacts_credentials(tmp_path, monkeypatch, stderr, message):
    def run(command, **kwargs):
        kwargs["stderr"].write(stderr)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr("app.eh_provider.subprocess.run", run)
    with pytest.raises(ProviderError, match=message) as error:
        download_gallery(
            "ehentai", "https://e-hentai.org/g/123/0123456789/",
            tmp_path / "images", "gallery-dl", tmp_path / "missing.json",
        )
    assert "private-secret" not in str(error.value)


@pytest.mark.parametrize("filename", [None, "0001.jpg.part"])
def test_empty_or_incomplete_download_is_not_success(tmp_path, monkeypatch, filename):
    def run(command, **kwargs):
        if filename:
            (tmp_path / "images" / filename).write_bytes(b"partial")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("app.eh_provider.subprocess.run", run)
    with pytest.raises(ProviderError):
        download_gallery(
            "ehentai", "https://e-hentai.org/g/123/0123456789/",
            tmp_path / "images", "gallery-dl", tmp_path / "missing.json",
        )


def test_exhentai_requires_cookie(tmp_path):
    with pytest.raises(ProviderError, match="需要登录 Cookie"):
        download_gallery(
            "exhentai", "https://exhentai.org/g/123/0123456789/",
            tmp_path / "images", "gallery-dl", tmp_path / "missing.json",
        )


@pytest.mark.parametrize("cookies", [{}, {"ipb_member_id": "123"}, {
    "ipb_member_id": "", "ipb_pass_hash": "", "igneous": "",
}])
def test_exhentai_rejects_incomplete_cookie_before_component_fallback(tmp_path, cookies):
    config = tmp_path / "eh-option.json"
    config.write_text(json.dumps({"extractor": {"exhentai": {"cookies": cookies}}}))
    with pytest.raises(ProviderError, match="需要登录 Cookie"):
        download_gallery(
            "exhentai", "https://exhentai.org/g/123/0123456789/",
            tmp_path / "images", "gallery-dl", config,
        )


@pytest.mark.parametrize("domain, expires, valid", [
    (".exhentai.org", "0", True),
    ("exhentai.org", "0", True),
    (".e-hentai.org", "0", False),
    (".exhentai.org", "1", False),
])
def test_cookie_file_domain_and_expiry(tmp_path, monkeypatch, domain, expires, valid):
    cookies = tmp_path / "eh-cookies.txt"
    include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
    cookies.write_text(
        "# Netscape HTTP Cookie File\n"
        f"{domain}\t{include_subdomains}\t/\tTRUE\t{expires}\tipb_member_id\t123\n"
        f"{domain}\t{include_subdomains}\t/\tTRUE\t{expires}\tipb_pass_hash\tsecret\n"
    )
    config = tmp_path / "eh-option.json"
    config.write_text(json.dumps({"extractor": {"exhentai": {"cookies": str(cookies)}}}))

    def run(command, **kwargs):
        path = Path(command[command.index("--config") + 1])
        loaded = json.loads(path.read_text())["extractor"]["exhentai"]["cookies"]
        assert loaded == {"ipb_member_id": "123", "ipb_pass_hash": "secret"}
        (tmp_path / "images" / "0001.png").write_bytes(b"test-image")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("app.eh_provider.subprocess.run", run)
    if valid:
        download_gallery(
            "exhentai", "https://exhentai.org/g/123/0123456789/",
            tmp_path / "images", "gallery-dl", config,
        )
    else:
        with pytest.raises(ProviderError, match="需要登录 Cookie"):
            download_gallery(
                "exhentai", "https://exhentai.org/g/123/0123456789/",
                tmp_path / "images", "gallery-dl", config,
            )


def test_timeout_does_not_expose_command(tmp_path, monkeypatch):
    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("app.eh_provider.subprocess.run", run)
    with pytest.raises(ProviderError, match="下载超时") as error:
        download_gallery(
            "ehentai", "https://e-hentai.org/g/123/0123456789/",
            tmp_path / "images", "gallery-dl", tmp_path / "missing.json", 1,
        )
    assert "0123456789" not in str(error.value)
