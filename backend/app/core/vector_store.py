import chromadb
from chromadb.utils import embedding_functions
from .config import settings
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Initialize ChromaDB client (singleton pattern might be better for prod)
try:
    client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    logger.info(f"ChromaDB client initialized. Persistence path: {settings.CHROMA_PERSIST_DIR}")
except Exception as e:
    logger.error(f"Failed to initialize ChromaDB client: {e}", exc_info=True)
    client = None # Handle inability to connect

# Initialize Sentence Transformer embedding function
try:
    embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=settings.EMBEDDING_MODEL_NAME
    )
    logger.info(f"Sentence Transformer embedding function loaded: {settings.EMBEDDING_MODEL_NAME}")
except Exception as e:
    logger.error(f"Failed to load Sentence Transformer model: {e}", exc_info=True)
    embedding_func = None # Handle model loading failure

# Get or create the main content collection
try:
    collection = client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION_NAME,
        embedding_function=embedding_func,
        metadata={"hnsw:space": "cosine"} # Use cosine distance
    )
    logger.info(f"ChromaDB collection '{settings.CHROMA_COLLECTION_NAME}' ready.")
except Exception as e:
    logger.error(f"Failed to get/create ChromaDB collection '{settings.CHROMA_COLLECTION_NAME}': {e}", exc_info=True)
    collection = None

# Get or create the chat history collection
try:
    chat_history_collection = client.get_or_create_collection(
        name=settings.CHROMA_CHAT_HISTORY_COLLECTION_NAME
        # No embedding function needed if we don't vectorize history content itself
    )
    logger.info(f"ChromaDB collection '{settings.CHROMA_CHAT_HISTORY_COLLECTION_NAME}' ready.")
except Exception as e:
    logger.error(f"Failed to get/create ChromaDB collection '{settings.CHROMA_CHAT_HISTORY_COLLECTION_NAME}': {e}", exc_info=True)
    chat_history_collection = None


def add_documents(documents: List[str], metadatas: List[dict], ids: List[str]):
    """Adds documents to the ChromaDB collection."""
    if not collection or not embedding_func:
        logger.error("ChromaDB collection or embedding function not available.")
        return False
    try:
        # Batch add for efficiency
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        logger.info(f"Added {len(documents)} documents to collection '{settings.CHROMA_COLLECTION_NAME}'.")
        return True
    except Exception as e:
        logger.error(f"Error adding documents to ChromaDB: {e}", exc_info=True)
        return False

def query_documents(query_text: str, n_results: int = 5, source_urls: Optional[List[str]] = None) -> List[Dict]:
    """Queries the collection for relevant documents."""
    if not collection or not embedding_func:
        logger.error("ChromaDB collection or embedding function not available for querying.")
        return []
    try:
        where_clause = None
        if source_urls:
            # Build OR condition for multiple source URLs
            if len(source_urls) == 1:
                 where_clause = {"source_url_base": source_urls[0]}
            else:
                where_clause = {"$or": [{"source_url_base": url} for url in source_urls]}

        results = collection.query(
            query_texts=[query_text],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
             where=where_clause
        )
        # Flatten results as we only query one text at a time
        retrieved_docs = []
        if results and results.get('ids') and results['ids'][0]:
            for i, doc_id in enumerate(results['ids'][0]):
                 retrieved_docs.append({
                     "id": doc_id,
                     "document": results['documents'][0][i],
                     "metadata": results['metadatas'][0][i],
                     "distance": results['distances'][0][i]
                 })
            # Optional: Add relevance filtering based on distance threshold if needed
            # retrieved_docs = [doc for doc in retrieved_docs if doc['distance'] < SOME_THRESHOLD]
        logger.info(f"Query '{query_text[:50]}...' returned {len(retrieved_docs)} results.")
        return retrieved_docs
    except Exception as e:
        logger.error(f"Error querying ChromaDB: {e}", exc_info=True)
        return []

def get_available_sources() -> List[str]:
    """Gets a list of unique base source URLs from the metadata."""
    if not collection:
        logger.error("ChromaDB collection not available.")
        return []
    try:
        # This can be inefficient on large collections. Consider maintaining a separate list/set.
        # ChromaDB doesn't have a direct distinct operation on metadata.
        # We fetch a large number of items and extract unique values.
        # A better approach might be needed for very large datasets.
        results = collection.get(include=['metadatas'], limit=10000) # Adjust limit as needed
        unique_sources = set()
        if results and results.get('metadatas'):
            for meta in results['metadatas']:
                if 'source_url_base' in meta:
                    unique_sources.add(meta['source_url_base'])
        return sorted(list(unique_sources))
    except Exception as e:
        logger.error(f"Error retrieving sources from ChromaDB: {e}", exc_info=True)
        return []

# --- Chat History Functions ---

def save_chat_turn(chat_id: str, turn_data: Dict):
    """Saves a single turn (user query + assistant response) to the history collection."""
    if not chat_history_collection:
        logger.error("Chat history collection not available.")
        return False
    try:
        # We store the turn data directly in the metadata, using a unique ID per turn.
        # The document itself can be empty or contain a summary if needed for search.
        turn_id = f"{chat_id}_{turn_data['timestamp']}" # Simple timestamp-based ID
        chat_history_collection.add(
            ids=[turn_id],
            metadatas=[{"chat_id": chat_id, **turn_data}],
            documents=[""] # Document content not strictly needed here
        )
        return True
    except Exception as e:
        logger.error(f"Error saving chat turn to ChromaDB: {e}", exc_info=True)
        return False

def get_chat_history(chat_id: str, limit: int = settings.LLM_MAX_HISTORY * 2) -> List[Dict]:
    """Retrieves the most recent turns for a given chat ID."""
    if not chat_history_collection:
        logger.error("Chat history collection not available.")
        return []
    try:
        results = chat_history_collection.get(
            where={"chat_id": chat_id},
            include=["metadatas"]
            # No need to sort by timestamp here, Chroma doesn't guarantee order
            # We'll sort afterwards
        )
        if results and results.get('metadatas'):
            # Sort by timestamp descending (newest first)
            history = sorted(results['metadatas'], key=lambda x: x.get('timestamp', 0), reverse=True)
            # Return the latest 'limit' items (limit applies to turns, so limit*2 for Q&A)
            return history[:limit]
        return []
    except Exception as e:
        logger.error(f"Error retrieving chat history from ChromaDB: {e}", exc_info=True)
        return []

def delete_chat_history(chat_id: str):
    """Deletes all history associated with a chat ID."""
    if not chat_history_collection:
        logger.error("Chat history collection not available.")
        return False
    try:
        chat_history_collection.delete(where={"chat_id": chat_id})
        logger.info(f"Deleted chat history for chat_id: {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error deleting chat history: {e}", exc_info=True)
        return False

def get_all_chats() -> List[Dict]:
    """Retrieves basic info (ID, first message, sources) for all chats."""
    if not chat_history_collection:
        logger.error("Chat history collection not available.")
        return []
    try:
        # Inefficient way to get distinct chat_ids, similar to get_available_sources
        results = chat_history_collection.get(include=['metadatas'], limit=10000) # Adjust limit
        chats = {}
        if results and results.get('metadatas'):
             # Sort all messages by timestamp to find the first one per chat
            all_messages = sorted(results['metadatas'], key=lambda x: x.get('timestamp', 0))
            for meta in all_messages:
                chat_id = meta.get('chat_id')
                if chat_id and chat_id not in chats:
                    # Store first user message and sources associated with the first turn
                    first_user_message = meta.get('user_query', 'Chat started...') if meta.get('role') == 'user' else 'Chat started...'
                    # Find the turn data associated with this message to get sources
                    # This assumes sources are stored with the assistant response turn following the user query
                    # Let's try to find the first assistant turn to get associated sources
                    selected_sources = meta.get('selected_sources', [])

                    chats[chat_id] = {
                        "chat_id": chat_id,
                        "first_message": first_user_message,
                         "selected_sources": selected_sources # Store sources here
                    }
                 # Update sources if found later in history (maybe from first assistant response)
                elif chat_id and 'selected_sources' in meta and not chats[chat_id].get('selected_sources'):
                    chats[chat_id]['selected_sources'] = meta.get('selected_sources', [])


        return list(chats.values())
    except Exception as e:
        logger.error(f"Error retrieving all chats: {e}", exc_info=True)
        return []

def add_semantic_concept(term: str, definition: str, source_url: str):
    """Adds a semantic concept/acronym to the main collection."""
    if not collection or not embedding_func:
         logger.error("ChromaDB collection or embedding function not available.")
         return False
    try:
        # Use a specific ID format for concepts
        concept_id = f"concept_{term.lower().replace(' ', '_')}_{hash(source_url)}"
        metadata = {
            "is_concept": True,
            "term": term,
            "definition": definition,
            "source_url": source_url # Link concept to its origin page
        }
        collection.add(
            ids=[concept_id],
            metadatas=[metadata],
            documents=[f"Concept: {term}. Definition: {definition}"] # Embed the term and definition
        )
        logger.debug(f"Added semantic concept: {term}")
        return True
    except Exception as e:
        # Ignore duplicate ID errors silently maybe?
        if "ID already exists" not in str(e):
            logger.warning(f"Could not add semantic concept '{term}': {e}")
        return False

def find_semantic_concepts(words: List[str]) -> Dict[str, Dict]:
    """Finds definitions for given words by querying concepts in ChromaDB."""
    if not collection:
        logger.error("ChromaDB collection not available for concept search.")
        return {}

    found_concepts = {}
    if not words:
        return found_concepts

    try:
        # Query for potential matches using the words themselves
        # This might not be the most efficient way. We could also fetch all concepts and filter.
        # Let's try querying for each word. This could be slow for long queries.
        # Consider optimizing this if performance is an issue.

        # Prepare a batch query if possible, or iterate
        # ChromaDB's query allows multiple query_texts, but filtering per query isn't straightforward.
        # Let's iterate for simplicity now.

        for word in set(w.lower() for w in words if len(w) > 2): # Simple filtering
            results = collection.get(
                where={"$and": [
                    {"is_concept": True},
                    # Search for the word in the 'term' metadata field (case-insensitive needs careful handling)
                    # ChromaDB's filtering might be exact match. Let's filter after retrieval for flexibility.
                    # Or we can store a lowercased version of the term in metadata. Let's assume term is stored as is.
                    # We can try filtering on the embedded document instead.
                 ]},
                 # where_document={"$contains": word}, # Search within the document text
                 include=["metadatas", "documents"]
            )

            if results and results.get('ids'):
                 for i, doc_id in enumerate(results['ids']):
                     meta = results['metadatas'][i]
                     doc = results['documents'][i]
                     term = meta.get("term")
                     # Post-filter check (case-insensitive)
                     if term and word == term.lower():
                         if word not in found_concepts: # Take the first match
                             found_concepts[word] = {
                                 "term": term,
                                 "definition": meta.get("definition", "No definition found."),
                                 "source_url": meta.get("source_url", "Unknown source")
                             }
                             break # Move to next word once found

        logger.info(f"Found definitions for concepts: {list(found_concepts.keys())}")
        return found_concepts

    except Exception as e:
        logger.error(f"Error finding semantic concepts: {e}", exc_info=True)
        return {}