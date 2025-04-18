# backend/app/core/scraping/scraper.py
import asyncio
import aiohttp
import logging
from typing import Dict, Set, List, Tuple, Optional, Callable, Any # Added Callable, Any
from urllib.parse import urlparse
import time
import tiktoken # For chunking based on tokens
from bs4 import BeautifulSoup # Need this for title extraction again

from ..config import settings
from .utils import normalize_url, get_base_url, guess_mimetype, get_content_type, generate_unique_id, is_internal_url, clean_text
from .html_parser import parse_html_content
from .pdf_parser import extract_text_from_pdf
from ..vector_store import add_documents
from ..semantic import extract_and_store_concepts
# REMOVED: from ..background import update_scrape_status # Import the status update function

logger = logging.getLogger(__name__)

# --- Text Chunking ---
# (Keep the chunk_text function as it was)
try:
    tokenizer = tiktoken.get_encoding("cl100k_base") # Encoder for gpt-4, gpt-3.5-turbo, etc.
except Exception:
    logger.warning("Tiktoken cl100k_base not found, falling back to basic split.")
    tokenizer = None

CHUNK_SIZE_TOKENS = 500 # Max tokens per chunk
CHUNK_OVERLAP_TOKENS = 50 # Overlap between chunks

def chunk_text(text: str, source_url: str, page_title: Optional[str]=None) -> List[Dict]:
    """Chunks text into smaller pieces suitable for embedding."""
    chunks = []
    if not text:
        return chunks

    base_metadata = {"source_url": source_url}
    if page_title:
        base_metadata["page_title"] = page_title # Add page title if available

    if tokenizer:
        tokens = tokenizer.encode(text)
        start_idx = 0
        chunk_num = 0
        while start_idx < len(tokens):
            end_idx = min(start_idx + CHUNK_SIZE_TOKENS, len(tokens))
            chunk_tokens = tokens[start_idx:end_idx]
            chunk_text = tokenizer.decode(chunk_tokens)

            if chunk_text.strip(): # Ensure chunk is not just whitespace
                chunk_num += 1
                metadata = {**base_metadata, "chunk_num": chunk_num}
                chunk_id = generate_unique_id(f"{source_url}_{chunk_num}")
                chunks.append({"id": chunk_id, "text": chunk_text, "metadata": metadata})

            # Move start index for next chunk, considering overlap
            # Adjust step to avoid re-processing the same tokens due to overlap logic
            step = CHUNK_SIZE_TOKENS - CHUNK_OVERLAP_TOKENS
            if step <= 0: step = CHUNK_SIZE_TOKENS # Prevent infinite loop if overlap >= size
            start_idx += step

    else:
        # Fallback to simple character split (less ideal)
        char_chunk_size = 1500 # Approximate chars
        char_overlap = 150
        start_idx = 0
        chunk_num = 0
        while start_idx < len(text):
            end_idx = min(start_idx + char_chunk_size, len(text))
            chunk_text = text[start_idx:end_idx]

            if chunk_text.strip():
                chunk_num += 1
                metadata = {**base_metadata, "chunk_num": chunk_num}
                chunk_id = generate_unique_id(f"{source_url}_{chunk_num}")
                chunks.append({"id": chunk_id, "text": chunk_text, "metadata": metadata})

            step = char_chunk_size - char_overlap
            if step <= 0: step = char_chunk_size
            start_idx += step


    logger.info(f"Chunked text from {source_url} into {len(chunks)} chunks.")
    return chunks

# --- Main Scraper Class ---
class WebsiteScraper:
    # ADDED status_update_callback parameter
    def __init__(self, start_url: str, status_update_callback: Callable):
        self.start_url = normalize_url(start_url)
        self.base_url = get_base_url(self.start_url)
        self.base_domain = urlparse(self.start_url).netloc.lower()
        self.visited_urls: Set[str] = set()
        self.to_visit_queue: asyncio.Queue = asyncio.Queue()
        self.processed_pages: int = 0
        self.total_discovered: int = 1 # Start with the initial URL
        self.scrape_errors: List[str] = []
        self.extracted_concepts: Set[str] = set() # Track concepts extracted in this run
        self.session: Optional[aiohttp.ClientSession] = None
        self.semaphore = asyncio.Semaphore(settings.SCRAPER_MAX_CONCURRENT_TASKS)
        self.status_updater = status_update_callback # STORE the callback

    async def _fetch_url(self, url: str) -> Optional[Tuple[bytes, str, Dict]]:
        """Fetches content from a URL asynchronously."""
        await asyncio.sleep(0.05) # Small delay to be polite
        logger.info(f"Fetching: {url}")
        headers = {'User-Agent': settings.SCRAPER_USER_AGENT}
        try:
            async with self.semaphore: # Limit concurrency
                 async with self.session.get(url, headers=headers, timeout=settings.SCRAPER_REQUEST_TIMEOUT, allow_redirects=True) as response:
                    response.raise_for_status() # Raise exception for bad status codes (4xx or 5xx)
                    content = await response.read()
                    # Use real URL after redirects
                    final_url = str(response.url)
                    content_type = get_content_type(response.headers)
                    logger.info(f"Fetched {final_url} (from {url}) - Status: {response.status}, Type: {content_type}, Size: {len(content)} bytes")
                    # Check if redirect went outside the original domain
                    if not is_internal_url(final_url, self.base_domain):
                        logger.warning(f"Redirected outside domain: {url} -> {final_url}. Skipping further processing of this URL.")
                        # We might have already added the original URL to visited_urls, handle potential duplicates if needed
                        self.visited_urls.add(final_url) # Mark redirected URL as visited too
                        return None # Don't process external content
                    return content, content_type, dict(response.headers)
        except aiohttp.ClientResponseError as e:
             # Log specific HTTP errors
             logger.error(f"HTTP Error {e.status} fetching {url}: {e.message}")
             self.scrape_errors.append(f"HTTP Error {e.status}: {url} - {e.message}")
             # Treat 404, 403 etc. as 'processed' but with error, don't retry
             if e.status >= 400 and e.status < 500:
                 self.visited_urls.add(url) # Ensure we don't retry client errors
             return None # Indicate fetch failure
        except aiohttp.ClientError as e:
            logger.error(f"Network/Connection Error fetching {url}: {e}")
            self.scrape_errors.append(f"Network Error: {url} - {e}")
            return None
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {url}")
            self.scrape_errors.append(f"Timeout Error: {url}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}", exc_info=True)
            self.scrape_errors.append(f"Unexpected Fetch Error: {url} - {e}")
            return None


    async def _process_page(self, url: str, depth: int):
        """Processes a single page: fetch, parse, chunk, index, find links."""
        # Normalize URL before checking visited set
        normalized_url = normalize_url(url)
        if normalized_url in self.visited_urls or depth > settings.SCRAPER_MAX_DEPTH:
            # logger.debug(f"Skipping already visited or too deep: {normalized_url} (Depth: {depth})")
            return
        self.visited_urls.add(normalized_url)

        fetch_result = await self._fetch_url(normalized_url) # Use normalized URL for fetching

        # If fetch failed (returned None), update status and return
        if not fetch_result:
            self.processed_pages += 1 # Count as processed even if failed
            # USE self.status_updater instead of imported function
            self.status_updater(self.start_url, "running", self.processed_pages, self.total_discovered, error=f"Failed to fetch/process {normalized_url}")
            return

        content, content_type, headers = fetch_result
        extracted_text = None
        internal_links = []
        page_title = None # Initialize page_title

        # Decode content and parse based on type
        # Ensure decoding happens before parsing
        html_content = None # Store decoded HTML if applicable
        if 'html' in content_type:
            try:
                # Try common encodings, fall back to replace errors
                try:
                     html_content = content.decode('utf-8')
                except UnicodeDecodeError:
                     try:
                         html_content = content.decode('iso-8859-1')
                     except UnicodeDecodeError:
                         logger.warning(f"Could not decode HTML with utf-8 or iso-8859-1 for {normalized_url}, using 'replace' errors.")
                         html_content = content.decode('utf-8', errors='replace')

                extracted_text, internal_links = parse_html_content(html_content, normalized_url, self.base_domain)
                # Extract title here
                try:
                    soup = BeautifulSoup(html_content, 'lxml')
                    title_tag = soup.find('title')
                    if title_tag and title_tag.string:
                         page_title = title_tag.string.strip()
                except Exception as title_e:
                     logger.warning(f"Could not extract title for {normalized_url}: {title_e}")

            except Exception as e:
                logger.error(f"Error parsing HTML for {normalized_url}: {e}", exc_info=True)
                self.scrape_errors.append(f"HTML Parsing Error: {normalized_url} - {e}")
        elif 'pdf' in content_type:
            extracted_text = extract_text_from_pdf(content, normalized_url)
            if extracted_text is None:
                 self.scrape_errors.append(f"PDF Processing Error: {normalized_url}")
        elif 'text/plain' in content_type:
             try:
                 # Similar decoding strategy as HTML
                 try:
                      extracted_text = content.decode('utf-8')
                 except UnicodeDecodeError:
                      try:
                          extracted_text = content.decode('iso-8859-1')
                      except UnicodeDecodeError:
                          logger.warning(f"Could not decode plain text with utf-8 or iso-8859-1 for {normalized_url}, using 'replace' errors.")
                          extracted_text = content.decode('utf-8', errors='replace')
                 if extracted_text:
                     extracted_text = clean_text(extracted_text) # Clean plain text too
             except Exception as e:
                  logger.error(f"Error decoding plain text for {normalized_url}: {e}")
                  self.scrape_errors.append(f"Text Decoding Error: {normalized_url} - {e}")
        else:
            logger.warning(f"Skipping unsupported content type '{content_type}' for URL: {normalized_url}")


        # Chunk and index the extracted text
        if extracted_text:
            chunks = chunk_text(extracted_text, source_url=normalized_url, page_title=page_title)
            if chunks:
                docs_to_add = [chunk['text'] for chunk in chunks]
                metadatas_to_add = [chunk['metadata'] for chunk in chunks]
                 # Add base URL to metadata for easier filtering
                for meta in metadatas_to_add:
                    meta['source_url_base'] = self.base_url

                ids_to_add = [chunk['id'] for chunk in chunks]

                # Add documents to Vector Store
                success = add_documents(docs_to_add, metadatas_to_add, ids_to_add)
                if success:
                     logger.info(f"Successfully indexed {len(chunks)} chunks from {normalized_url}.")
                     # Extract and store semantic concepts from these chunks
                     for chunk_text_content in docs_to_add:
                          extract_and_store_concepts(chunk_text_content, normalized_url, self.extracted_concepts)
                else:
                     logger.error(f"Failed to index chunks from {normalized_url}.")
                     self.scrape_errors.append(f"Indexing Error: {normalized_url}")


        # Add newly discovered internal links to the queue
        newly_discovered = 0
        for link in internal_links:
            # Ensure links added to queue haven't been visited OR are already in the queue
            # Check visited status *before* adding to queue
            normalized_link = normalize_url(link) # Normalize before checking/adding
            if normalized_link not in self.visited_urls:
                 # Check if already in queue - tricky with asyncio.Queue directly
                 # For simplicity, we might add duplicates but the visited_urls check handles them later
                 # Or maintain a separate set for URLs currently in the queue if performance is critical
                 await self.to_visit_queue.put((normalized_link, depth + 1))
                 newly_discovered += 1

        self.processed_pages += 1
        self.total_discovered += newly_discovered
        # Update progress using the callback
        self.status_updater(self.start_url, "running", self.processed_pages, self.total_discovered)

        logger.info(f"Processed: {normalized_url} (Depth: {depth}). Pages Processed: {self.processed_pages}/{self.total_discovered}. Links Found: {len(internal_links)}. Errors: {len(self.scrape_errors)}")


    async def run(self):
        """Starts the scraping process."""
        start_time = time.time()
        # USE self.status_updater instead of imported function
        self.status_updater(self.start_url, "running", self.processed_pages, self.total_discovered, message="Scraping started...")

        connector = aiohttp.TCPConnector(limit=settings.SCRAPER_MAX_CONCURRENT_TASKS) # Limit total connections
        # Set connection timeout globally for the session
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=settings.SCRAPER_REQUEST_TIMEOUT) # Separate connect/read timeouts
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            self.session = session
            # Add the initial URL to the queue (make sure it's normalized)
            await self.to_visit_queue.put((self.start_url, 0))

            active_tasks = set()

            while True:
                # Check if we should stop (queue empty and no tasks running)
                if self.to_visit_queue.empty() and not active_tasks:
                     break

                # Add tasks from the queue up to the concurrency limit
                while not self.to_visit_queue.empty() and len(active_tasks) < settings.SCRAPER_MAX_CONCURRENT_TASKS:
                    try:
                        # Get item without waiting indefinitely if queue becomes empty concurrently
                        url, depth = self.to_visit_queue.get_nowait()
                        # Double-check visited here, as duplicates might enter the queue
                        if url not in self.visited_urls:
                             task = asyncio.create_task(self._process_page(url, depth))
                             active_tasks.add(task)
                             # Add callback to remove task from set upon completion
                             task.add_done_callback(active_tasks.discard)
                        else:
                             self.to_visit_queue.task_done() # Mark as done if skipped
                    except asyncio.QueueEmpty:
                        break # Queue is empty, proceed to wait for tasks

                if not active_tasks:
                     # Should be caught by the loop break condition, but as safety:
                     await asyncio.sleep(0.05) # Wait briefly if queue is empty but somehow loop continues
                     continue

                # Wait for at least one task to complete
                done, pending = await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)

                # `active_tasks` is automatically managed by the done callback now

                # Mark tasks associated with done futures as processed in the queue
                # We need to associate futures back to queue items if task_done isn't called internally
                # For simplicity, assuming task completion implies queue item processing
                # A more robust system might track queue items explicitly

        await self.to_visit_queue.join() # Ensure queue is fully processed if needed (though loop logic should handle it)

        end_time = time.time()
        duration = end_time - start_time
        final_status = "completed" if not self.scrape_errors else "completed_with_errors"
        error_count = len(self.scrape_errors)
        final_message = f"Scraping finished in {duration:.2f}s. Processed: {self.processed_pages}. Errors: {error_count}."
        if error_count > 0:
             final_message += f" Last error: {self.scrape_errors[-1][:100]}..." # Show snippet of last error

        # USE self.status_updater instead of imported function
        self.status_updater(self.start_url, final_status, self.processed_pages, self.total_discovered, message=final_message)
        logger.info(final_message)
        if self.scrape_errors:
             logger.warning(f"Errors encountered during scrape of {self.start_url}: {error_count} total. Sample: {self.scrape_errors[:5]}")


# Function to be called in the background task
# ADDED status_update_callback parameter
async def run_scrape_job(url: str, status_update_callback: Callable):
    # PASS the callback to the scraper instance
    scraper = WebsiteScraper(url, status_update_callback=status_update_callback)
    try:
        await scraper.run()
    except Exception as e:
        # Catch unexpected errors during scraper execution
        logger.error(f"Critical error during scrape job for {url}: {e}", exc_info=True)
        # Update status to failed if scraper run crashes
        scraper.status_updater(
            scraper.start_url,
            "failed",
            scraper.processed_pages,
            scraper.total_discovered,
            message=f"Scraper failed critically: {e}"
        )