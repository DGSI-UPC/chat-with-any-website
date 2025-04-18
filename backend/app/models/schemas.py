from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict, Any

class ScrapeRequest(BaseModel):
    url: HttpUrl

class ScrapeStatusResponse(BaseModel):
    url: str
    status: str # e.g., 'queued', 'running', 'completed', 'failed'
    progress: int # e.g., number of pages indexed
    total_pages: Optional[int] = None # Optional: If total can be estimated
    message: Optional[str] = None

class AskRequest(BaseModel):
    chat_id: Optional[str] = None # If None, a new chat is created
    query: str
    selected_sources: List[str] # List of base URLs scraped

class ChatMessage(BaseModel):
    role: str # 'user' or 'assistant'
    content: str
    sources: Optional[List[str]] = None # URLs used for assistant response

class ChatResponse(BaseModel):
    chat_id: str
    response: ChatMessage

class ChatHistoryResponse(BaseModel):
    chat_id: str
    history: List[ChatMessage]
    selected_sources: List[str] # Sources associated with this chat

class ChatListItem(BaseModel):
    chat_id: str
    first_message: Optional[str] = None # Preview of the chat
    selected_sources: List[str]

class SourceItem(BaseModel):
    url: str # Base URL that was scraped