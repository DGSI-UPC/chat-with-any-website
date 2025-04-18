import re
import openai
from .config import settings
import logging
from typing import List, Dict, Optional, Tuple
import time

logger = logging.getLogger(__name__)

# Configure OpenAI client
openai.api_key = settings.OPENAI_API_KEY

def format_RAG_prompt(query: str, context_chunks: List[Dict], semantic_augmentation: str, chat_history: List[Dict]) -> List[Dict[str, str]]:
    """Formats the prompt for the LLM, including context, history, and instructions."""

    system_message = """You are a helpful assistant answering questions based on the provided context from specific websites.
Use *only* the information available in the 'Retrieved Context' and 'Semantic Context' sections to answer the user's query.
If the answer is not found in the provided context, state that you cannot answer based on the available information from the website(s).
When you use information from the 'Retrieved Context', you MUST cite the source URL(s). Append the citation(s) clearly at the end of your answer in the format [Source: <URL>]. If multiple sources are used, list them all. Example: [Source: https://example.com/page1], [Source: https://example.com/page2].
Do not use information from the chat history unless it's directly relevant to understanding the current query.
Keep your answers concise and directly address the user's query.
Answer in the same language as the user's query if possible (the context may be multilingual)."""

    # Format retrieved context
    context_str = "Retrieved Context:\n"
    if context_chunks:
        for i, chunk in enumerate(context_chunks):
            source_url = chunk.get('metadata', {}).get('source_url', 'Unknown Source')
            context_str += f"Chunk {i+1} (Source: {source_url}):\n{chunk.get('document', '')}\n---\n"
    else:
        context_str += "No relevant context found in the vector database for the selected sources.\n---\n"

    # Combine contexts
    full_context = context_str
    if semantic_augmentation:
        full_context += "\n" + semantic_augmentation + "\n" # Already includes header and ---

    # Format history (newest first, limit length)
    history_messages = []
    if chat_history:
        # History is newest first, take last N turns (user+assistant = 2 messages per turn)
        history_limit = settings.LLM_MAX_HISTORY * 2
        for turn in reversed(chat_history[:history_limit]): # Iterate oldest relevant first
            if turn.get('role') == 'user':
                 history_messages.append({"role": "user", "content": turn.get('content', '')})
            elif turn.get('role') == 'assistant':
                 history_messages.append({"role": "assistant", "content": turn.get('content', '')})

    # Construct final messages list
    messages = [{"role": "system", "content": system_message}]
    messages.extend(history_messages) # Add history
    messages.append({"role": "user", "content": f"{full_context}\nUser Query: {query}"}) # Add context and current query

    return messages

def get_chat_response(query: str, context_chunks: List[Dict], semantic_augmentation: str, chat_history: List[Dict]) -> Tuple[str, List[str]]:
    """Gets response from OpenAI API based on formatted prompt."""
    if not settings.OPENAI_API_KEY:
        logger.error("OpenAI API key not configured.")
        return "Error: LLM service is not configured.", []

    messages = format_RAG_prompt(query, context_chunks, semantic_augmentation, chat_history)

    logger.debug(f"Sending request to LLM. Model: {settings.LLM_MODEL_NAME}. Messages: {messages}")

    try:
        start_time = time.time()
        response = openai.chat.completions.create(
            model=settings.LLM_MODEL_NAME,
            messages=messages,
            temperature=0.2, # Lower temperature for more factual RAG
            max_tokens=1000, # Adjust as needed
            # stream=True # Consider streaming for better UX
        )
        end_time = time.time()
        logger.info(f"LLM response received in {end_time - start_time:.2f} seconds.")

        llm_content = response.choices[0].message.content.strip()

        # --- Simple Source Extraction (Based on the requested format) ---
        # This relies *heavily* on the LLM following the citation instruction.
        sources = []
        source_pattern = re.compile(r'\[Source:\s*(.*?)\s*\]')
        matches = source_pattern.findall(llm_content)
        if matches:
            sources = [match.strip() for match in matches]
            # Optionally remove the source citations from the main content
            # llm_content = source_pattern.sub('', llm_content).strip()

        logger.debug(f"LLM Response: {llm_content}, Sources: {sources}")
        return llm_content, sources

    except openai.APIError as e:
        logger.error(f"OpenAI API Error: {e}", exc_info=True)
        return f"Error communicating with the LLM: {e}", []
    except Exception as e:
        logger.error(f"An unexpected error occurred during LLM interaction: {e}", exc_info=True)
        return "An unexpected error occurred while processing your request.", []