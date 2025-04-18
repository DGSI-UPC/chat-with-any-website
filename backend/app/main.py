from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pathlib import Path
import logging
import logging.config

from .api import scrape, chat # Import API routers
from .core.config import settings

# --- Logging Configuration ---
# Basic logging setup (customize as needed, e.g., using a dict config)
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger("uvicorn.access").setLevel(logging.WARNING) # Quieter access logs
logging.getLogger("chromadb").setLevel(logging.WARNING) # Quieter ChromaDB logs unless debugging
logging.getLogger("httpx").setLevel(logging.WARNING) # Quieter httpx logs
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)

# --- Determine Frontend Directory Path ---
# This assumes main.py is in backend/app/
BACKEND_DIR = Path(__file__).resolve().parent.parent
# The frontend directory is expected to be sibling to the backend directory
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
STATIC_DIR = FRONTEND_DIR # Serve static files directly from frontend dir

if not FRONTEND_DIR.exists() or not FRONTEND_DIR.is_dir():
     logger.error(f"Frontend directory not found at expected location: {FRONTEND_DIR}")
     # Depending on deployment, you might want to exit or handle this differently
     # For Docker, this should be copied correctly.

# --- FastAPI App Initialization ---
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# --- API Routers ---
app.include_router(scrape.router, prefix=settings.API_V1_STR, tags=["Scraping"])
app.include_router(chat.router, prefix=settings.API_V1_STR, tags=["Chat"])

# --- Static Files Mounting ---
# Serve static files (CSS, JS) from the frontend directory
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    logger.info(f"Mounted static files from: {STATIC_DIR}")

    # --- Serve index.html ---
    @app.get("/", response_class=HTMLResponse)
    async def serve_index(request: Request):
        index_path = FRONTEND_DIR / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        else:
             logger.error(f"index.html not found in {FRONTEND_DIR}")
             raise HTTPException(status_code=404, detail="index.html not found")

    # Optional: Serve other static assets like CSS/JS directly if needed,
    # but mounting /static should cover files in css/ and js/ subdirs correctly.
    # Example: Mount CSS directory
    # css_dir = FRONTEND_DIR / "css"
    # if css_dir.exists():
    #     app.mount("/css", StaticFiles(directory=css_dir), name="css")

    # Example: Mount JS directory
    # js_dir = FRONTEND_DIR / "js"
    # if js_dir.exists():
    #     app.mount("/js", StaticFiles(directory=js_dir), name="js")

else:
     logger.warning(f"Frontend directory {FRONTEND_DIR} not found. Static files and index.html will not be served.")
     @app.get("/")
     async def root():
         return {"message": f"{settings.PROJECT_NAME} API is running, but frontend files are missing."}


# --- Simple Health Check ---
@app.get("/health", tags=["Health"])
async def health_check():
    # Add checks for DB, LLM connectivity if needed
    return {"status": "ok"}

# --- Application Startup Event (Optional) ---
@app.on_event("startup")
async def startup_event():
    logger.info("Application startup...")
    # Initialize connections or resources if needed (ChromaDB client is initialized globally for simplicity here)
    from .core import vector_store # Trigger VDB init log messages
    if not vector_store.client or not vector_store.collection or not vector_store.chat_history_collection:
         logger.critical("Vector Store Initialization failed. Application might not function correctly.")
    if not settings.OPENAI_API_KEY:
         logger.warning("OPENAI_API_KEY is not set in the environment. LLM features will be disabled.")


# --- Application Shutdown Event (Optional) ---
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutdown...")
    # Clean up resources if needed

# To run locally (for development): uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000