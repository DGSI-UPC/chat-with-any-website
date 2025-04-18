# Use Python 3.11 slim image
FROM python:3.11-slim

# Set environment variables to prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    # Tesseract language data path (adjust if needed based on base image)
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata

# Set working directory
WORKDIR /app

# Install system dependencies
# - build-essential: For compiling some Python packages if needed
# - tesseract-ocr: The OCR engine
# - language packs: For English, Spanish, Catalan
# - git: Might be needed for installing some pip packages directly from repos (e.g., sentence-transformers sometimes)
# - curl, other utils: Good to have for debugging
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-spa \
    tesseract-ocr-cat \
    git \
    curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Copy backend requirements first to leverage Docker cache
COPY ./backend/requirements.txt /app/backend/requirements.txt

# Install Python dependencies
# Using --no-cache-dir reduces image size
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend application code
COPY ./backend /app/backend

# Copy frontend application code
COPY ./frontend /app/frontend

# Expose the port the app runs on
EXPOSE 8000

# Define the command to run the application using uvicorn
# Use 0.0.0.0 to bind to all interfaces inside the container
# The entrypoint is backend.app.main:app
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]