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
                                  verbose=False, target_description="", max_target_similarity=0.95):
    """
    Filter candidate markets by semantic similarity to target question, 
    while forcing diversity by excluding highly redundant markets.
    
    Args:
        target_question: The target market question
        candidate_dict: {market_id: {"question": "...", "description": "..."}} or {market_id: "question_text"}
        top_k: Number of top matches to return (default: 10)
        min_similarity: Minimum similarity to the target (default: 0.4)
        max_pairwise_similarity: Maximum allowed similarity between selected inputs (default: 0.85)
        verbose: Whether to print detailed logs (default: False)
        target_description: Optional target market description for deeper similarity (default: "")
        max_target_similarity: Maximum similarity to target - filters out near-duplicates (default: 0.95)
    """
    logger.info(f"🔍 Filtering {len(candidate_dict)} candidates to top {top_k} (using Title + Description)...")
    model = get_semantic_model()
    
    market_ids = list(candidate_dict.keys())
    
    # Handle both old format (string) and new format (dict with question/description)
    candidate_texts = []
    candidate_questions = []
    for market_id in market_ids:
        value = candidate_dict[market_id]
        if isinstance(value, dict):
            # New format with description
            question = value.get('question', '')
            description = value.get('description', '')
            candidate_texts.append(f"Title: {question}\nResolution Rules: {description}")
            candidate_questions.append(question)
        else:
            # Old format (backward compatibility)
            candidate_texts.append(f"Title: {value}")
            candidate_questions.append(value)
    
    # 1. Generate embeddings using full text (Title + Description)
    target_text = f"Title: {target_question}\nResolution Rules: {target_description}"
    target_embedding = model.encode(target_text, convert_to_tensor=True)
    candidate_embeddings = model.encode(candidate_texts, convert_to_tensor=True)
    
    # 2. Calculate cosine similarity to the TARGET
    cosine_scores = util.cos_sim(target_embedding, candidate_embeddings)[0]
    
    # 2.5. Filter out near-duplicates (markets TOO similar to the target)
    valid_indices = []
    excluded_count = 0
    for idx, score in enumerate(cosine_scores):
        score_val = score.item()
        if score_val > max_target_similarity:
            logger.info(f"  ❌ Excluding near-duplicate (sim={score_val:.4f}): {candidate_questions[idx][:60]}...")
            excluded_count += 1
        else:
            valid_indices.append(idx)
    
    if excluded_count > 0:
        logger.info(f"Excluded {excluded_count} near-duplicate markets, {len(valid_indices)} remaining")
    
    # If all candidates were filtered out, return empty
    if not valid_indices:
        logger.warning("All candidates were filtered out as near-duplicates!")
        return []
    
    # 3. Sort candidates from most relevant to least relevant (only valid ones)
    valid_scores = cosine_scores[valid_indices]
    sorted_order = torch.argsort(valid_scores, descending=True)
    sorted_indices = [valid_indices[i] for i in sorted_order]
    
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
                    logger.info(f"  ❌ Skipping: [{score:.4f}] {candidate_questions[idx][:50]}... "
                                f"(Redundancy: {max_redundancy:.4f})")
                continue
                
        # If it passes the redundancy check, add it to our final basket
        selected_indices.append(idx.item())
        selected_scores.append(score)
        
        if len(selected_indices) == top_k:
            break

    logger.info(f"✅ Selected {len(selected_indices)} diverse markets:")
    for score, idx in zip(selected_scores, selected_indices):
        logger.info(f"  [{score:.4f}] {candidate_questions[idx]}")
    
    return [market_ids[i] for i in selected_indices]