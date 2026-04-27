import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    # Telegram
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    
    # Gemini
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    
    # Google Cloud (for Speech-to-Text)
    google_cloud_credentials: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    
    # Website API
    website_base_url: str = os.getenv("WEBSITE_BASE_URL", "https://sas-academy.up.railway.app")
    website_api_key: str = os.getenv("WEBSITE_API_KEY", "sas-agent-b27bdbe6-2496-4a58-93cf-8d6b5a5e0de1")
    
    # Database
    database_url: str = os.getenv("DATABASE_URL", "")
    
    # App
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8080"))


config = Config()