import sqlite3
import chromadb
from chromadb.utils import embedding_functions
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Table, MetaData
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.sql import func
import logging
from .config import settings

logger = logging.getLogger(__name__)

# --- SQLite Setup (using SQLAlchemy for structure, but could use raw sqlite3) ---
DATABASE_URL = f"sqlite:///{settings.SQLITE_DB_PATH}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}) # check_same_thread needed for SQLite with FastAPI
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Association table for many-to-many relationship between semantic terms
semantic_term_association = Table(
    'semantic_term_association', Base.metadata,
    Column('term_id', Integer, ForeignKey('semantic_terms.id'), primary_key=True),
    Column('related_term_id', Integer, ForeignKey('semantic_terms.id'), primary_key=True)
)

class SemanticTerm(Base):
    __tablename__ = "semantic_terms"
    id = Column(Integer, primary_key=True, index=True)
    term = Column(String, unique=True, index=True, nullable=False)
    explanation = Column(Text, nullable=False)
    related_terms = relationship(
        "SemanticTerm",
        secondary=semantic_term_association,
        primaryjoin=id == semantic_term_association.c.term_id,
        secondaryjoin=id == semantic_term_association.c.related_term_id,
        backref="related_to"
    )

class ChatHistory(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True, default="default") # Add session management later if needed
    role = Column(String, nullable=False) # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

def create_db_and_tables():
    logger.info(f"Creating database tables at {DATABASE_URL}")
    Base.metadata.create_all(bind=engine)

# --- ChromaDB Setup ---
# Use default SentenceTransformer embeddings, adjust if using OpenAI etc.
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=settings.EMBEDDING_MODEL_NAME
)

# If using OpenAI Embeddings (ensure OPENAI_API_KEY is set)
# openai_ef = embedding_functions.OpenAIEmbeddingFunction(
#                 api_key=settings.OPENAI_API_KEY,
#                 model_name="text-embedding-ada-002" # Or another OpenAI embedding model
#             )

chroma_client = chromadb.PersistentClient(path=settings.CHROMA_DB_PATH)

# Use the chosen embedding function
embedding_function_to_use = sentence_transformer_ef # or openai_ef

# Get or create the collection
# Adding metadata={"hnsw:space": "cosine"} is often recommended for sentence embeddings
try:
    knowledge_collection = chroma_client.get_or_create_collection(
        name="knowledge_base",
        embedding_function=embedding_function_to_use,
        metadata={"hnsw:space": "cosine"}
    )
    logger.info(f"ChromaDB collection 'knowledge_base' loaded/created at {settings.CHROMA_DB_PATH}")
except Exception as e:
     logger.error(f"Error initializing ChromaDB: {e}")
     # Handle error appropriately, maybe exit or fallback


def get_db():
    """ Dependency to get SQLAlchemy DB session """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()