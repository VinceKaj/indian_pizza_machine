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
