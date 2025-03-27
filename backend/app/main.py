from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging
import sys
import os

from .api import knowledge, chat
from .core.db import create_db_and_tables
from .core.config import settings

# --- Logging Configuration ---
# Remove default handlers
root_logger = logging.getLogger()
if root_logger.hasHandlers():
    root_logger.handlers.clear()

# Configure new handler
log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)

# Configure loggers used in the application
loggers_to_configure = [
    logging.getLogger(__name__),
    logging.getLogger("app.api"),
    logging.getLogger("app.core"),
    logging.getLogger("app.services"),
    # Add other loggers if necessary
]

# Configure root logger to capture logs from libraries if needed, but set its level higher
# to avoid excessive library logs unless explicitly desired.
root_logger.addHandler(stream_handler)
root_logger.setLevel(logging.WARNING) # Set root logger level higher

# Set specific levels for application loggers
for logger in loggers_to_configure:
    logger.addHandler(stream_handler) # Add the handler
    logger.setLevel(log_level)       # Set the desired level
    logger.propagate = False         # Prevent logs from propagating to the root logger

logger = logging.getLogger(__name__) # Get logger for this module

# --- FastAPI Application ---
app = FastAPI(title="Knowledge Chat App", version="0.1.0")

# --- Middleware ---
# Configure CORS (Cross-Origin Resource Sharing)
# Adjust origins as needed for your frontend setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all origins for simplicity, restrict in production!
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods
    allow_headers=["*"], # Allows all headers
)

# --- Database Initialization ---
@app.on_event("startup")
def on_startup():
    logger.info("Application starting up...")
    try:
        create_db_and_tables()
        logger.info("Database tables checked/created successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        # Depending on the severity, you might want to exit or handle differently
    logger.info("Checking required environment variables...")
    if settings.LLM_PROVIDER == "openai" and settings.OPENAI_API_KEY == "YOUR_DEFAULT_KEY_IF_NO_ENV":
         logger.warning("OPENAI_API_KEY is not set or using default. OpenAI features will likely fail.")
    logger.info(f"Using LLM Model: {settings.LLM_MODEL_NAME}")
    logger.info(f"Using Embedding Model: {settings.EMBEDDING_MODEL_NAME}")
    logger.info(f"SQLite DB Path: {settings.SQLITE_DB_PATH}")
    logger.info(f"ChromaDB Path: {settings.CHROMA_DB_PATH}")
    logger.info("Application startup complete.")


# --- API Routers ---
app.include_router(knowledge.router, prefix="/api", tags=["Knowledge"])
app.include_router(chat.router, prefix="/api", tags=["Chat"])

# --- Static Files (Frontend) ---
# Serve the 'frontend' directory from the root of the application
# Assumes the 'frontend' directory is one level up from the 'backend/app' directory
frontend_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend')
# Check if the directory exists before mounting
if os.path.isdir(frontend_dir):
     # Use absolute path for reliability
     abs_frontend_dir = os.path.abspath(frontend_dir)
     logger.info(f"Mounting static files from: {abs_frontend_dir}")
     app.mount("/", StaticFiles(directory=abs_frontend_dir, html=True), name="static")
else:
    logger.warning(f"Frontend directory not found at expected location: {frontend_dir}. Static files will not be served.")


# --- Basic Root Endpoint ---
@app.get("/health", tags=["Health"])
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}

# Add a default route if static files are not mounted at root or not found
# @app.get("/")
# async def read_root():
#     return {"message": "Welcome to the Knowledge Chat API. Frontend not found or not mounted at root."}