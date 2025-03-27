import logging
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional

from ..core.db import SemanticTerm, semantic_term_association
from ..models.schemas import SemanticTermCreate

logger = logging.getLogger(__name__)

def add_semantic_term(db: Session, term_data: SemanticTermCreate) -> SemanticTerm:
    """Adds a new semantic term and its relationships."""
    # Check if term already exists
    db_term = db.query(SemanticTerm).filter(SemanticTerm.term == term_data.term).first()
    if db_term:
        logger.warning(f"Term '{term_data.term}' already exists. Updating explanation.")
        db_term.explanation = term_data.explanation
    else:
        db_term = SemanticTerm(term=term_data.term, explanation=term_data.explanation)
        db.add(db_term)
        db.flush() # Need the ID for relationships

    # Handle relationships
    current_related_ids = {t.id for t in db_term.related_terms}
    new_related_ids = set(term_data.related_term_ids)

    # Add new relationships
    ids_to_add = new_related_ids - current_related_ids
    for related_id in ids_to_add:
        related_term = db.query(SemanticTerm).get(related_id)
        if related_term:
            db_term.related_terms.append(related_term)
            related_term.related_terms.append(db_term) # Make relationship symmetric
            logger.info(f"Linked '{db_term.term}' and '{related_term.term}'")
        else:
             logger.warning(f"Cannot link term '{db_term.term}': Related term ID {related_id} not found.")

    # Remove old relationships (optional, uncomment if needed)
    # ids_to_remove = current_related_ids - new_related_ids
    # for related_id in ids_to_remove:
    #     related_term = db.query(SemanticTerm).get(related_id)
    #     if related_term in db_term.related_terms:
    #         db_term.related_terms.remove(related_term)
    #     if db_term in related_term.related_terms:
    #         related_term.related_terms.remove(db_term)

    db.commit()
    db.refresh(db_term)
    logger.info(f"Successfully added/updated semantic term: '{db_term.term}'")
    return db_term


def get_semantic_info(db: Session, term_text: str, max_depth: int = 1) -> Optional[SemanticTerm]:
    """
    Retrieves a semantic term and its related terms up to a specified depth.
    Uses eager loading to fetch relationships efficiently.
    """
    # Build the query with eager loading options based on depth
    options = joinedload(SemanticTerm.related_terms)
    current_option = options
    for _ in range(1, max_depth): # Depth 1 means load direct relations, Depth 2 means relations of relations etc.
        current_option = current_option.joinedload(SemanticTerm.related_terms)
        options = options.options(current_option) # Chain the options

    term = db.query(SemanticTerm).options(options).filter(SemanticTerm.term == term_text).first()
    return term


def find_terms_in_text(db: Session, text: str, max_depth: int = 1) -> List[SemanticTerm]:
    """
    Placeholder: Finds known semantic terms within a given text.
    A real implementation would use more sophisticated NLP (e.g., tokenization, stemming, NER).
    This version does a simple substring check against all known terms.
    """
    # Inefficient for large number of terms. Consider Aho-Corasick or other algorithms.
    all_terms = db.query(SemanticTerm.term).all()
    found_terms_data = []
    processed_terms = set() # Avoid duplicates if a term appears multiple times

    text_lower = text.lower()
    for term_tuple in all_terms:
        term_str = term_tuple[0]
        if term_str.lower() in text_lower and term_str not in processed_terms:
             term_info = get_semantic_info(db, term_str, max_depth)
             if term_info:
                 found_terms_data.append(term_info)
                 processed_terms.add(term_str) # Mark as processed

    logger.info(f"Found {len(found_terms_data)} semantic terms in text.")
    return found_terms_data

def format_semantic_context(terms: List[SemanticTerm], current_term: SemanticTerm, depth: int, max_depth: int) -> str:
    """Recursive helper to format semantic context."""
    if depth > max_depth:
        return ""

    context = f"Term: {current_term.term}\nExplanation: {current_term.explanation}\n"
    if current_term.related_terms and depth < max_depth:
        context += "Related Concepts:\n"
        for related in current_term.related_terms:
            # Basic check to avoid infinite recursion in case of cycles (though the query depth limit should handle it)
            if related.term not in [t.term for t in terms[:depth]]: # Check if we are looping back immediately
                nested_context = format_semantic_context(terms + [current_term], related, depth + 1, max_depth)
                if nested_context: # Add indentation for clarity
                    context += f"  - {nested_context.replace('Term:', 'Related Term:').replace('Explanation:', '  Explanation:')}" # Basic reformatting
                else:
                    context += f"  - {related.term}: {related.explanation}\n" # Max depth reached for this branch
            else:
                context += f"  - {related.term} (already mentioned)\n"

    return context