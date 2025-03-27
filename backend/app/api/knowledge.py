from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import logging

from ..models.schemas import KnowledgeRequest, KnowledgeResponse
from ..services.scraping import scrape_website
from ..services.indexing import index_documents
from ..core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

async def background_scrape_and_index(url: str):
    """Background task to perform scraping and indexing."""
    try:
        logger.info(f"Starting background task: Scraping {url}")
        scraped_data = await scrape_website(str(url), max_depth=settings.MAX_SCRAPE_DEPTH)

        if not scraped_data:
            logger.warning(f"No content scraped from {url}.")
            return # Exit if nothing scraped

        logger.info(f"Scraping finished for {url}. Starting indexing...")
        await index_documents(scraped_data)
        logger.info(f"Background task finished: Indexing complete for {url}")

    except Exception as e:
        logger.error(f"Error in background task for {url}: {e}", exc_info=True)
        # Add notification or error tracking here if needed

@router.post("/add_knowledge", response_model=KnowledgeResponse, status_code=202) # 202 Accepted
async def add_knowledge_source(
    request: KnowledgeRequest,
    background_tasks: BackgroundTasks
):
    """
    Accepts a URL, acknowledges the request, and starts
    scraping and indexing in the background.
    """
    url_str = str(request.url)
    logger.info(f"Received request to add knowledge from: {url_str}")

    # Add the scraping/indexing job to background tasks
    background_tasks.add_task(background_scrape_and_index, url_str)

    return KnowledgeResponse(
        message="Knowledge source accepted. Scraping and indexing started in the background.",
        url=url_str
        # task_id can be added if you implement task tracking (e.g., with Celery)
    )

# Optional: Add endpoint to add Semantic Terms (requires auth in real app)
# from sqlalchemy.orm import Session
# from ..core.db import get_db
# from ..models.schemas import SemanticTermCreate, SemanticTermResponse
# from ..services.semantics import add_semantic_term

# @router.post("/semantics", response_model=SemanticTermResponse)
# def create_semantic_term(term_data: SemanticTermCreate, db: Session = Depends(get_db)):
#     try:
#         term = add_semantic_term(db, term_data)
#         # Need to map the ORM object to the Pydantic response model, including nested relations
#         # This requires careful handling or a helper function/library
#         # Basic example (might need adjustment based on relationship loading):
#         response_term = SemanticTermResponse.from_orm(term)
#         return response_term
#     except Exception as e:
#         logger.error(f"Failed to add semantic term '{term_data.term}': {e}")
#         raise HTTPException(status_code=500, detail=f"Failed to add semantic term: {e}")