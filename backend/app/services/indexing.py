from langchain.text_splitter import RecursiveCharacterTextSplitter
import logging
from typing import List, Tuple, Dict, Any
import uuid

from ..core.db import knowledge_collection # Import the initialized collection
from ..core.config import settings

logger = logging.getLogger(__name__)

# Configure text splitter (adjust parameters as needed)
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    length_function=len,
    is_separator_regex=False,
)

def split_text(text: str, source_url: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Splits text into chunks and adds metadata."""
    chunks = text_splitter.split_text(text)
    documents = []
    for i, chunk in enumerate(chunks):
        metadata = {
            "source": source_url,
            "chunk_index": i,
            "content_type": "text" # Could add 'pdf' based on scraping result
        }
        documents.append((chunk, metadata))
    return documents

async def index_documents(scraped_data: List[Tuple[str, str]]):
    """Splits text from scraped data and indexes it into ChromaDB."""
    all_chunks = []
    all_metadatas = []
    all_ids = []

    logger.info(f"Starting indexing process for {len(scraped_data)} sources.")

    for url, text in scraped_data:
        if not text or not text.strip():
            logger.warning(f"Skipping empty content from {url}")
            continue

        logger.info(f"Splitting text from {url}...")
        documents = split_text(text, url)
        logger.info(f"Generated {len(documents)} chunks from {url}.")

        for chunk_text, metadata in documents:
            # Generate a unique ID for each chunk
            # Using URL + chunk index might be more deterministic if needed for updates
            chunk_id = str(uuid.uuid4())
            all_chunks.append(chunk_text)
            all_metadatas.append(metadata)
            all_ids.append(chunk_id)

    if not all_chunks:
        logger.warning("No valid chunks generated for indexing.")
        return

    # Index in batches if necessary (ChromaDB handles batching well)
    try:
        logger.info(f"Adding {len(all_chunks)} chunks to ChromaDB...")
        knowledge_collection.add(
            documents=all_chunks,
            metadatas=all_metadatas,
            ids=all_ids
        )
        logger.info(f"Successfully added {len(all_chunks)} chunks to ChromaDB.")
    except Exception as e:
        logger.error(f"Error adding documents to ChromaDB: {e}")
        # Consider retry logic or more specific error handling