import os
import json
import logging
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# 1. Define the exact JSON schema you want the LLM to return
class MarketWeight(BaseModel):
    market_id: str = Field(description="The exact ID of the candidate market.")
    weight: float = Field(description="Decimal weight between 0.0 and 1.0. Must reflect predictive power.")
    reasoning: str = Field(description="A 1-sentence explanation of the causal link.")

class BasketDistribution(BaseModel):
    basket: list[MarketWeight] = Field(description="List of weights. The sum of all weights MUST equal exactly 1.0.")

def get_llm_predictive_weights(target_question, candidate_dict):
    """
    candidate_dict format: {market_id: {"question": "...", "description": "..."}}
    """
    api_key = os.environ.get("openai_key") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OpenAI API key not found. Set 'openai_key' in .env file")
    
    client = OpenAI(api_key=api_key)
    
    # 2. Format the candidate data for the prompt
    candidates_text = ""
    for m_id, info in candidate_dict.items():
        candidates_text += f"ID: {m_id} | Title: {info['question']} | Rules: {info['description']}\n"
        
    prompt = f"""
    You are a quantitative researcher building a synthetic prediction market ETF.
    The target market we want to track is: "{target_question}"
    
    Below is a list of existing candidate markets. 
    Assign a percentage weight (0.0 to 1.0) to each candidate based strictly on its CAUSAL PREDICTIVE POWER to the target, not just keyword overlap. 
    If a market is irrelevant or spuriously correlated, give it a weight of 0.0. 
    The total sum of all weights must equal exactly 1.0.
    
    CANDIDATES:
    {candidates_text}
    """
    
    logger.info("🧠 Asking LLM to calculate predictive weights...")
    
    # 3. Force the LLM to reply using your Pydantic schema
    response = client.beta.chat.completions.parse(
        model="gpt-4o", # Or gemini-1.5-pro if using the Google SDK
        messages=[
            {"role": "system", "content": "You are a precise financial pricing engine."},
            {"role": "user", "content": prompt}
        ],
        response_format=BasketDistribution,
        temperature=0.0 # Zero temperature for maximum determinism
    )
    
    # 4. Extract the cleanly parsed Python dictionary
    result = response.choices[0].message.parsed
    
    # 5. Clean up and verify the math
    weights_output = []
    total_weight = 0.0
    
    for item in result.basket:
        if item.weight > 0:
            title = candidate_dict.get(item.market_id, {}).get('question', 'Unknown')
            weights_output.append({
                "title": title,
                "market_id": item.market_id,
                "weight": item.weight,
                "reasoning": item.reasoning
            })
            total_weight += item.weight
            
    # Normalize mathematically just in case the LLM was slightly off (e.g., sum is 0.99)
    if total_weight > 0:
        for w in weights_output:
            w["weight"] = w["weight"] / total_weight

    return weights_output