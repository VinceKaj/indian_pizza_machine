import logging
import warnings
from sentence_transformers import SentenceTransformer, util
import torch

# Suppress transformers model loading warnings
import os
os.environ['TRANSFORMERS_VERBOSITY'] = 'error'

logger = logging.getLogger(__name__)

_semantic_model = None

def get_semantic_model():
    """Lazy load the sentence transformer model."""
    global _semantic_model
    if _semantic_model is None:
        logger.info("Loading sentence transformer model 'all-MiniLM-L6-v2'...")
        
        # Suppress transformer library warnings during model load
        import transformers
        transformers.logging.set_verbosity_error()
        
        _semantic_model = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("Model loaded successfully!")
    return _semantic_model

def filter_by_semantic_similarity(target_question, candidate_dict, top_k=10, 
                                  min_similarity=0.4, max_pairwise_similarity=0.85, 
                                  verbose=False):
    """
    Filter candidate markets by semantic similarity to target question, 
    while forcing diversity by excluding highly redundant markets.
    
    Args:
        target_question: The target market question
        candidate_dict: {market_id: "Market Question Text"}
        top_k: Number of top matches to return (default: 10)
        min_similarity: Minimum similarity to the target (default: 0.4)
        max_pairwise_similarity: Maximum allowed similarity between selected inputs (default: 0.85)
    """
    logger.info(f"🔍 Filtering {len(candidate_dict)} candidates to top {top_k}...")
    model = get_semantic_model()
    
    candidates = list(candidate_dict.values())
    market_ids = list(candidate_dict.keys())
    
    # 1. Generate embeddings
    target_embedding = model.encode(target_question, convert_to_tensor=True)
    candidate_embeddings = model.encode(candidates, convert_to_tensor=True)
    
    # 2. Calculate cosine similarity to the TARGET
    cosine_scores = util.cos_sim(target_embedding, candidate_embeddings)[0]
    
    # 3. Sort candidates from most relevant to least relevant
    sorted_indices = torch.argsort(cosine_scores, descending=True)
    
    selected_indices = []
    selected_scores = []
    
    # 4. Greedy Diversity Selection
    for idx in sorted_indices:
        score = cosine_scores[idx].item()
        
        # Stop immediately if the best remaining candidate is below target threshold
        if score < min_similarity:
            break
            
        candidate_emb = candidate_embeddings[idx]
        is_redundant = False
        
        # Check similarity against ALREADY SELECTED markets
        if selected_indices:
            # Stack the embeddings of markets we've already approved
            selected_tensor = candidate_embeddings[selected_indices]
            
            # Compare current candidate to all approved candidates
            redundancy_scores = util.cos_sim(candidate_emb, selected_tensor)[0]
            max_redundancy = torch.max(redundancy_scores).item()
            
            # If it's too similar to something we already have, skip it
            if max_redundancy > max_pairwise_similarity:
                if verbose:
                    logger.info(f"  ❌ Skipping: [{score:.4f}] {candidates[idx][:50]}... "
                                f"(Redundancy: {max_redundancy:.4f})")
                continue
                
        # If it passes the redundancy check, add it to our final basket
        selected_indices.append(idx.item())
        selected_scores.append(score)
        
        if len(selected_indices) == top_k:
            break

    logger.info(f"✅ Selected {len(selected_indices)} diverse markets:")
    for score, idx in zip(selected_scores, selected_indices):
        logger.info(f"  [{score:.4f}] {candidates[idx]}")
    
    return [market_ids[i] for i in selected_indices]