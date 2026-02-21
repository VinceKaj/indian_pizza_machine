"""
Semantic similarity filtering for market selection.
Uses sentence transformers to rank and filter input markets by relevance.
"""
import logging
from sentence_transformers import SentenceTransformer, util
import torch

logger = logging.getLogger(__name__)

# Load semantic similarity model once (lazy loading)
_semantic_model = None


def get_semantic_model():
    """Lazy load the sentence transformer model."""
    global _semantic_model
    if _semantic_model is None:
        logger.info("Loading sentence transformer model 'all-MiniLM-L6-v2' (first time may take a moment)...")
        _semantic_model = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("Model loaded successfully!")
    return _semantic_model


def filter_by_semantic_similarity(target_question, candidate_dict, top_k=10, min_similarity=0.4, verbose=False):
    """
    Filter candidate markets by semantic similarity to target question.
    
    Args:
        target_question: The target market question
        candidate_dict: {market_id: "Market Question Text"}
        top_k: Number of top matches to return (default: 10)
        min_similarity: Minimum cosine similarity threshold (default: 0.4)
        verbose: Whether to print similarity scores
    
    Returns:
        List of top_k market IDs sorted by semantic similarity (above threshold)
    """
    logger.info(f"🔍 Filtering {len(candidate_dict)} candidates to top {top_k} by semantic similarity (threshold: {min_similarity})...")
    model = get_semantic_model()
    
    candidates = list(candidate_dict.values())
    market_ids = list(candidate_dict.keys())
    
    # Generate embeddings
    logger.info("Encoding target question...")
    target_embedding = model.encode(target_question, convert_to_tensor=True)
    
    logger.info(f"Encoding {len(candidates)} candidate questions...")
    candidate_embeddings = model.encode(candidates, convert_to_tensor=True)
    
    # Calculate cosine similarity
    logger.info("Computing cosine similarity scores...")
    cosine_scores = util.cos_sim(target_embedding, candidate_embeddings)[0]
    
    # Get top k indices
    k = min(top_k, len(candidates))
    top_results = torch.topk(cosine_scores, k=k)
    
    # Filter by similarity threshold
    filtered_results = [(score, idx) for score, idx in zip(top_results.values, top_results.indices) if score >= min_similarity]
    
    if len(filtered_results) < len(top_results.values):
        logger.warning(f"⚠️  {len(top_results.values) - len(filtered_results)} market(s) excluded due to similarity < {min_similarity}")
    
    logger.info(f"✅ Selected {len(filtered_results)} markets above {min_similarity} threshold:")
    for idx, (score, i) in enumerate(filtered_results):
        market_id = market_ids[i]
        question = candidates[i]
        logger.info(f"  {idx+1}. [{score:.4f}] {question[:80]}...")
    
    return [market_ids[i] for score, i in filtered_results]
