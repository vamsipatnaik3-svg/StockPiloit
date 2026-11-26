
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    app_environment: str = "development"
    frontend_origin: str = "http://localhost:3000"
    upload_storage_dir: str = "/tmp/tavuno-uploads"
    max_upload_size_bytes: int = 20 * 1024 * 1024

    # Redis configuration
    redis_url: str = "redis://localhost:6379/0"
    login_rate_limit_account_ip: int = 5
    login_rate_limit_ip: int = 30
    login_rate_limit_window_seconds: int = 900

    # SMTP email configuration
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True
    smtp_timeout: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def session_cookie_secure(self) -> bool:
        """Enable Secure outside explicitly local/test environments."""
        return self.app_environment.strip().casefold() not in {
            "development", "dev", "local", "test",
        }


settings = Settings()
