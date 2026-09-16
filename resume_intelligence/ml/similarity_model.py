# -*- coding: utf-8 -*-
import logging
import numpy as np

logger = logging.getLogger(__name__)

# Global model cache to avoid reloading on every request
_EMBEDDING_MODEL = None

def get_sentence_transformer():
    """Lazy load SentenceTransformer model for fast dense inference."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _EMBEDDING_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Loaded SentenceTransformer ('all-MiniLM-L6-v2') successfully.")
        except Exception as e:
            logger.warning(f"Could not load SentenceTransformer: {e}. Falling back to TF-IDF.")
            _EMBEDDING_MODEL = False
    return _EMBEDDING_MODEL

def compute_semantic_similarity(text_a, text_b):
    """
    Computes semantic cosine similarity (0.0 to 1.0) between two text blocks.
    Uses dense embeddings with automatic fallback to TF-IDF cosine similarity.
    """
    if not text_a or not text_b:
        return 0.0
        
    model = get_sentence_transformer()
    if model:
        try:
            embeddings = model.encode([text_a, text_b], convert_to_numpy=True, normalize_embeddings=True)
            cosine_sim = float(np.dot(embeddings[0], embeddings[1]))
            return max(0.0, min(1.0, cosine_sim))
        except Exception as e:
            logger.error(f"Dense embedding calculation error: {e}")
            
    # TF-IDF Cosine Similarity Fallback
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        vec = TfidfVectorizer(stop_words='english', max_features=5000)
        tfidf = vec.fit_transform([text_a, text_b])
        sim = float(cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0])
        return max(0.0, min(1.0, sim))
    except Exception as err:
        logger.error(f"TF-IDF fallback error: {err}")
        return 0.5
