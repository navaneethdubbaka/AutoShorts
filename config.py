import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # API Keys
    elevenlabs_api_key: str = Field(default="", validation_alias="ELEVENLABS_API_KEY")
    elevenlabs_api_keys: str = Field(default="", validation_alias="ELEVENLABS_API_KEYS")
    elevenlabs_model_id: str = Field(default="eleven_flash_v2_5", validation_alias="ELEVENLABS_MODEL_ID")
    pexels_api_key: str = Field(default="", validation_alias="PEXELS_API_KEY")
    pixabay_api_key: str = Field(default="", validation_alias="PIXABAY_API_KEY")
    api_key: str = Field(default="", validation_alias="API_KEY")  # Shared secret for API security

    # Paths
    base_dir: Path = Path(__file__).resolve().parent
    output_dir: Path = Field(default=Path("output"), validation_alias="OUTPUT_DIR")
    temp_dir: Path = Field(default=Path("temp"), validation_alias="TEMP_DIR")
    fonts_dir: Path = Field(default=Path("fonts"), validation_alias="FONTS_DIR")
    music_dir: Path = Field(default=Path("music"), validation_alias="MUSIC_DIR")
    logos_dir: Path = Field(default=Path("logos"), validation_alias="LOGOS_DIR")
    assets_dir: Path = Field(default=Path("assets"), validation_alias="ASSETS_DIR")

    # App Config
    host: str = Field(default="0.0.0.0", validation_alias="HOST")
    port: int = Field(default=8000, validation_alias="PORT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def create_dirs(self):
        """Ensure that all required directory paths exist."""
        for path_attr in ["output_dir", "temp_dir", "fonts_dir", "music_dir", "logos_dir", "assets_dir"]:
            path: Path = getattr(self, path_attr)
            if not path.is_absolute():
                path = self.base_dir / path
            path.mkdir(parents=True, exist_ok=True)

settings = Settings()
# Initialize directories
settings.create_dirs()
