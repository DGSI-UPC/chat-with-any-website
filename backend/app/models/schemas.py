from pydantic import BaseModel, HttpUrl
from typing import List, Optional
from datetime import datetime

class KnowledgeRequest(BaseModel):
    url: HttpUrl

class KnowledgeResponse(BaseModel):
    message: str
    url: str
    task_id: Optional[str] = None # For background task tracking

class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = "default" # Keep it simple for now

class ChatMessage(BaseModel):
    role: str # 'user' or 'assistant'
    content: str
    timestamp: Optional[datetime] = None

class ChatResponse(BaseModel):
    answer: str
    sources: List[str] = [] # URLs of sources used

class SemanticTermCreate(BaseModel):
    term: str
    explanation: str
    related_term_ids: List[int] = []

class SemanticTermResponse(BaseModel):
    id: int
    term: str
    explanation: str
    related_terms: List['SemanticTermResponse'] = [] # Recursive definition

    class Config:
        from_attributes = True

# Required for recursive model definition
SemanticTermResponse.model_rebuild()