from pathlib import Path
from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    provider: str = 'mock'
    public_base_url: HttpUrl = 'http://127.0.0.1:8000'
    data_dir: Path = Path(__file__).resolve().parent.parent / 'data'
    mock_delay_seconds: float = Field(default=2, ge=0, le=60)
    meshy_api_key: SecretStr = SecretStr('')
    meshy_ai_model: str = 'latest'
    fal_key: SecretStr = SecretStr('')
    fal_model_download_hosts: str = 'v3.fal.media,v3b.fal.media'
    hunyuan_api_key: SecretStr = SecretStr('')
    hunyuan_model: str = 'hy-3d-3.1'
    hunyuan_enable_pbr: bool = False
    hunyuan_face_count: int | None = Field(default=None, ge=3000, le=1500000)
    hunyuan_image_base_url: str = ''
    hunyuan_model_download_hosts: str = 'hunyuan-prod-1258344699.cos.ap-guangzhou.tencentcos.cn'
    poll_interval_seconds: float = Field(default=5, ge=0.05)
    task_timeout_seconds: float = Field(default=1800, ge=1)
    max_image_mb: int = Field(default=10, ge=1, le=20)
    max_model_mb: int = Field(default=64, ge=1, le=256)
    model_download_hosts: str = 'assets.meshy.ai'
    cors_origins: str = ''

    @property
    def base_url(self):
        return str(self.public_base_url).rstrip('/')

    @property
    def min_images(self):
        return 2 if self.provider == 'fal_tripo' else 1

    @property
    def max_images(self):
        return 6 if self.provider in ('hunyuan', 'mock') else 4

    @property
    def provider_ready(self):
        if self.provider == 'hunyuan': return bool(self.hunyuan_api_key.get_secret_value().strip())
        if self.provider == 'fal_tripo': return bool(self.fal_key.get_secret_value().strip())
        if self.provider == 'meshy': return bool(self.meshy_api_key.get_secret_value().strip())
        return self.provider == 'mock'

    @property
    def effective_image_mb(self):
        # 4 MiB raw fits within the documented 6 MiB base64 input limit after expansion.
        return min(self.max_image_mb, 4) if self.provider == 'hunyuan' else self.max_image_mb
