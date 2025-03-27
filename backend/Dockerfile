# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies required for Tesseract OCR and pdf2image
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     tesseract-ocr \
#     libtesseract-dev \
#     tesseract-ocr-eng \ # English language pack, add others if needed (e.g., tesseract-ocr-spa)
#     poppler-utils \ # Provides pdftoppm needed by pdf2image
#     curl \ # Often useful for debugging
#     build-essential \ # Needed if some pip packages compile C extensions
#     && apt-get clean \
#     && rm -rf /var/lib/apt/lists/*

# Install system dependencies required for Tesseract OCR, pdf2image and PyPDFium2
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    pkg-config \
    libopenjp2-7 \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry (Optional, but good practice) - If not using Poetry, skip this section
# RUN curl -sSL https://install.python-poetry.org | python3 -
# ENV PATH="/root/.local/bin:$PATH"

# Copy dependency definition files
COPY ./requirements.txt /app/requirements.txt
# If using Poetry:
# COPY ./pyproject.toml ./poetry.lock* /app/

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
# If using Poetry:
# RUN poetry config virtualenvs.create false && poetry install --no-dev --no-interaction --no-ansi

# Copy the rest of the application code
COPY ./app /app/app
COPY .env /app/.env

# Make port 80 available to the world outside this container
EXPOSE 8000

# Define environment variable from .env (example, usually set in docker-compose)
# ENV OPENAI_API_KEY=${OPENAI_API_KEY}

# Run Uvicorn server
# Use --reload for development ONLY, remove for production
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# For development with auto-reload:
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]