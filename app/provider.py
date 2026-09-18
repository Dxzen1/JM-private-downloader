from __future__ import annotations

import shutil
from pathlib import Path

import yaml


class ProviderError(RuntimeError):
    pass


def download_album(album_id: str, output_dir: Path, provider: str, option_path: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    if provider == "stub":
        album = output_dir / f"JM{album_id}"
        album.mkdir()
        (album / "001.txt").write_text("stub download\n", encoding="utf-8")
        return

    if not option_path.is_file():
        raise ProviderError(f"未找到 JM 配置文件：{option_path}")

    try:
        import jmcomic
    except ImportError as exc:
        raise ProviderError("jmcomic 组件未安装") from exc

    job_option = output_dir / ".job-option.yml"
    try:
        raw = yaml.safe_load(option_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ProviderError("JM 配置文件顶层必须是对象")
        dir_rule = raw.setdefault("dir_rule", {})
        if not isinstance(dir_rule, dict):
            raise ProviderError("JM 配置中的 dir_rule 必须是对象")
        dir_rule["base_dir"] = str(output_dir)
        job_option.write_text(
            yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        option = jmcomic.create_option_by_file(str(job_option))
        jmcomic.download_album(album_id, option)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"JM 下载失败：{exc}") from exc
    finally:
        job_option.unlink(missing_ok=True)


def make_zip(source_dir: Path, archive_base: Path) -> Path:
    archive_base.parent.mkdir(parents=True, exist_ok=True)
    result = shutil.make_archive(str(archive_base), "zip", root_dir=source_dir)
    return Path(result)
