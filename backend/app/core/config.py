from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    database_url: str = "sqlite:///./asariya_local.db"
    storage_root: str = "../storage"
    watermark_timeout_seconds: int = 180
    watermark_text: str = "AsariyaForum.com"
    tesseract_exe: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    tessdata_dir: str = "./tessdata"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    max_upload_mb: int = 100
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
BASE_DIR = Path(__file__).resolve().parents[2]
def storage_path() -> Path:
    p = Path(settings.storage_root)
    return p.resolve() if p.is_absolute() else (BASE_DIR / p).resolve()
