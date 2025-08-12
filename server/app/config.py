from pydantic import BaseModel
import os

class Settings(BaseModel):
    app_name: str = "kbxy-monsters-pro"
    db_path: str = os.getenv("KBXY_DB_PATH", "kbxy-dev.db")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

settings = Settings()
