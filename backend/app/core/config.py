import os
from pydantic_settings import BaseSettings
from pathlib import Path

# Determine the base directory of the backend
# Assuming this file is in backend/app/core/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    PROJECT_NAME: str = "Web RAG Chatbot"
    API_V1_STR: str = "/api/v1"

    OPENAI_API_KEY: str

    # ChromaDB settings
    CHROMA_PERSIST_DIR: str = str(BASE_DIR / "data")
    CHROMA_COLLECTION_NAME: str = "web_content"
    CHROMA_CHAT_HISTORY_COLLECTION_NAME: str = "chat_history"

    # Embedding model
    EMBEDDING_MODEL_NAME: str = "paraphrase-multilingual-mpnet-base-v2" # Good multilingual model

    # LLM settings
    LLM_MODEL_NAME: str = "gpt-4o-mini-2024-07-18"
    LLM_MAX_HISTORY: int = 5 # Keep last 5 Q&A pairs

    # Scraping settings
    SCRAPER_USER_AGENT: str = "WebRAGBot/1.0 (+http://example.com/bot)" # Be a good citizen
    SCRAPER_REQUEST_TIMEOUT: int = 15 # seconds
    SCRAPER_MAX_DEPTH: int = 3 # Limit recursion depth
    SCRAPER_MAX_CONCURRENT_TASKS: int = 5 # Limit concurrent scraping fetches

    # Tesseract settings (adjust path if needed for your Docker setup)
    TESSERACT_CMD: str = "/usr/bin/tesseract" # Default path in many Linux distros

    class Config:
        # Load .env file relative to the backend directory
        env_file = BASE_DIR / ".env"
        env_file_encoding = 'utf-8'
        extra = 'ignore'

settings = Settings()

# Ensure data directory exists
Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)