"""
LLM-based basket creation without a target market.
Uses OpenAI to identify themes and assign weights.
"""
import os
import logging
import requests
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


def get_clob_token_ids(market_id):
    """Fetch CLOB token IDs and metadata from a Polymarket market ID."""
    url = f"https://gamma-api.polymarket.com/markets/{market_id}"
    response = requests.get(url)
    
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch market {market_id}: {response.status_code}")
    
    data = response.json()
    clob_ids = data.get('clobTokenIds', [])
    
    if isinstance(clob_ids, str):
        import json
        clob_ids = json.loads(clob_ids)
    
    if len(clob_ids) < 2:
        raise ValueError(f"Market {market_id} doesn't have CLOB token IDs")
    
    return clob_ids[0], clob_ids[1], data.get('question', 'Unknown'), data.get('description', '')


def build_basket_llm_no_target(input_market_ids, top_k=10):
    """
    Build a basket without a target market using LLM to identify themes and assign weights.
    
    Args:
        input_market_ids: List of Polymarket market IDs
        top_k: Maximum number of markets to include (default: 10)
    
    Returns:
        dict with {weights: [...], theme: str, total_markets: int}
    """
    logger.info(f"🚀 Creating LLM basket without target from {len(input_market_ids)} input markets")
    
    # 1. Fetch market metadata
    logger.info(f"[1/2] 📥 Fetching market metadata...")
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
    
    # 2. Use LLM to identify theme and assign weights
    logger.info(f"[2/2] 🧠 Asking LLM to identify theme and calculate weights...")
    
    api_key = os.environ.get("openai_key") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OpenAI API key not found. Set 'openai_key' in .env file")
    
    client = OpenAI(api_key=api_key)
    
    # Format candidate data for prompt
    candidates_text = ""
    for m_id, info in candidate_dict.items():
        question = info.get('question', '')
        description = info.get('description', '')
        candidates_text += f"ID: {m_id}\nTitle: {question}\nRules: {description}\n\n"
    
    prompt = f"""
You are a quantitative researcher analyzing prediction markets.

Below is a collection of markets. Your task is to:
1. Identify the PRIMARY THEME that connects these markets (e.g., "Elon Musk's ventures", "AI advancement", "US Politics")
2. Select up to {top_k} markets that best represent this theme
3. Assign weights (0.0 to 1.0) based on each market's CENTRALITY to the theme
4. Weights must sum to exactly 1.0
5. Explain the reasoning for each weight

Markets with low relevance to the main theme should receive 0.0 weight.

CANDIDATE MARKETS:
{candidates_text}

Identify the coherent theme and create a focused basket around it.
"""
    
    # Define response schema
    class MarketWeightWithTheme(BaseModel):
        market_id: str = Field(description="The exact ID of the candidate market")
        weight: float = Field(description="Weight between 0.0 and 1.0 based on centrality to theme")
        reasoning: str = Field(description="One sentence explaining relevance to the theme")
    
    class BasketWithTheme(BaseModel):
        theme: str = Field(description="The primary theme connecting these markets (1-2 sentences)")
        basket: list[MarketWeightWithTheme] = Field(description="List of weighted markets, sum must equal 1.0")
    
    response = client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a thematic market analyst identifying coherent investment themes."},
            {"role": "user", "content": prompt}
        ],
        response_format=BasketWithTheme,
        temperature=0.0
    )
    
    result = response.choices[0].message.parsed
    
    # Process results
    weights_output = []
    total_weight = 0.0
    
    logger.info(f"🎯 THEME IDENTIFIED: {result.theme}")
    logger.info("Weights:")
    
    for item in result.basket:
        if item.weight > 0:
            title = candidate_dict.get(item.market_id, {}).get('question', 'Unknown')
            logger.info(f"  {item.weight:+.6f} | {title[:60]}...")
            logger.info(f"    Reasoning: {item.reasoning}")
            
            weights_output.append({
                "title": title,
                "market_id": item.market_id,
                "weight": item.weight,
                "reasoning": item.reasoning
            })
            total_weight += item.weight
    
    # Normalize weights
    if total_weight > 0:
        for w in weights_output:
            w["weight"] = w["weight"] / total_weight
    
    logger.info(f"✅ LLM basket created successfully! Total markets: {len(weights_output)}")
    
    return {
        "weights": weights_output,
        "theme": result.theme,
        "total_markets": len(weights_output)
    }
