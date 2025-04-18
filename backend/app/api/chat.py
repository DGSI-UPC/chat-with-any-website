from fastapi import APIRouter, HTTPException, Body
import logging
from typing import List, Optional
import uuid
import time

from ..models.schemas import (
    AskRequest, ChatResponse, ChatMessage, ChatHistoryResponse, ChatListItem
)
from ..core.vector_store import (
    query_documents, save_chat_turn, get_chat_history, delete_chat_history, get_all_chats
)
from ..core.llm import get_chat_response
from ..core.semantic import augment_query_with_semantics
from ..core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/ask", response_model=ChatResponse)
async def ask_question(request: AskRequest = Body(...)):
    """Handles user questions, performs RAG, interacts with LLM, and saves history."""
    chat_id = request.chat_id or str(uuid.uuid4()) # Create new chat ID if none provided
    user_query = request.query
    selected_sources = request.selected_sources

    if not user_query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    if not selected_sources:
         raise HTTPException(status_code=400, detail="At least one source URL must be selected.")


    logger.info(f"Received query for chat_id '{chat_id}' on sources {selected_sources}: '{user_query[:50]}...'")

    # 1. Retrieve relevant context chunks from VectorDB based on selected sources
    retrieved_chunks = query_documents(
        query_text=user_query,
        n_results=5, # Number of chunks to retrieve
        source_urls=selected_sources
    )
    logger.debug(f"Retrieved {len(retrieved_chunks)} chunks for query.")

    # 2. Retrieve chat history (limit to N turns for LLM context)
    # History is stored newest first, reverse it for chronological order in prompt if needed
    history_turns = get_chat_history(chat_id, limit=settings.LLM_MAX_HISTORY * 2)
    # history_turns are newest first: [ {role: assistant, ...}, {role: user, ...}, ...]

    # 3. Perform Semantic Augmentation based on query words
    semantic_augmentation = augment_query_with_semantics(user_query)
    logger.debug(f"Semantic Augmentation generated: {semantic_augmentation[:100]}...")

    # 4. Get response from LLM
    llm_answer, sources = get_chat_response(
        query=user_query,
        context_chunks=retrieved_chunks,
        semantic_augmentation=semantic_augmentation,
        chat_history=history_turns # Pass history (newest first)
    )

    # 5. Save the current turn (User Query + Assistant Response) to history
    timestamp = int(time.time())
    user_turn_data = {
        "chat_id": chat_id,
        "role": "user",
        "content": user_query,
        "timestamp": timestamp,
        "selected_sources": selected_sources # Store sources selected for this turn
    }
    assistant_turn_data = {
        "chat_id": chat_id,
        "role": "assistant",
        "content": llm_answer,
        "sources": sources, # Sources cited by the LLM
        "timestamp": timestamp + 1, # Ensure assistant is slightly after user
         "retrieved_context": [chunk['metadata'] for chunk in retrieved_chunks], # Store context used
         "semantic_augmentation": semantic_augmentation # Store augmentation used
    }

    save_chat_turn(chat_id, user_turn_data)
    save_chat_turn(chat_id, assistant_turn_data)
    # Optional: Trim older history beyond a larger limit if needed

    # 6. Return response
    assistant_message = ChatMessage(role="assistant", content=llm_answer, sources=sources)
    return ChatResponse(chat_id=chat_id, response=assistant_message)


@router.get("/chats", response_model=List[ChatListItem])
async def list_chats():
    """Lists all existing chats with basic information."""
    chats_data = get_all_chats() # Retrieves {chat_id, first_message, selected_sources}
    # Convert to ChatListItem Pydantic model
    return [ChatListItem(**chat_info) for chat_info in chats_data]

@router.get("/chats/{chat_id}", response_model=ChatHistoryResponse)
async def get_chat(chat_id: str):
    """Retrieves the full history for a specific chat."""
    history_turns = get_chat_history(chat_id, limit=100) # Get a larger history for display

    if not history_turns:
        raise HTTPException(status_code=404, detail="Chat not found.")

    # History is newest first from DB, reverse for display (oldest first)
    formatted_history = []
    selected_sources = [] # Find sources associated with the latest turn
    if history_turns:
        # Find the most recent turn with selected_sources info
        for turn in history_turns:
             if 'selected_sources' in turn:
                 selected_sources = turn.get('selected_sources', [])
                 break # Found the most recent associated sources

    for turn in reversed(history_turns):
        formatted_history.append(ChatMessage(
            role=turn.get('role'),
            content=turn.get('content'),
            sources=turn.get('sources') if turn.get('role') == 'assistant' else None
        ))

    return ChatHistoryResponse(
        chat_id=chat_id,
        history=formatted_history,
         selected_sources=selected_sources # Return sources associated with the chat
        )


@router.delete("/chats/{chat_id}", status_code=204) # 204 No Content
async def delete_chat(chat_id: str):
    """Deletes a specific chat history."""
    logger.info(f"Received request to delete chat: {chat_id}")
    success = delete_chat_history(chat_id)
    if not success:
        # Deletion might fail if chat doesn't exist or DB error
        # Check if chat existed first? Maybe not necessary, just try deleting.
        logger.warning(f"Failed to delete chat {chat_id} or chat did not exist.")
        # Don't raise 404, DELETE should be idempotent. Return 204 even if not found.
    return None # Return No Content