import re
import logging
from .vector_store import add_semantic_concept, find_semantic_concepts
from typing import List, Dict, Set

logger = logging.getLogger(__name__)

# Simple Regex for potential acronyms (e.g., 3+ uppercase letters)
# and potentially capitalized phrases (e.g., sequences of capitalized words)
ACRONYM_REGEX = re.compile(r'\b([A-Z]{3,})\b')
# Simple capitalized phrase regex (might catch too much)
CAPITALIZED_PHRASE_REGEX = re.compile(r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\b')

# Simple regex for splitting query into words
WORD_SPLIT_REGEX = re.compile(r'\b\w+\b')


def extract_and_store_concepts(text_chunk: str, source_url: str, extracted_concepts: Set[str]):
    """
    Extracts potential concepts (acronyms, capitalized phrases) from a text chunk
    and stores them with a definition snippet. Avoids duplicates per scrape job.
    """
    # Find acronyms
    for match in ACRONYM_REGEX.finditer(text_chunk):
        term = match.group(1)
        if term.lower() not in extracted_concepts:
            context_window = 150 # Characters around the term
            start = max(0, match.start() - context_window)
            end = min(len(text_chunk), match.end() + context_window)
            definition_snippet = text_chunk[start:end].strip().replace("\n", " ")
            if add_semantic_concept(term, definition_snippet, source_url):
                 extracted_concepts.add(term.lower())

    # Find capitalized phrases (less reliable) - Use with caution
    # for match in CAPITALIZED_PHRASE_REGEX.finditer(text_chunk):
    #     term = match.group(1)
    #     if term.lower() not in extracted_concepts and len(term.split()) <= 5: # Limit phrase length
    #         context_window = 100
    #         start = max(0, match.start() - context_window)
    #         end = min(len(text_chunk), match.end() + context_window)
    #         definition_snippet = text_chunk[start:end].strip().replace("\n", " ")
    #         if add_semantic_concept(term, definition_snippet, source_url):
    #              extracted_concepts.add(term.lower())


def augment_query_with_semantics(query: str) -> str:
    """
    Augments the user query with definitions of potential concepts found in it.
    """
    words = WORD_SPLIT_REGEX.findall(query)
    if not words:
        return ""

    found_concepts = find_semantic_concepts(words)

    if not found_concepts:
        return ""

    augmentation_parts = []
    for word, concept_data in found_concepts.items():
        augmentation_parts.append(f"- {concept_data['term']}: {concept_data['definition']} (Source: {concept_data['source_url']})")

    if augmentation_parts:
        return "Semantic Context:\n" + "\n".join(augmentation_parts) + "\n---"
    else:
        return ""