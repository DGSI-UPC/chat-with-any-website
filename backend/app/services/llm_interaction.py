import logging
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Tuple
from openai import AsyncOpenAI # Use Async client
import asyncio


from ..core.config import settings
from ..core.db import ChatHistory, knowledge_collection, get_db # Import collection
from .semantics import find_terms_in_text, format_semantic_context # Import semantic functions

logger = logging.getLogger(__name__)

# Initialize OpenAI client (or other LLM client)
# Ensure OPENAI_API_KEY is set in environment or config
if settings.LLM_PROVIDER == "openai":
    llm_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
else:
    # Placeholder for other LLM providers
    logger.warning(f"LLM Provider '{settings.LLM_PROVIDER}' not fully implemented. Using placeholder.")
    llm_client = None # You'd initialize other clients here


async def generate_query_variations(question: str, num_variations: int = settings.CHROMA_QUERY_COUNT) -> List[str]:
    """
    Generates variations of the user's question for broader ChromaDB search.
    Can use a simple approach or call an LLM for more sophisticated variations.
    """
    # Simple approach: return the original question plus maybe keywords
    variations = [question]
    # Add more sophisticated logic here if needed, e.g., extracting keywords,
    # or using another LLM call to rephrase the question.
    # For now, just duplicate for demonstration if needed
    while len(variations) < num_variations:
        variations.append(question) # Basic duplication for now
    logger.info(f"Generated {len(variations)} query variations.")
    return variations[:num_variations] # Ensure correct number

async def retrieve_relevant_chunks(queries: List[str], n_results: int = settings.CHROMA_N_RESULTS) -> Tuple[List[str], List[str]]:
    """Queries ChromaDB with multiple variations and returns unique, relevant chunks and their sources."""
    all_results = []
    source_urls = set()

    try:
        # Perform queries concurrently
        query_tasks = [
            asyncio.to_thread(
                knowledge_collection.query,
                query_texts=[query],
                n_results=n_results,
                include=['documents', 'metadatas', 'distances'] # Include distances for potential ranking/filtering
            ) for query in queries
        ]
        results_list = await asyncio.gather(*query_tasks)

        # Process and deduplicate results
        processed_ids = set()
        all_docs = []
        all_metadatas = []
        all_distances = []

        for result_set in results_list:
            if result_set and result_set.get('ids') and result_set['ids'][0]:
                 ids = result_set['ids'][0]
                 docs = result_set['documents'][0]
                 metadatas = result_set['metadatas'][0]
                 distances = result_set.get('distances', [None] * len(ids))[0] # Handle if distances are missing

                 for i, doc_id in enumerate(ids):
                     if doc_id not in processed_ids:
                         processed_ids.add(doc_id)
                         all_docs.append(docs[i])
                         all_metadatas.append(metadatas[i])
                         all_distances.append(distances[i] if distances else None)
                         if metadatas[i] and 'source' in metadatas[i]:
                              source_urls.add(metadatas[i]['source'])

        # Optional: Sort by distance if available
        if all(d is not None for d in all_distances):
             sorted_indices = sorted(range(len(all_distances)), key=lambda k: all_distances[k])
             relevant_chunks = [all_docs[i] for i in sorted_indices]
        else:
             relevant_chunks = all_docs # Use original order if distances missing/inconsistent


        logger.info(f"Retrieved {len(relevant_chunks)} unique chunks from ChromaDB.")
        return relevant_chunks, list(source_urls)

    except Exception as e:
        logger.error(f"Error querying ChromaDB: {e}")
        return [], []


async def augment_and_ask(db: Session, user_question: str, session_id: str = "default") -> Tuple[str, List[str]]:
    """Augments the question, queries Chroma, calls LLM, and stores history."""

    # 1. Retrieve Chat History
    history_records = db.query(ChatHistory)\
        .filter(ChatHistory.session_id == session_id)\
        .order_by(ChatHistory.timestamp.desc())\
        .limit(settings.CHAT_HISTORY_LENGTH * 2).all()
    history_records.reverse() # Oldest first for context
    chat_history_context = "\n".join([f"{h.role}: {h.content}" for h in history_records])
    logger.info(f"Retrieved {len(history_records)} messages from chat history.")

    # 2. Semantic Augmentation (Simplified)
    semantic_terms = find_terms_in_text(db, user_question, settings.SEMANTIC_LOOKUP_DEPTH)
    semantic_context = "Relevant Concepts Found:\n"
    if semantic_terms:
        for term in semantic_terms:
             # Use the recursive formatter
             semantic_context += format_semantic_context([], term, 0, settings.SEMANTIC_LOOKUP_DEPTH) + "\n---\n"
    else:
        semantic_context = "No specific semantic terms found in the question.\n"
    logger.info("Performed semantic lookup.")


    # 3. Prepare Augmented Question & Generate ChromaDB Queries
    # Combine elements for a potentially better query base
    query_base = f"{user_question}\nContext from history: {chat_history_context}\nRelevant Concepts: {semantic_context}"
    query_variations = await generate_query_variations(query_base, settings.CHROMA_QUERY_COUNT)

    # 4. Retrieve Relevant Chunks from ChromaDB
    relevant_chunks, source_urls = await retrieve_relevant_chunks(query_variations, settings.CHROMA_N_RESULTS)
    knowledge_context = "\n\n---\n\n".join(relevant_chunks) if relevant_chunks else "No specific documents found in the knowledge base."

    # 5. Construct Final Prompt for LLM
    system_message = """You are a helpful assistant answering questions based on the provided context.
Use the information from the 'Knowledge Base Context' and 'Semantic Concepts' sections to answer the user's question.
If the answer is not found in the context, say so clearly. Do not make up information.
You can also use the 'Chat History' for conversational context.
Cite the sources provided if you use information from the knowledge base. Format citations like [Source: URL]."""

    prompt_messages = [
        {"role": "system", "content": system_message},
        {"role": "system", "content": f"--- Knowledge Base Context ---\n{knowledge_context}"},
        {"role": "system", "content": f"--- Semantic Concepts ---\n{semantic_context}"},
        {"role": "system", "content": f"--- Chat History ---\n{chat_history_context}"},
        {"role": "user", "content": user_question}
    ]

    # Add previous turns from history_records directly if using OpenAI format
    # prompt_messages = [{"role": "system", "content": system_message},
    #                    {"role": "system", "content": f"--- Knowledge Base Context ---\n{knowledge_context}"},
    #                    {"role": "system", "content": f"--- Semantic Concepts ---\n{semantic_context}"}]
    # for record in history_records:
    #      prompt_messages.append({"role": record.role, "content": record.content})
    # prompt_messages.append({"role": "user", "content": user_question})


    # 6. Call LLM
    ai_response_content = "Sorry, I encountered an error." # Default error message
    if llm_client:
        try:
            logger.info(f"Sending request to LLM model: {settings.LLM_MODEL_NAME}")
            completion = await llm_client.chat.completions.create(
                model=settings.LLM_MODEL_NAME,
                messages=prompt_messages,
                temperature=0.7, # Adjust as needed
                max_tokens=1000 # Adjust as needed
            )
            ai_response_content = completion.choices[0].message.content
            logger.info("Received response from LLM.")

        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            ai_response_content = f"Sorry, I encountered an error while contacting the language model: {e}"
    else:
         logger.error("LLM client not initialized.")
         ai_response_content = "LLM client is not configured or available."


    # 7. Store User Question and AI Response in History
    try:
        user_entry = ChatHistory(session_id=session_id, role="user", content=user_question)
        ai_entry = ChatHistory(session_id=session_id, role="assistant", content=ai_response_content)
        db.add_all([user_entry, ai_entry])
        db.commit()
        logger.info("Saved user question and AI response to chat history.")
    except Exception as e:
        logger.error(f"Failed to save chat history: {e}")
        db.rollback() # Rollback on error


    return ai_response_content, source_urls