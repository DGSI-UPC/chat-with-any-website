import re
from urllib.parse import urlparse, urljoin
import logging
import hashlib
import mimetypes
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Basic text cleaning: replace multiple whitespace chars with a single space
def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def normalize_url(url: str) -> str:
    """Normalize URL to avoid duplicates (e.g., remove fragment, trailing slash)."""
    try:
        parts = urlparse(url)
        # Rebuild without fragment, ensure path exists
        path = parts.path if parts.path else '/'
        if path.endswith('/') and len(path) > 1:
             path = path[:-1] # Remove trailing slash unless it's just '/'
        # Convert scheme and netloc to lowercase
        normalized = f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"
        if parts.query:
            normalized += f"?{parts.query}" # Keep query params for now
        return normalized
    except Exception:
        return url # Return original if parsing fails

def get_base_url(url: str) -> Optional[str]:
    """Extracts the base URL (scheme://netloc)."""
    try:
        parts = urlparse(url)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme.lower()}://{parts.netloc.lower()}"
        return None
    except Exception:
        return None

def is_internal_url(url: str, base_domain: str) -> bool:
    """Checks if a URL belongs to the same domain."""
    try:
        url_domain = urlparse(url).netloc.lower()
        return url_domain == base_domain
    except Exception:
        return False

def generate_unique_id(content: str) -> str:
    """Generates a unique ID for a content chunk."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def guess_mimetype(url: str) -> Optional[str]:
     """Guess MIME type from URL extension."""
     mimetype, _ = mimetypes.guess_type(url)
     return mimetype

def get_content_type(headers: dict) -> Optional[str]:
    """Extract content type from HTTP headers."""
    content_type = headers.get('content-type', '').lower()
    return content_type.split(';')[0].strip() # Remove charset info etc.