# backend/app/background.py
import asyncio
from typing import Dict, Any, Optional, Callable # Added Callable
import logging
# Correctly import run_scrape_job
from .core.scraping.scraper import run_scrape_job

logger = logging.getLogger(__name__)

# In-memory storage for scrape job status (simple approach)
# Keys are the normalized starting URLs
scrape_jobs: Dict[str, Dict[str, Any]] = {}

# Lock for thread-safe access to scrape_jobs dict (though asyncio is single-threaded, good practice if extending)
_jobs_lock = asyncio.Lock()


# THIS FUNCTION STAYS HERE and updates the local scrape_jobs dict
def update_scrape_status(
    url: str,
    status: str,
    progress: int,
    total_pages: int,
    message: Optional[str] = None,
    error: Optional[str] = None
):
    """Updates the status of a scraping job. Called BY the scraper via callback."""
    global scrape_jobs
    # This might be called from the asyncio task. Accessing shared dict should be
    # generally safe in asyncio if not mutating structure heavily, but lock is safer.
    # However, acquiring async lock in sync function is not possible.
    # Let's assume asyncio safety for simple value updates. If issues arise,
    # use loop.call_soon_threadsafe if called from another thread, or restructure.
    if url in scrape_jobs:
        job = scrape_jobs[url]
        job['status'] = status
        job['progress'] = progress
        job['total_pages'] = total_pages
        if message:
            job['message'] = message
        if error:
            current_error = job.get('error')
            job['error'] = f"{current_error}\n{error}" if current_error else error
        # logger.debug(f"Status update for {url}: {status}, Progress: {progress}/{total_pages}")
    else:
        logger.warning(f"Attempted to update status for unknown job URL: {url}")


async def start_background_scraping(url: str) -> bool:
    """Initiates a scraping job in the background."""
    global scrape_jobs
    normalized_url = url # Assume already normalized by caller

    async with _jobs_lock:
        if normalized_url in scrape_jobs and scrape_jobs[normalized_url]['status'] in ['running', 'queued']:
            logger.warning(f"Scraping job for {normalized_url} is already running or queued.")
            return False # Indicate already running/queued

        # Initialize status
        scrape_jobs[normalized_url] = {
            "url": normalized_url,
            "status": "queued",
            "progress": 0,
            "total_pages": 1,
            "message": "Scraping job queued.",
            "task": None,
            "error": None
        }
        logger.info(f"Queued scraping job for: {normalized_url}")

    # Create and run the background task
    try:
        # --- PASS the local update_scrape_status function as the callback ---
        task = asyncio.create_task(run_scrape_job(normalized_url, update_scrape_status))

        async with _jobs_lock:
             # Store task reference if needed (e.g., for cancellation)
            scrape_jobs[normalized_url]['task'] = task
            # Optionally update status immediately? Let run_scrape_job handle first update.
        logger.info(f"Started background task for scraping: {normalized_url}")
        return True # Indicate job started successfully
    except Exception as e:
        logger.error(f"Failed to create background task for {normalized_url}: {e}", exc_info=True)
        async with _jobs_lock:
             # Ensure status is updated if task creation fails
            if normalized_url in scrape_jobs:
                 scrape_jobs[normalized_url]['status'] = 'failed'
                 scrape_jobs[normalized_url]['message'] = f"Failed to start task: {e}"
            else:
                 # Should not happen, but handle defensively
                 scrape_jobs[normalized_url] = {"status": "failed", "message": f"Failed to start task: {e}"}
        return False


async def get_scrape_status(url: str) -> Optional[Dict[str, Any]]:
    """Retrieves the status of a specific scraping job."""
    async with _jobs_lock:
        job_info = scrape_jobs.get(url)
        if job_info:
             # Return a copy to avoid external modification
            status_copy = job_info.copy()
            # Don't return the actual task object in the status response
            status_copy.pop('task', None)
            return status_copy
        return None