import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env file variables
load_dotenv()

class Settings(BaseSettings):
    # Core
    SQLITE_DB_PATH: str = "./app/data/app_data.db"
    CHROMA_DB_PATH: str = "./app/data/chroma_data"
    LOG_LEVEL: str = "INFO"

    # LLM
    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "YOUR_DEFAULT_KEY_IF_NO_ENV") # Load from env
    LLM_MODEL_NAME: str = "gpt-4o-mini"

    # Embeddings
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"

    # Augmentation
    SEMANTIC_LOOKUP_DEPTH: int = 1
    CHAT_HISTORY_LENGTH: int = 5
    CHROMA_QUERY_COUNT: int = 3
    CHROMA_N_RESULTS: int = 5

    # Scraping
    REQUESTS_TIMEOUT: int = 10
    MAX_SCRAPE_DEPTH: int = 0
    USER_AGENT: str = "KnowledgeBot/1.0"

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = 'ignore' # Ignore extra fields from .env if any


settings = Settings()

# Create data directories if they don't exist
os.makedirs(os.path.dirname(settings.SQLITE_DB_PATH), exist_ok=True)
os.makedirs(settings.CHROMA_DB_PATH, exist_ok=True)