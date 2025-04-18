from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
import logging
from typing import List

from ..models.schemas import ScrapeRequest, ScrapeStatusResponse
from ..core.scraping.utils import normalize_url, is_valid_url
from ..background import start_background_scraping, get_scrape_status, scrape_jobs # Import background task functions
from ..core.vector_store import get_available_sources
from ..models.schemas import SourceItem


logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/scrape", status_code=202) # 202 Accepted
async def scrape_website(
    scrape_request: ScrapeRequest,
    # background_tasks: BackgroundTasks # FastAPI's built-in background tasks
):
    """
    Endpoint to initiate website scraping.
    Uses asyncio.create_task directly for better control over the task lifecycle.
    """
    url = str(scrape_request.url)
    if not is_valid_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL provided.")

    normalized = normalize_url(url)
    logger.info(f"Received scrape request for: {url} (Normalized: {normalized})")

    # Use the custom background task management
    success = await start_background_scraping(normalized)

    if success:
        return {"message": "Scraping job started.", "url": normalized}
    else:
         # Check if it failed because it's already running
        status = await get_scrape_status(normalized)
        if status and status.get('status') == 'running':
             raise HTTPException(status_code=409, detail=f"Scraping job for {normalized} is already in progress.")
        else:
             raise HTTPException(status_code=500, detail=f"Failed to start scraping job for {normalized}.")


@router.get("/scrape/status/{url:path}", response_model=ScrapeStatusResponse)
async def get_scraping_status(url: str):
    """
    Endpoint to check the status of a scraping job.
    The {url:path} parameter allows URLs containing slashes.
    """
    # The URL might come in encoded, FastAPI should handle decoding.
    # We need to normalize it the same way we did when starting the job.
    if not is_valid_url(f"http://{url}") and not is_valid_url(f"https://{url}"):
         # Basic check if it looks like a domain/path
         raise HTTPException(status_code=400, detail="Invalid URL format provided for status check.")

    # Try normalizing with common schemes
    normalized_http = normalize_url(f"http://{url}")
    normalized_https = normalize_url(f"https://{url}")

    # Check status for both possible normalizations
    status_http = await get_scrape_status(normalized_http)
    status_https = await get_scrape_status(normalized_https)

    status = status_https or status_http # Prefer https if both exist (unlikely)

    if status:
        # Remove the 'task' object before sending the response
        response_data = status.copy()
        response_data.pop('task', None)
        response_data.pop('error', None) # Don't expose raw errors directly maybe? Add to message if needed.
        if status.get('error') and 'message' in response_data:
             response_data['message'] += f" | Last Error: {status['error'][:100]}..." # Show snippet

        return ScrapeStatusResponse(**response_data)
    else:
        raise HTTPException(status_code=404, detail=f"No active or completed scraping job found for URL: {url}")


@router.get("/sources", response_model=List[SourceItem])
async def list_available_sources():
    """Lists all unique base URLs that have been successfully scraped and indexed."""
    sources = get_available_sources()
    return [SourceItem(url=src) for src in sources]