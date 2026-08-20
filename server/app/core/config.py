from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# server/.env resolved absolutely from this file, so it loads no matter which
# directory the server is started from (root, server/, or an IDE working dir).
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_name: str = "ReconAI API"
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 4000
    client_origin: str = "http://localhost:5173"

    # Credentials belong in server/.env (DATABASE_URL, JWT_SECRET_KEY), never
    # in this file — it is the one that gets committed. The defaults below are
    # deliberately non-secret so a misconfigured deploy fails loudly instead of
    # silently running on a checked-in password.
    database_url: str = "sqlite:///./server/data/reconai-dev.sqlite3"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = "change-this-secret-before-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720

    r2_endpoint_url: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "reconai-documents"

    email_host: str = ""
    email_port: int = 587
    email_host_user: str = ""
    email_host_password: str = ""
    email_use_tls: bool = True
    default_from_email: str = "no-reply@reconai.local"

    gstverify_api_key: str = ""
    gstverify_base_url: str = "https://api.gstverify.dubey.app/api/v1"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_vision_model: str = "qwen2.5vl:3b"
    # OCR tuning. 8192 fits a rendered page plus the reply and is what a 4 GB
    # GPU wants; raise only if a dense page fails on context size.
    ocr_num_ctx: int = 8192
    ocr_num_predict: int = 2048

    # extra="ignore" because server/.env is shared with the legacy stdlib
    # server (server/app.py), which reads its own PG*/SMTP_* keys from the same
    # file. Without this, pydantic-settings rejects those keys and the API
    # refuses to start. Drop back to the stricter default (which catches
    # misspelled keys) once that backend is retired.
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")


settings = Settings()
