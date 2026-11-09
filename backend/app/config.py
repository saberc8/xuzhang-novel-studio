from pathlib import Path
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NOVEL_", env_file=ROOT / ".env", extra="ignore"
    )
    data_dir: Path = ROOT / "data"
    api_url: str = "http://127.0.0.1:8010"
    database_url: str = "postgresql://localhost/xuzhang"
    database_schema: str = "public"
    max_upload_bytes: int = 30 * 1024 * 1024
    max_archive_bytes: int = 200 * 1024 * 1024
    api_token: str = ""
    public_url: str = "http://127.0.0.1:8010"
    production: bool = False
    registration_enabled: bool = True
    session_days: int = 14
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]

    @model_validator(mode="after")
    def validate_deployment(self):
        url = urlsplit(self.public_url)
        if url.scheme not in {"http", "https"} or not url.netloc or url.path not in {"", "/"} or url.query or url.fragment or url.username:
            raise ValueError("NOVEL_PUBLIC_URL 必须是网站的完整 HTTP(S) 域名，不含路径或账号")
        self.public_url = self.public_url.rstrip("/")
        if not 1 <= self.session_days <= 90:
            raise ValueError("NOVEL_SESSION_DAYS 必须为 1–90")
        if self.production and (url.scheme != "https" or "*" in self.allowed_hosts or "*" in self.allowed_origins):
            raise ValueError("生产环境必须配置 HTTPS 的 NOVEL_PUBLIC_URL，且不能允许任意 Host / Origin")
        return self
