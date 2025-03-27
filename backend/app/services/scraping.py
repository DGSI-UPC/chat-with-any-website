import httpx # Async HTTP client
import pypdfium2 as pdfium # PDF processing
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import logging
import asyncio
from typing import Set, Tuple, Optional, List
import os

from ..core.config import settings

logger = logging.getLogger(__name__)

# --- Tesseract Configuration ---
# Set TESSDATA_PREFIX if needed, especially in Docker
# os.environ['TESSDATA_PREFIX'] = '/usr/share/tesseract-ocr/4.00/tessdata'
# You might need to specify the path to the tesseract executable
# pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'


async def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> Tuple[str, bool]:
    """Extracts text from PDF bytes using PyPDFium2, falling back to OCR."""
    text = ""
    ocr_used = False
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        for i in range(len(pdf)):
            page = pdf.get_page(i)
            text += page.get_textpage().get_text_range() + "\n"
            page.close()
        pdf.close()
        logger.info("Successfully extracted text using PyPDFium2")

        # Basic check if extraction likely failed (e.g., scanned PDF)
        if len(text.strip()) < 50: # Arbitrary threshold
             logger.warning("Low text extracted via PyPDFium2, attempting OCR fallback.")
             text = await ocr_pdf_bytes(pdf_bytes)
             ocr_used = True
        elif not any(c.isalnum() for c in text): # Check if it's mostly non-alphanumeric garbage
            logger.warning("Extracted text seems non-alphanumeric, attempting OCR fallback.")
            text = await ocr_pdf_bytes(pdf_bytes)
            ocr_used = True

    except Exception as e_pypdf:
        logger.error(f"PyPDFium2 failed: {e_pypdf}. Attempting OCR.")
        try:
            text = await ocr_pdf_bytes(pdf_bytes)
            ocr_used = True
        except Exception as e_ocr:
            logger.error(f"OCR also failed: {e_ocr}")
            text = "" # Ensure text is empty string on complete failure
            ocr_used = False # OCR didn't succeed

    return text.strip(), ocr_used

async def ocr_pdf_bytes(pdf_bytes: bytes) -> str:
    """Performs OCR on PDF bytes using pytesseract."""
    text = ""
    try:
        # Convert PDF to images
        images = convert_from_bytes(pdf_bytes, dpi=300) # Higher DPI for better OCR
        if not images:
            logger.warning("pdf2image returned no images.")
            return ""

        # OCR each image
        # Run OCR in parallel using asyncio.gather for slight speedup
        tasks = [asyncio.to_thread(pytesseract.image_to_string, img, lang='eng') for img in images] # Adjust lang if needed
        results = await asyncio.gather(*tasks)
        text = "\n\n--- Page Break ---\n\n".join(results)
        logger.info(f"OCR performed successfully on {len(images)} pages.")

    except pytesseract.TesseractNotFoundError:
        logger.error("Tesseract executable not found. Please install Tesseract and/or configure pytesseract.pytesseract.tesseract_cmd.")
        raise # Re-raise critical configuration error
    except Exception as e:
        logger.error(f"An error occurred during OCR: {e}")
        text = "" # Return empty string on other errors

    return text

async def fetch_url(client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
    """Fetches a URL content with appropriate headers and timeout."""
    headers = {'User-Agent': settings.USER_AGENT}
    try:
        response = await client.get(url, headers=headers, timeout=settings.REQUESTS_TIMEOUT, follow_redirects=True)
        response.raise_for_status() # Raise exception for 4xx/5xx status codes
        return response
    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP error fetching {url}: {e.response.status_code} {e.response.reason_phrase}")
    except httpx.RequestError as e:
        logger.warning(f"Request error fetching {url}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
    return None

async def scrape_website(start_url: str, max_depth: int = settings.MAX_SCRAPE_DEPTH) -> List[Tuple[str, str]]:
    """
    Scrapes a website starting from start_url, following links within the same domain/subdomain.
    Downloads and processes text from HTML and PDFs.

    Returns:
        List of tuples: (source_url, extracted_text)
    """
    base_domain = urlparse(start_url).netloc
    urls_to_visit: asyncio.Queue[Tuple[str, int]] = asyncio.Queue()
    visited_urls: Set[str] = set()
    scraped_content: List[Tuple[str, str]] = [] # List to store (url, text)

    await urls_to_visit.put((start_url, 0))
    visited_urls.add(start_url)

    async with httpx.AsyncClient() as client:
        tasks = []
        # Limit concurrent scraping tasks to avoid overwhelming servers or getting blocked
        max_concurrent_tasks = 10
        active_tasks = 0

        while not urls_to_visit.empty() or tasks:
            # Start new tasks if queue has items and concurrency limit not reached
            while not urls_to_visit.empty() and active_tasks < max_concurrent_tasks:
                 current_url, current_depth = await urls_to_visit.get()
                 task = asyncio.create_task(process_url(client, current_url, current_depth, base_domain, visited_urls, urls_to_visit, max_depth))
                 tasks.append(task)
                 active_tasks += 1
                 urls_to_visit.task_done() # Mark task as started

            if not tasks:
                await asyncio.sleep(0.1) # Avoid busy-waiting if queue is empty but tasks might add more
                continue

            # Wait for any task to complete
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            tasks = list(pending) # Update the list of pending tasks
            active_tasks -= len(done) # Decrease active task count

            for task in done:
                try:
                    result = await task
                    if result:
                        url, text, new_links = result
                        if text:
                             scraped_content.append((url, text))
                        # Add newly found, valid links to the queue (process_url handles visited check)
                        for link, depth in new_links:
                            await urls_to_visit.put((link, depth))

                except Exception as e:
                    logger.error(f"Error processing task result: {e}")


    logger.info(f"Scraping finished. Processed {len(visited_urls)} URLs. Found content from {len(scraped_content)} sources.")
    return scraped_content


async def process_url(client: httpx.AsyncClient, url: str, depth: int, base_domain: str, visited: Set[str], queue: asyncio.Queue, max_depth: int) -> Optional[Tuple[str, str, List[Tuple[str, int]]]]:
    """Processes a single URL: fetches, parses, extracts text/PDFs, finds links."""
    logger.info(f"Processing [Depth {depth}]: {url}")
    response = await fetch_url(client, url)
    if not response:
        return None

    content_type = response.headers.get('content-type', '').lower()
    extracted_text = ""
    new_links_to_add = []

    if 'pdf' in content_type:
        logger.info(f"Processing PDF: {url}")
        try:
            pdf_bytes = await response.aread()
            extracted_text, ocr_used = await extract_text_from_pdf_bytes(pdf_bytes)
            if extracted_text:
                logger.info(f"Extracted text from PDF {url} ({'OCR' if ocr_used else 'Direct'})")
            else:
                 logger.warning(f"No text extracted from PDF: {url}")
        except Exception as e:
            logger.error(f"Failed to process PDF {url}: {e}")

    elif 'html' in content_type:
        logger.info(f"Processing HTML: {url}")
        try:
            html_content = await response.aread()
            soup = BeautifulSoup(html_content, 'html.parser')

            # Basic text extraction (remove script/style, get text)
            for element in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']):
                element.decompose()
            extracted_text = soup.get_text(separator=' ', strip=True)

            # Find links if depth allows further scraping
            if depth < max_depth:
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    absolute_link = urljoin(url, href)
                    parsed_link = urlparse(absolute_link)

                    # Basic validation and domain check
                    if parsed_link.scheme in ['http', 'https'] and parsed_link.netloc.endswith(base_domain):
                        # Normalize URL (remove fragment)
                        normalized_link = parsed_link._replace(fragment="").geturl()
                        if normalized_link not in visited:
                            visited.add(normalized_link)
                            new_links_to_add.append((normalized_link, depth + 1))
                            # logger.debug(f"Queueing [Depth {depth+1}]: {normalized_link}")

        except Exception as e:
            logger.error(f"Failed to parse HTML {url}: {e}")
    else:
        logger.debug(f"Skipping non-HTML/PDF content type '{content_type}' at {url}")

    return url, extracted_text, new_links_to_add