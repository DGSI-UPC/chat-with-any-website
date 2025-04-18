from bs4 import BeautifulSoup
import logging
from typing import List, Tuple, Set
from urllib.parse import urljoin, urlparse
from .utils import normalize_url, is_internal_url, clean_text

logger = logging.getLogger(__name__)

# Elements to ignore when extracting text
IGNORE_TAGS = ['script', 'style', 'nav', 'footer', 'aside', 'header', 'head', 'meta', 'link', 'noscript']
# Potentially keep 'title' if needed

def parse_html_content(html_content: str, page_url: str, base_domain: str) -> Tuple[str, List[str]]:
    """
    Parses HTML content to extract main text and discover internal links.

    Returns:
        Tuple[str, List[str]]: (extracted_text, internal_links)
    """
    soup = BeautifulSoup(html_content, 'lxml') # Use lxml for speed
    extracted_text = ""
    internal_links = set()

    # 1. Extract Text
    # Remove ignored tags first
    for tag in soup(IGNORE_TAGS):
        tag.decompose()

    # Attempt to find the main content area (heuristics, might need improvement)
    main_content = soup.find('main') or soup.find('article') or soup.find('div', role='main') or soup.body
    if main_content:
        # Get text, try to preserve some structure with separators
        text_parts = main_content.find_all(string=True, recursive=True)
        extracted_text = ' '.join(part.strip() for part in text_parts if part.strip())
    else:
         logger.warning(f"Could not find main content area for {page_url}. Extracting from body.")
         if soup.body:
             text_parts = soup.body.find_all(string=True, recursive=True)
             extracted_text = ' '.join(part.strip() for part in text_parts if part.strip())


    # 2. Find Links
    for link in soup.find_all('a', href=True):
        href = link['href'].strip()
        if not href or href.startswith('#') or href.startswith('mailto:') or href.startswith('javascript:'):
            continue

        # Resolve relative URLs
        absolute_url = urljoin(page_url, href)
        normalized_abs_url = normalize_url(absolute_url)

        # Check if it's a valid HTTP/HTTPS URL and internal
        try:
            parsed_url = urlparse(normalized_abs_url)
            if parsed_url.scheme in ['http', 'https'] and is_internal_url(normalized_abs_url, base_domain):
                internal_links.add(normalized_abs_url)
        except ValueError:
            logger.warning(f"Could not parse URL: {href} found on {page_url}")

    cleaned_text = clean_text(extracted_text)
    logger.debug(f"Parsed {page_url}. Text length: {len(cleaned_text)}. Found {len(internal_links)} potential internal links.")

    return cleaned_text, list(internal_links)