import fitz # PyMuPDF
import pytesseract
from PIL import Image
import io
import logging
from ..config import settings
from .utils import clean_text
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Set Tesseract command path if needed (especially in Docker)
if settings.TESSERACT_CMD and os.path.exists(settings.TESSERACT_CMD):
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD
else:
    logger.warning(f"Tesseract command path '{settings.TESSERACT_CMD}' not found or not set. OCR might fail.")


def extract_text_from_pdf(pdf_content: bytes, source_url: str) -> Optional[str]:
    """
    Extracts text from PDF content, using OCR as a fallback for images or scanned PDFs.
    Supports English, Spanish, and Catalan OCR.
    """
    full_text = ""
    try:
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        logger.info(f"Opened PDF {source_url} with {len(doc)} pages.")

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            page_text = page.get_text("text", sort=True).strip() # Try direct extraction first, sorted

            if len(page_text) < 50: # Heuristic: If very little text extracted, try OCR
                logger.warning(f"Page {page_num+1}/{len(doc)} of {source_url} has little text ({len(page_text)} chars). Attempting OCR.")
                # Use higher DPI for better OCR results
                pix = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_bytes))

                try:
                     # Specify multiple languages for Tesseract
                    ocr_text = pytesseract.image_to_string(img, lang='eng+spa+cat', config='--psm 6') # PSM 6: Assume a single uniform block of text.
                    page_text = ocr_text.strip()
                    logger.info(f"OCR successful for page {page_num+1} of {source_url}. Extracted {len(page_text)} chars.")
                except pytesseract.TesseractNotFoundError:
                    logger.error("Tesseract is not installed or not in PATH. OCR failed.")
                    # Continue with potentially empty page_text
                except Exception as ocr_err:
                    logger.error(f"Tesseract OCR error on page {page_num+1} of {source_url}: {ocr_err}", exc_info=True)
                    # Continue with potentially empty page_text

            full_text += page_text + "\n\n" # Add page separator

        doc.close()
        cleaned_full_text = clean_text(full_text)
        logger.info(f"Successfully processed PDF {source_url}. Total text length: {len(cleaned_full_text)} chars.")
        return cleaned_full_text

    except fitz.fitz.FitzError as pdf_err:
        logger.error(f"PyMuPDF error processing PDF {source_url}: {pdf_err}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing PDF {source_url}: {e}", exc_info=True)
        return None