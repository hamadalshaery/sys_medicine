"""
وظيفة هذا الملف: إدارة إعدادات البيئة (Environment Variables) باستخدام Pydantic Settings.
يتيح لك الوصول إلى الإعدادات السرية بسهولة وبأمان في أي مكان في المشروع.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    # App config
    APP_NAME: str = "Pharmacy - ابن النفيس"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    
    # Security
    SECRET_KEY: str = "fallback_secret_key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    
    # Admin defaults
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "Admin@123"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/pharmacy"
    
    # Telegram Bot
    BOT_TOKEN: str = ""
    WEBHOOK_URL: str = ""
    ADMINS: str = ""  # Comma separated list of admin IDs

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def admin_ids(self) -> List[int]:
        if not self.ADMINS:
            return []
        try:
            return [int(x.strip()) for x in self.ADMINS.split(",") if x.strip().isdigit()]
        except Exception:
            return []

settings = Settings()
