from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    download_dir: Path
    admin_username: str
    admin_password: str
    session_secret: str
    secure_cookie: bool
    provider: str
    jm_option_path: Path
    max_storage_gb: float
    retention_hours: int
    max_album_id_length: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "/app/data")),
            download_dir=Path(os.getenv("DOWNLOAD_DIR", "/app/downloads")),
            admin_username=os.getenv("ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("ADMIN_PASSWORD", ""),
            session_secret=os.getenv("SESSION_SECRET", ""),
            secure_cookie=_bool("SECURE_COOKIE", True),
            provider=os.getenv("JM_PROVIDER", "jmcomic"),
            jm_option_path=Path(os.getenv("JM_OPTION_PATH", "/run/secrets/jm-option.yml")),
            max_storage_gb=float(os.getenv("MAX_STORAGE_GB", "20")),
            retention_hours=int(os.getenv("RETENTION_HOURS", "168")),
            max_album_id_length=int(os.getenv("MAX_ALBUM_ID_LENGTH", "12")),
        )

    def validate(self) -> None:
        if not self.admin_password:
            raise RuntimeError("ADMIN_PASSWORD is required")
        if len(self.admin_password) < 12:
            raise RuntimeError("ADMIN_PASSWORD must be at least 12 characters")
        if len(self.session_secret) < 32:
            raise RuntimeError("SESSION_SECRET must be at least 32 characters")
        if self.provider not in {"jmcomic", "stub"}:
            raise RuntimeError("JM_PROVIDER must be jmcomic or stub")

