"""
Create a basket without a target market.
Uses high-fidelity semantic similarity (Title + Description) and softmax weighting.
"""
import pandas as pd
import numpy as np
import requests
import logging
import torch

# Assuming get_semantic_model now loads BAAI/bge-large-en-v1.5
from app.filter_inputs import get_semantic_model
from sentence_transformers import util

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_clob_token_ids(market_id):
    """
    Fetch CLOB token IDs and metadata from a Polymarket market ID.
    Returns (yes_token_id, no_token_id, market_question, market_description)
    """
    url = f"https://gamma-api.polymarket.com/markets/{market_id}"
    response = requests.get(url)
    
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch market {market_id}: {response.status_code}")
    
    data = response.json()
    clob_ids = data.get('clobTokenIds', [])
    
    # Handle case where clobTokenIds might be a JSON string
    if isinstance(clob_ids, str):
        import json
        clob_ids = json.loads(clob_ids)
    
    if len(clob_ids) < 2:
        raise ValueError(f"Market {market_id} doesn't have CLOB token IDs")
    
    return clob_ids[0], clob_ids[1], data.get('question', 'Unknown'), data.get('description', '')


def apply_diversity_filter(candidate_dict, top_k=10, max_pairwise_similarity=0.85):
    """
    Apply diversity filtering to select up to top_k diverse markets using full descriptions.
    
    Args:
        candidate_dict: {market_id: {"question": "...", "description": "..."}}
    """
    logger.info(f"🔍 Applying high-fidelity diversity filter to {len(candidate_dict)} candidates (max: {top_k})...")
    
    if len(candidate_dict) <= top_k:
        logger.info(f"All {len(candidate_dict)} markets selected (below threshold)")
        return list(candidate_dict.keys())
    
    model = get_semantic_model()
    market_ids = list(candidate_dict.keys())
    
    # Concatenate title and description for deep semantic footprint
    candidate_texts = [
        f"Title: {info.get('question', '')}\nResolution Rules: {info.get('description', '')}" 
        for info in candidate_dict.values()
    ]
    
    # Generate embeddings
    logger.info("Encoding candidate texts (Title + Description)...")
    candidate_embeddings = model.encode(candidate_texts, convert_to_tensor=True)
    
    # Compute centroid
    centroid = torch.mean(candidate_embeddings, dim=0)
    
    # Compute similarity to centroid
    centroid_similarities = util.cos_sim(centroid.unsqueeze(0), candidate_embeddings)[0]
    
    # Sort by centroid similarity (most representative first)
    sorted_indices = torch.argsort(centroid_similarities, descending=True)
    
    selected_indices = []
    
    # Greedy diversity selection
    for idx in sorted_indices:
        candidate_emb = candidate_embeddings[idx]
        title_only = list(candidate_dict.values())[idx].get('question', '')
        
        # Check similarity against already selected markets
        if selected_indices:
            selected_tensor = candidate_embeddings[selected_indices]
            redundancy_scores = util.cos_sim(candidate_emb, selected_tensor)[0]
            max_redundancy = torch.max(redundancy_scores).item()
            
            # Skip if too similar to existing selection
            if max_redundancy > max_pairwise_similarity:
                logger.info(f"  ❌ Skipping: {title_only[:50]}... (Redundancy: {max_redundancy:.4f})")
                continue
        
        selected_indices.append(idx.item())
        
        if len(selected_indices) == top_k:
            break
    
    logger.info(f"✅ Selected {len(selected_indices)} diverse markets")
    return [market_ids[i] for i in selected_indices]


def build_basket_no_target(input_market_ids, top_k=10, temperature=0.1, 
                           use_diversity_filter=True, max_pairwise_similarity=0.85):
    """
    Build a basket without a target market using deep semantic similarity and softmax weighting.
    """
    logger.info(f"🚀 Creating basket without target from {len(input_market_ids)} input markets")
    logger.info(f"📊 Parameters: top_k={top_k}, temperature={temperature}, diversity_filter={use_diversity_filter}")
    
    # 1. Fetch all candidate market metadata
    logger.info(f"[1/3] 📥 Fetching market metadata (including descriptions)...")
    candidate_dict = {}
    for market_id in input_market_ids:
        try:
            _, _, question, description = get_clob_token_ids(market_id)
            candidate_dict[market_id] = {
                'question': question,
                'description': description
            }
        except Exception as e:
            logger.warning(f"Failed to fetch market {market_id}: {e}")
    
    logger.info(f"Successfully fetched {len(candidate_dict)}/{len(input_market_ids)} markets")
    
    if len(candidate_dict) == 0:
        raise ValueError("No valid markets found")
    
    # 2. Apply diversity filtering if enabled
    if use_diversity_filter:
        logger.info(f"[2/3] 🎯 Applying diversity filtering...")
        selected_market_ids = apply_diversity_filter(
            candidate_dict, 
            top_k=top_k,
            max_pairwise_similarity=max_pairwise_similarity
        )
    else:
        # Just take first top_k
        selected_market_ids = list(candidate_dict.keys())[:top_k]
        logger.info(f"[2/3] Using first {len(selected_market_ids)} markets (no filtering)")
    
    # 3. Compute weights using semantic similarity and softmax
    logger.info(f"[3/3] 🧮 Computing softmax weights from deep semantic similarities...")
    
    model = get_semantic_model()
    
    selected_info = [candidate_dict[mid] for mid in selected_market_ids]
    selected_texts = [
        f"Title: {info.get('question', '')}\nResolution Rules: {info.get('description', '')}" 
        for info in selected_info
    ]
    
    # Encode selected markets
    embeddings = model.encode(selected_texts, convert_to_tensor=True)
    
    # Compute centroid (average embedding)
    centroid = torch.mean(embeddings, dim=0)
    
    # Compute similarity of each market to the centroid
    similarities = util.cos_sim(centroid.unsqueeze(0), embeddings)[0]
    
    # Apply softmax with temperature
    scaled_similarities = similarities / temperature
    weights_tensor = torch.softmax(scaled_similarities, dim=0)
    
    # Convert to numpy
    weights = weights_tensor.cpu().numpy()
    similarities_np = similarities.cpu().numpy()
    
    # Add lognormal noise so weights are more spread out (no-target case only)
    sigma = 0.5  # scale of lognormal noise
    lognormal_noise = np.exp(np.random.normal(0, sigma, size=weights.shape))
    weights = weights * lognormal_noise
    # Renormalize to sum to 1
    weights = weights / (weights.sum() or 1.0)
    
    # Find most representative question
    centroid_idx = int(torch.argmax(similarities).item())
    centroid_question = selected_info[centroid_idx].get('question', '')
    
    logger.info(f"✅ Basket created successfully!")
    logger.info(f"Centroid question: {centroid_question}")
    logger.info("Weights:")
    for i, mid in enumerate(selected_market_ids):
        title = selected_info[i].get('question', '')
        logger.info(f"  {weights[i]:+.6f} (sim: {similarities_np[i]:.4f}) | {title[:60]}...")
    
    # Format output for API (Only return the title to keep the JSON payload clean)
    weights_output = [
        {
            "title": selected_info[i].get('question', ''),
            "market_id": mid,
            "weight": float(weights[i]),
            "similarity": float(similarities_np[i])
        }
        for i, mid in enumerate(selected_market_ids)
    ]
    
    return {
        'weights': weights_output,
        'total_markets': len(selected_market_ids),
        'centroid_question': centroid_question,
        'temperature': temperature
    }