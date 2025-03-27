from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging
from typing import List

from ..models.schemas import ChatRequest, ChatResponse, ChatMessage
from ..core.db import get_db, ChatHistory
from ..services.llm_interaction import augment_and_ask

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/chat", response_model=ChatResponse)
async def handle_chat_message(
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    """
    Receives a user question, augments it, gets an answer from the LLM,
    stores the conversation, and returns the response.
    """
    logger.info(f"Received chat request for session '{request.session_id}': '{request.question}'")
    try:
        answer, sources = await augment_and_ask(db, request.question, request.session_id)
        return ChatResponse(answer=answer, sources=sources)
    except Exception as e:
        logger.error(f"Error handling chat request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")

@router.get("/chat_history", response_model=List[ChatMessage])
async def get_chat_history(
    session_id: str = "default",
    limit: int = 50, # Limit the amount of history returned
    db: Session = Depends(get_db)
):
    """
    Retrieves the recent chat history for a given session.
    """
    logger.info(f"Fetching chat history for session '{session_id}' (limit {limit})")
    try:
        history_records = db.query(ChatHistory)\
            .filter(ChatHistory.session_id == session_id)\
            .order_by(ChatHistory.timestamp.desc())\
            .limit(limit)\
            .all()
        history_records.reverse() # Return in chronological order

        # Convert ORM objects to Pydantic models
        return [ChatMessage(role=h.role, content=h.content, timestamp=h.timestamp) for h in history_records]

    except Exception as e:
        logger.error(f"Error fetching chat history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve chat history")