from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = BACKEND_DIR / ".env"

_settings: "Settings | None" = None
_env_mtime: float | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE if ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bailian_api_key: str = ""
    bailian_asr_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    bailian_asr_model: str = "qwen3-asr-flash"
    bailian_tts_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    bailian_tts_model: str = "qwen3-tts-flash"
    bailian_tts_voice: str = "Cherry"
    bailian_tts_language: str = "Chinese"

    deepseek_api_key: str = ""
    deepseek_url: str = "https://api.deepseek.com/chat/completions"
    deepseek_model: str = "deepseek-v4-flash"

    amap_api_key: str = ""
    amap_geocode_url: str = "https://restapi.amap.com/v3/geocode/geo"
    amap_around_url: str = "https://restapi.amap.com/v3/place/around"

    backend_host: str = "127.0.0.1"
    backend_port: int = 8003
    cors_origins: str = "http://localhost:5175,http://127.0.0.1:5175"

    audio_storage_dir: str = "storage/audio"
    audio_ttl_hours: int = 24
    max_audio_bytes: int = 5 * 1024 * 1024
    min_audio_seconds: float = 1.0
    max_audio_seconds: float = 60.0
    ffprobe_timeout_seconds: float = 10.0
    ffprobe_path: str = ""
    asr_timeout_seconds: float = 20.0
    max_asr_base64_bytes: int = 10 * 1024 * 1024
    extract_timeout_seconds: float = 15.0
    extract_max_tokens: int = 1024

    @field_validator(
        "bailian_api_key",
        "deepseek_api_key",
        "amap_api_key",
        mode="before",
    )
    @classmethod
    def strip_secret(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip().strip('"').strip("'")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


def get_settings() -> Settings:
    global _settings, _env_mtime
    mtime = ENV_FILE.stat().st_mtime if ENV_FILE.is_file() else None
    if _settings is None or mtime != _env_mtime:
        _settings = Settings()
        _env_mtime = mtime
    return _settings
