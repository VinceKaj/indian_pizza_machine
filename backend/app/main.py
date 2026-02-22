"""
FastAPI backend with an auto-updating exposed endpoint.
Data is refreshed in the background; GET /api/updates returns the latest snapshot.
"""
import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from create_basket import build_synthetic_basket
from create_basket_no_target import build_basket_no_target
from basket_llm_no_target import build_basket_llm_no_target

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# In-memory store updated by the background task
_updates: dict[str, Any] = {
    "last_updated": None,
    "version": 0,
    "data": [],
}


async def _refresh_updates() -> None:
    """Refresh the shared updates payload (runs periodically)."""
    global _updates
    _updates["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
    _updates["version"] = _updates.get("version", 0) + 1
    # Placeholder: replace with real Polymarket/arb data later
    _updates["data"] = [
        {"id": f"item-{_updates['version']}", "label": "Sample", "updated_at": _updates["last_updated"]},
    ]


async def _background_updater(interval_seconds: float = 10.0) -> None:
    """Loop that periodically refreshes the exposed data."""
    while True:
        await _refresh_updates()
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background auto-update task on startup; cancel on shutdown."""
    await _refresh_updates()
    task = asyncio.create_task(_background_updater(interval_seconds=10.0))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Polymarket Arb API",
    description="Backend for probability and arbitrage from related bets.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check."""
    return {"status": "ok"}


@app.get("/api/updates")
async def get_updates() -> dict[str, Any]:
    """
    Auto-updating endpoint: returns the latest snapshot of data.
    The server refreshes this data in the background every 10 seconds.
    Poll this endpoint to get updated values.
    """
    return _updates.copy()


class BasketRequest(BaseModel):
    target_market_id: str
    input_market_ids: list[str]
    days: int = 7
    use_semantic_filter: bool = True
    top_k_semantic: int = 10
    min_similarity: float = 0.4


@app.post("/api/basket")
async def create_basket(request: BasketRequest) -> dict[str, Any]:
    """
    Create a synthetic basket from a target market and input markets.
    
    Args:
        target_market_id: Polymarket market ID for the target
        input_market_ids: List of Polymarket market IDs for inputs
        days: Number of days of historical data to use (default: 7)
        use_semantic_filter: Filter inputs by semantic similarity (default: True)
        top_k_semantic: Number of top semantically similar markets to keep (default: 10)
        min_similarity: Minimum cosine similarity threshold (default: 0.4)
    
    Returns:
        {
            "target_prices": [float, ...],
            "synthetic_prices": [float, ...],
            "weights": [{"title": str, "market_id": str, "weight": float}, ...],
            "r_squared": float,
            "timestamps": [str, ...],
            "target_question": str
        }
    """
    try:
        result = build_synthetic_basket(
            target_market_id=request.target_market_id,
            input_market_ids=request.input_market_ids,
            days=request.days,
            verbose=False,
            use_semantic_filter=request.use_semantic_filter,
            top_k_semantic=request.top_k_semantic,
            min_similarity=request.min_similarity
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BasketNoTargetRequest(BaseModel):
    input_market_ids: list[str]
    top_k: int = 10
    temperature: float = 1.0
    use_diversity_filter: bool = True
    max_pairwise_similarity: float = 0.85


@app.post("/api/basket-no-target")
async def create_basket_no_target_endpoint(request: BasketNoTargetRequest) -> dict[str, Any]:
    """
    Create a basket without a target market using semantic similarity and softmax weighting.
    
    Weights are computed as:
    w_i = exp(S_i / T) / sum(exp(S_j / T))
    where S_i is the similarity of market i to the centroid embedding.
    
    Args:
        input_market_ids: List of Polymarket market IDs
        top_k: Maximum number of markets to include (default: 10)
        temperature: Softmax temperature parameter (default: 1.0, higher = more uniform weights)
        use_diversity_filter: Apply diversity filtering to avoid redundant markets (default: True)
        max_pairwise_similarity: Maximum allowed similarity between selected markets (default: 0.85)
    
    Returns:
        {
            "weights": [{"title": str, "market_id": str, "weight": float, "similarity": float}, ...],
            "total_markets": int,
            "centroid_question": str,
            "temperature": float
        }
    """
    try:
        result = build_basket_no_target(
            input_market_ids=request.input_market_ids,
            top_k=request.top_k,
            temperature=request.temperature,
            use_diversity_filter=request.use_diversity_filter,
            max_pairwise_similarity=request.max_pairwise_similarity
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BasketLLMNoTargetRequest(BaseModel):
    input_market_ids: list[str]
    top_k: int = 10


@app.post("/api/basket-llm-no-target")
async def create_basket_llm_no_target_endpoint(request: BasketLLMNoTargetRequest) -> dict[str, Any]:
    """
    Create a basket without a target market using OpenAI LLM to identify themes and assign weights.
    
    The LLM analyzes the markets, identifies a coherent theme, and assigns weights based on
    each market's centrality to that theme.
    
    Args:
        input_market_ids: List of Polymarket market IDs
        top_k: Maximum number of markets to include (default: 10)
    
    Returns:
        {
            "weights": [{"title": str, "market_id": str, "weight": float, "reasoning": str}, ...],
            "theme": str,
            "total_markets": int
        }
    """
    try:
        result = build_basket_llm_no_target(
            input_market_ids=request.input_market_ids,
            top_k=request.top_k
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
