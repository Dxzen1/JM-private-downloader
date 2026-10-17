from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

SOURCE_LABELS = {"jm": "JM", "ehentai": "E-Hentai", "exhentai": "ExHentai"}
SOURCE_PREFIXES = {"jm": "JM", "ehentai": "EH", "exhentai": "EX"}
GALLERY_HOSTS = {"e-hentai.org": "ehentai", "exhentai.org": "exhentai"}


@dataclass(frozen=True)
class Target:
    source: str
    album_id: str
    source_url: str = ""


def normalize_target(source: str, value: str, max_id_length: int = 12) -> Target:
    if source not in SOURCE_LABELS:
        raise ValueError("请选择有效的下载来源")
    value = value.strip()
    if source == "jm":
        normalized = value.upper().removeprefix("JM")
        if not re.fullmatch(r"[0-9]+", normalized) or not 1 <= len(normalized) <= max_id_length:
            raise ValueError("请输入有效的 JM 漫画数字 ID")
        return Target(source, normalized)

    try:
        url = urlsplit(value)
    except ValueError:
        raise ValueError("请输入有效的 E 站画廊链接") from None
    # Exact authorities exclude userinfo, arbitrary ports and lookalike domains.
    host = url.netloc.lower()
    match = re.fullmatch(r"/g/([0-9]{1,12})/([0-9a-fA-F]{10})/?", url.path)
    if url.scheme not in {"http", "https"} or host not in GALLERY_HOSTS or not match:
        raise ValueError("请粘贴 E-Hentai 或 ExHentai 的完整画廊链接：https://域名/g/编号/令牌/")
    gid, token = match.groups()
    return Target(GALLERY_HOSTS[host], gid, f"https://{host}/g/{gid}/{token.lower()}/")
