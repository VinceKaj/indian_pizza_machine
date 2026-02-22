"""
FastAPI backend with an auto-updating exposed endpoint.
Data is refreshed in the background; GET /api/updates returns the latest snapshot.
Polymarket proxy: GET /api/polymarket?url=... returns market data so the frontend doesn't query Polymarket directly.
Semantic search: POST /api/search/semantic matches a prompt to Polymarket tags, fetches events per tag,
and for each event returns the most informative market (by MIS: volatility + log(1+volume) + recency).
"""
import asyncio
import json
import logging
import math
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from backend directory so NYTIMES_API_KEY etc. are available
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

logging.basicConfig(level=logging.INFO)
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

try:
    from app.graph import (
        init_driver,
        close_driver,
        clear_graph,
        ingest_polymarket,
        ingest_wikipedia,
        postprocess_merge_duplicate_entities,
        find_connections,
        find_indirect_datasources,
        search_nodes,
        graph_stats,
        find_related_by_paths,
        find_bfs_layers,
        IngestResponse,
        TraverseResponse,
        DatasourceResponse,
        SearchResponse,
        StatsResponse,
        PostprocessResponse,
        RelatedByPathsResponse,
        BFSLayersResponse,
    )
    _graph_available = True
except Exception as _graph_err:
    _graph_available = False
    _graph_err_msg = str(_graph_err)

from app.create_basket import build_synthetic_basket
from app.create_basket_no_target import build_basket_no_target
from app.basket_llm_no_target import build_basket_llm_no_target

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# In-memory store updated by the background task
_updates: dict[str, Any] = {
    "last_updated": None,
    "version": 0,
    "data": [],
}

# Sentence-transformer model (loaded once at startup)
_model: SentenceTransformer | None = None

# Cached Polymarket tags with pre-computed embeddings.
# Tags are discovered from events and refreshed every 30 min.
_tag_cache: dict[str, Any] = {
    "last_updated": None,
    "tags": [],          # list[dict] with keys: label, slug, id
    "embeddings": None,  # np.ndarray of shape (n_tags, embed_dim)
}

SKIP_TAGS = {"All", "Featured", "Parent For Derivative", "Hide From China", "Hide From New"}


class SemanticSearchRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Free-text query to match against Polymarket tags/markets")
    num_tags: int = Field(5, ge=1, le=15, description="Number of tags to match the prompt against")
    events_per_tag: int = Field(30, ge=1, le=100, description="Max events to fetch per matched tag")


class MatchedTag(BaseModel):
    label: str
    slug: str
    score: float


class EventSummary(BaseModel):
    event_id: str | None = None
    title: str | None = None
    slug: str | None = None
    description: str | None = None
    image: str | None = None
    active: bool | None = None
    end_date: str | None = None
    volume: float | None = None
    liquidity: float | None = None
    tags: list[str] = []
    markets_count: int = 0


class BestMarketSummary(BaseModel):
    """Most informative market for an event (by MIS): id and question only."""

    id: str
    question: str


class EventWithBestMarket(BaseModel):
    """One event with its single best market for inference (id + question)."""

    event_id: str
    event_title: str = ""
    best_market: BestMarketSummary | None = None


class WordSearchMarket(BaseModel):
    """One market from Polymarket word search (id + question)."""

    id: str
    question: str
    score: float | None = None


class BestMarketMatchRequest(BaseModel):
    """Request body for the single best-matching market by embedding."""

    prompt: str = Field(..., min_length=1, description="User prompt to match against market questions")


class BestMarketMatchResponse(BaseModel):
    """The single market whose question embedding is closest to the prompt, and its score."""

    market: BestMarketSummary | None = None
    match_score: float = 0.0


class TagBreakdown(BaseModel):
    """Per-tag statistics so the frontend can show the pipeline step-by-step."""

    tag_slug: str
    tag_label: str
    score: float
    events_count: int = 0
    total_markets: int = 0
    avg_markets_per_event: float = 0.0
    event_titles: list[str] = []


class SemanticSearchResponse(BaseModel):
    api_version: str = "tag-based"
    prompt: str
    matched_tags: list[MatchedTag]
    tag_breakdown: list[TagBreakdown] = []
    events: list[EventWithBestMarket]
    total_events: int
    word_search_markets: list[WordSearchMarket] = []


async def _refresh_updates() -> None:
    """Refresh the shared updates payload (runs periodically)."""
    global _updates
    _updates["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
    _updates["version"] = _updates.get("version", 0) + 1
    # Placeholder: replace with real Polymarket/arb data later
    _updates["data"] = [
        {"id": f"item-{_updates['version']}", "label": "Sample", "updated_at": _updates["last_updated"]},
    ]


async def _refresh_tag_cache() -> None:
    """Fetch events from Polymarket, extract unique tags, and embed their labels."""
    global _tag_cache
    if _model is None:
        return

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            all_events: list[dict] = []
            for offset in range(0, 1000, 100):
                r = await client.get(
                    f"{GAMMA_API_BASE}/events",
                    params={"limit": 100, "offset": offset, "active": "true", "closed": "false"},
                )
                r.raise_for_status()
                batch = r.json()
                if not batch:
                    break
                all_events.extend(batch if isinstance(batch, list) else [batch])
    except Exception:
        logger.exception("Failed to fetch events for tag cache")
        return

    seen_slugs: set[str] = set()
    unique_tags: list[dict] = []
    for event in all_events:
        for tag in event.get("tags") or []:
            slug = tag.get("slug", "")
            label = tag.get("label", "")
            if not slug or not label or label in SKIP_TAGS:
                continue
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                unique_tags.append({"label": label, "slug": slug, "id": tag.get("id")})

    if not unique_tags:
        return

    labels = [t["label"] for t in unique_tags]
    loop = asyncio.get_running_loop()
    embeddings = await loop.run_in_executor(None, _model.encode, labels)

    _tag_cache["tags"] = unique_tags
    _tag_cache["embeddings"] = np.asarray(embeddings, dtype=np.float32)
    _tag_cache["last_updated"] = datetime.now(tz=timezone.utc).isoformat()
    logger.info("Tag embedding cache refreshed: %d tags", len(unique_tags))


async def _background_updater(interval_seconds: float = 10.0) -> None:
    """Loop that periodically refreshes the exposed data."""
    while True:
        await _refresh_updates()
        await asyncio.sleep(interval_seconds)


async def _tag_cache_updater(interval_seconds: float = 1800.0) -> None:
    """Refresh tag embedding cache every N seconds (default 30 min)."""
    while True:
        await _refresh_tag_cache()
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load ML model, seed caches, and start background tasks."""
    global _model
    _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _model.encode, "warmup")

    _neo4j_ok = False
    if _graph_available:
        try:
            await init_driver()
            _neo4j_ok = True
        except Exception:
            logger.warning("Neo4j unavailable — graph endpoints will 503. Start Neo4j and restart.")

    await _refresh_updates()
    await _refresh_tag_cache()
    updates_task = asyncio.create_task(_background_updater(interval_seconds=10.0))
    cache_task = asyncio.create_task(_tag_cache_updater(interval_seconds=1800.0))

    yield

    for t in (updates_task, cache_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    if _neo4j_ok:
        await close_driver()


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

if not _graph_available:
    logger.warning("Graph module NOT loaded (%s) — /api/graph/* routes disabled", _graph_err_msg)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check."""
    return {"status": "ok"}


@app.get("/api/version")
async def api_version() -> dict[str, str]:
    """Return API version so frontend can verify tag-based semantic search is loaded."""
    return {"semantic_search": "tag-based", "api_version": "tag-based"}


@app.get("/api/search/tags")
async def get_cached_tags() -> dict[str, Any]:
    """Return the cached tag list instantly (no embedding computation)."""
    tags = _tag_cache.get("tags", [])
    return {
        "tags": [{"label": t["label"], "slug": t["slug"]} for t in tags],
        "count": len(tags),
        "last_updated": _tag_cache.get("last_updated"),
    }


@app.get("/api/updates")
async def get_updates() -> dict[str, Any]:
    """
    Auto-updating endpoint: returns the latest snapshot of data.
    The server refreshes this data in the background every 10 seconds.
    Poll this endpoint to get updated values.
    """
    return _updates.copy()


def _parse_polymarket_url(url: str) -> tuple[str | None, str | None]:
    """
    Parse a Polymarket URL and return (slug, condition_id).
    Supports e.g. https://polymarket.com/event/slug, https://polymarket.com/market/slug,
    and ?condition_id=0x... in query string.
    """
    parsed = urlparse(url.strip())
    if "polymarket.com" not in parsed.netloc:
        return None, None
    path_segments = [p for p in parsed.path.strip("/").split("/") if p]
    slug = path_segments[-1] if len(path_segments) >= 2 else None
    query = parse_qs(parsed.query)
    condition_id = None
    for key in ("condition_id", "conditionId", "condition"):
        if key in query and query[key]:
            condition_id = query[key][0]
            break
    return slug or None, condition_id


@app.get("/api/polymarket")
async def get_polymarket_info(url: str = Query(..., description="Full Polymarket event or market URL")) -> Any:
    """
    Intermediary endpoint: pass a Polymarket URL and get back all information
    Polymarket provides for that market/event. The frontend does not need to
    call Polymarket directly.
    """
    slug, condition_id = _parse_polymarket_url(url)
    if not slug and not condition_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid Polymarket URL: expected e.g. https://polymarket.com/event/... or .../market/...",
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        if slug:
            # Try event by slug first (typical for /event/... URLs)
            try:
                r = await client.get(f"{GAMMA_API_BASE}/events", params={"slug": slug})
                r.raise_for_status()
                events = r.json()
                if events and (isinstance(events, list) and len(events) > 0 or isinstance(events, dict)):
                    return {"source": "gamma", "slug": slug, "data": events}
            except httpx.HTTPStatusError:
                pass
            except httpx.RequestError as e:
                raise HTTPException(status_code=502, detail=f"Failed to reach Polymarket: {str(e)}")

            # Fallback: markets by slug
            try:
                r = await client.get(f"{GAMMA_API_BASE}/markets", params={"slug": slug})
                r.raise_for_status()
                data = r.json()
                if data and (isinstance(data, list) and len(data) > 0 or isinstance(data, dict)):
                    return {"source": "gamma", "slug": slug, "data": data}
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 404:
                    raise HTTPException(status_code=502, detail=f"Polymarket API error: {e.response.text}")
            except httpx.RequestError as e:
                raise HTTPException(status_code=502, detail=f"Failed to reach Polymarket: {str(e)}")

        if condition_id:
            try:
                r = await client.get(f"{GAMMA_API_BASE}/markets", params={"condition_ids": condition_id})
                r.raise_for_status()
                data = r.json()
                return {"source": "gamma", "condition_id": condition_id, "data": data}
            except httpx.HTTPStatusError as e:
                raise HTTPException(status_code=502, detail=f"Polymarket API error: {e.response.text}")
            except httpx.RequestError as e:
                raise HTTPException(status_code=502, detail=f"Failed to reach Polymarket: {str(e)}")

    raise HTTPException(status_code=404, detail="No market or event found for this URL")


def _prices_history_params(market: str, interval: str) -> dict[str, Any]:
    """Build query params for CLOB prices-history. Use startTs/endTs for 1w and max to avoid 400s."""
    market = market.strip()
    now = datetime.now(timezone.utc)
    end_ts = int(now.timestamp())
    # fidelity=60 (1-hour buckets) keeps response size bounded and avoids 400 on some markets
    if interval == "1w":
        start = now - timedelta(days=7)
        return {"market": market, "startTs": int(start.timestamp()), "endTs": end_ts, "fidelity": 60}
    if interval == "max":
        start = now - timedelta(days=30)
        return {"market": market, "startTs": int(start.timestamp()), "endTs": end_ts, "fidelity": 60}
    return {"market": market, "interval": interval}


@app.get("/api/polymarket/prices-history")
async def get_prices_history(
    market: str = Query(..., description="CLOB token id (asset id) for the market"),
    interval: str = Query("1d", description="Aggregation: max, 1w, 1d, 6h, 1h"),
) -> Any:
    """
    Proxy to Polymarket CLOB prices-history. Pass the market (token id) from
    event market clobTokenIds (e.g. first id for Yes outcome).
    For 1w and max we use startTs/endTs first; on 400 we fall back to interval param.
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            params = _prices_history_params(market, interval)
            r = await client.get(
                f"{CLOB_API_BASE}/prices-history",
                params=params,
            )
            if r.status_code == 400 and interval in ("1w", "max"):
                r = await client.get(
                    f"{CLOB_API_BASE}/prices-history",
                    params={"market": market.strip(), "interval": interval},
                )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=e.response.text or "Polymarket CLOB error",
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Failed to reach Polymarket: {str(e)}")


@app.get("/api/polymarket/markets/{market_id}")
async def get_market_by_id(market_id: str) -> Any:
    """
    Fetch a single market by id from Polymarket Gamma API.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(f"{GAMMA_API_BASE}/markets/{market_id.strip()}")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=e.response.text or "Polymarket Gamma error",
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Failed to reach Polymarket: {str(e)}")


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity between vector *a* (1-D) and matrix *b* (2-D)."""
    a_norm = a / (np.linalg.norm(a) + 1e-10)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-10)
    return b_norm @ a_norm


async def _word_search_markets(
    client: httpx.AsyncClient, query: str, top_n: int = 3
) -> list[WordSearchMarket]:
    """
    Polymarket full-text word search; returns top N markets closest in wording to the query.
    Uses Gamma public-search API.
    """
    out: list[WordSearchMarket] = []
    try:
        r = await client.get(
            f"{GAMMA_API_BASE}/public-search",
            params={"q": query[:200], "limit_per_type": 10, "keep_closed_markets": 0},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        events = data.get("events") if isinstance(data, dict) else []
        if not isinstance(events, list):
            events = []
        seen_ids: set[str] = set()
        for ev in events:
            for m in ev.get("markets") or []:
                if len(out) >= top_n:
                    return out
                if m.get("closed") is True or m.get("active") is False:
                    continue
                mid = str(m.get("id", ""))
                q = m.get("question") or m.get("questionTitle") or ""
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    out.append(WordSearchMarket(id=mid, question=q))
        return out
    except Exception:
        logger.warning("Word search failed for query %r", query[:50], exc_info=True)
        return []


async def _fetch_prices_history(
    client: httpx.AsyncClient, token_id: str, interval: str = "1d"
) -> list[dict]:
    """Fetch CLOB price history for a market token (Yes outcome). Returns list of {t, p}."""
    try:
        r = await client.get(
            f"{CLOB_API_BASE}/prices-history",
            params={"market": token_id.strip(), "interval": interval},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        history = data.get("history") if isinstance(data, dict) else []
        return history if isinstance(history, list) else []
    except Exception:
        return []


def _market_importance_score(
    prices: list[float], total_volume: float, timestamps: list[int]
) -> float:
    """
    Market Importance Score (MIS) = volatility + log(1+volume) + recency_ratio.
    Equal weights (alpha=beta=gamma=1). Prioritises informative markets for inference.
    """
    volatility = float(np.std(prices)) if len(prices) >= 2 else 0.0
    volume_score = math.log(1.0 + max(0.0, total_volume))
    if len(timestamps) >= 2:
        span_sec = max(timestamps) - min(timestamps)
        span_days = max(1.0, span_sec / 86400.0)
        distinct_days = len(set(t // 86400 for t in timestamps))
        recency_ratio = min(1.0, distinct_days / span_days)
    else:
        recency_ratio = 0.0
    return volatility + volume_score + recency_ratio


class MatchTagsRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    num_tags: int = Field(5, ge=1, le=15)


class MatchTagsResponse(BaseModel):
    matched_tags: list[MatchedTag]


@app.post("/api/search/semantic/match-tags", response_model=MatchTagsResponse)
async def match_tags(body: MatchTagsRequest) -> MatchTagsResponse:
    """Step 1: embed the prompt and match it against cached Polymarket tags."""
    if _model is None:
        raise HTTPException(status_code=503, detail="Embedding model not loaded yet")
    tag_embeddings: np.ndarray | None = _tag_cache["embeddings"]
    if tag_embeddings is None or len(_tag_cache["tags"]) == 0:
        raise HTTPException(status_code=503, detail="Tag cache empty — try again shortly")

    loop = asyncio.get_running_loop()
    prompt_emb: np.ndarray = await loop.run_in_executor(None, _model.encode, body.prompt)
    scores = _cosine_similarity(prompt_emb, tag_embeddings)
    top_k = min(body.num_tags, len(scores))
    top_indices = np.argsort(scores)[::-1][:top_k]

    tags = []
    for idx in top_indices:
        t = _tag_cache["tags"][int(idx)]
        tags.append(MatchedTag(label=t["label"], slug=t["slug"], score=round(float(scores[idx]), 5)))
    return MatchTagsResponse(matched_tags=tags)


class TagEventsRequest(BaseModel):
    tag_slug: str = Field(..., min_length=1)
    tag_label: str = ""
    tag_score: float = 0.0
    events_per_tag: int = Field(30, ge=1, le=100)


@app.post("/api/search/semantic/tag-events", response_model=TagBreakdown)
async def tag_events(body: TagEventsRequest) -> TagBreakdown:
    """Step 2: fetch live events for a single tag and return breakdown stats."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            r = await client.get(
                f"{GAMMA_API_BASE}/events",
                params={"tag_slug": body.tag_slug, "limit": body.events_per_tag, "active": "true", "closed": "false"},
            )
            r.raise_for_status()
            data = r.json()
            event_list = data if isinstance(data, list) else [data] if data else []
        except Exception:
            logger.warning("Failed to fetch events for tag '%s'", body.tag_slug)
            event_list = []

    total_markets = sum(len(e.get("markets") or []) for e in event_list)
    ev_count = len(event_list)
    return TagBreakdown(
        tag_slug=body.tag_slug,
        tag_label=body.tag_label,
        score=body.tag_score,
        events_count=ev_count,
        total_markets=total_markets,
        avg_markets_per_event=round(total_markets / ev_count, 2) if ev_count else 0.0,
        event_titles=[(e.get("title") or e.get("question") or "(untitled)")[:120] for e in event_list],
    )


class WordSearchRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class WordSearchResponse(BaseModel):
    markets: list[WordSearchMarket]


@app.post("/api/search/semantic/word-search", response_model=WordSearchResponse)
async def word_search(body: WordSearchRequest) -> WordSearchResponse:
    """Step 3: Polymarket full-text word search with embedding similarity scores."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        markets = await _word_search_markets(client, body.prompt, top_n=5)

    if markets and _model is not None:
        loop = asyncio.get_running_loop()
        prompt_emb = await loop.run_in_executor(None, _model.encode, body.prompt)
        questions = [m.question for m in markets]
        q_emb = await loop.run_in_executor(None, _model.encode, questions)
        q_scores = _cosine_similarity(prompt_emb, np.asarray(q_emb, dtype=np.float32))
        for i, m in enumerate(markets):
            m.score = round(float(q_scores[i]), 5)

    return WordSearchResponse(markets=markets)


@app.post("/api/search/semantic/best-market", response_model=BestMarketMatchResponse)
async def best_market_match(body: BestMarketMatchRequest) -> BestMarketMatchResponse:
    """
    Return the single Polymarket market whose question most closely matches the prompt
    by embedding similarity. Only open/active markets are considered (closed markets filtered out).
    """
    if _model is None:
        raise HTTPException(status_code=503, detail="Embedding model not loaded yet")

    async with httpx.AsyncClient(timeout=15.0) as client:
        candidates = await _word_search_markets(client, body.prompt, top_n=80)

    if not candidates:
        return BestMarketMatchResponse(market=None, match_score=0.0)

    loop = asyncio.get_running_loop()
    prompt_emb = await loop.run_in_executor(None, _model.encode, body.prompt)
    questions = [m.question for m in candidates]
    q_emb = await loop.run_in_executor(None, _model.encode, questions)
    q_scores = _cosine_similarity(prompt_emb, np.asarray(q_emb, dtype=np.float32))
    best_idx = int(np.argmax(q_scores))
    best = candidates[best_idx]
    score = round(float(q_scores[best_idx]), 5)

    return BestMarketMatchResponse(
        market=BestMarketSummary(id=best.id, question=best.question),
        match_score=score,
    )


@app.post("/api/search/semantic", response_model=SemanticSearchResponse)
async def semantic_search(body: SemanticSearchRequest) -> SemanticSearchResponse:
    """
    Two-stage semantic search:
    1. Embed the prompt and match it to the top N Polymarket tags.
    2. Fetch live events for each matched tag and return the deduplicated set.
    """
    if _model is None:
        raise HTTPException(status_code=503, detail="Embedding model not loaded yet")

    tag_embeddings: np.ndarray | None = _tag_cache["embeddings"]
    if tag_embeddings is None or len(_tag_cache["tags"]) == 0:
        raise HTTPException(
            status_code=503,
            detail="Tag embedding cache is empty — try again in a few seconds",
        )

    # Stage 1: embed prompt -> match top tags
    loop = asyncio.get_running_loop()
    prompt_embedding: np.ndarray = await loop.run_in_executor(
        None, _model.encode, body.prompt,
    )

    scores = _cosine_similarity(prompt_embedding, tag_embeddings)
    top_k = min(body.num_tags, len(scores))
    top_indices = np.argsort(scores)[::-1][:top_k]

    matched_tags: list[MatchedTag] = []
    tag_slugs: list[str] = []
    for idx in top_indices:
        tag = _tag_cache["tags"][int(idx)]
        matched_tags.append(MatchedTag(
            label=tag["label"],
            slug=tag["slug"],
            score=round(float(scores[idx]), 5),
        ))
        tag_slugs.append(tag["slug"])

    # Stage 2: fetch events for each matched tag concurrently
    async def _fetch_events_for_tag(client: httpx.AsyncClient, slug: str) -> list[dict]:
        try:
            r = await client.get(
                f"{GAMMA_API_BASE}/events",
                params={
                    "tag_slug": slug,
                    "limit": body.events_per_tag,
                    "active": "true",
                    "closed": "false",
                },
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else [data] if data else []
        except Exception:
            logger.warning("Failed to fetch events for tag '%s'", slug)
            return []

    async with httpx.AsyncClient(timeout=20.0) as client:
        results = await asyncio.gather(
            *[_fetch_events_for_tag(client, slug) for slug in tag_slugs]
        )

    # Build per-tag breakdown before deduplication
    tag_breakdown: list[TagBreakdown] = []
    for tag_idx, event_list in enumerate(results):
        tag = matched_tags[tag_idx]
        total_markets = sum(len(e.get("markets") or []) for e in event_list)
        ev_count = len(event_list)
        tag_breakdown.append(TagBreakdown(
            tag_slug=tag.slug,
            tag_label=tag.label,
            score=tag.score,
            events_count=ev_count,
            total_markets=total_markets,
            avg_markets_per_event=round(total_markets / ev_count, 2) if ev_count else 0.0,
            event_titles=[
                (e.get("title") or e.get("question") or "(untitled)")[:120]
                for e in event_list
            ],
        ))

    # Deduplicate by event id; keep raw event dict + tag score for MIS and ordering
    seen_ids: set[str] = set()
    events_with_scores: list[tuple[dict, float]] = []
    for tag_idx, event_list in enumerate(results):
        tag_score = matched_tags[tag_idx].score
        for e in event_list:
            eid = str(e.get("id", ""))
            if eid in seen_ids:
                continue
            seen_ids.add(eid)
            events_with_scores.append((e, tag_score))
    events_with_scores.sort(key=lambda x: -x[1])

    # For each event, pick the most informative market (MIS) and return only its id + question
    max_markets_per_event = 20
    out_events: list[EventWithBestMarket] = []

    async def _best_market_for_event(
        client: httpx.AsyncClient, e: dict, _tag_score: float
    ) -> EventWithBestMarket:
        eid = str(e.get("id", ""))
        title = (e.get("title") or e.get("question")) or ""
        markets = (e.get("markets") or [])[:max_markets_per_event]
        if not markets and e.get("slug"):
            try:
                r = await client.get(
                    f"{GAMMA_API_BASE}/events",
                    params={"slug": e.get("slug")},
                    timeout=10.0,
                )
                r.raise_for_status()
                full = r.json()
                if isinstance(full, list) and full:
                    e = full[0]
                    markets = (e.get("markets") or [])[:max_markets_per_event]
                elif isinstance(full, dict) and full.get("markets"):
                    e = full
                    markets = (e.get("markets") or [])[:max_markets_per_event]
            except Exception:
                pass
        if not markets:
            return EventWithBestMarket(event_id=eid, event_title=title, best_market=None)

        def _parse_clob_token_ids(m: dict) -> str | None:
            raw = m.get("clobTokenIds")
            if isinstance(raw, list) and raw:
                return str(raw[0])
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    return str(parsed[0]) if isinstance(parsed, list) and parsed else None
                except (json.JSONDecodeError, TypeError):
                    pass
            return None

        async def _history_for_market(m: dict) -> tuple[dict, list[float], list[int]]:
            token_id = _parse_clob_token_ids(m)
            if not token_id:
                return (m, [], [])
            hist = await _fetch_prices_history(client, token_id)
            prices = [h["p"] for h in hist if isinstance(h, dict) and "p" in h]
            ts = [int(h["t"]) for h in hist if isinstance(h, dict) and "t" in h]
            return (m, prices, ts)

        market_data = await asyncio.gather(
            *[_history_for_market(m) for m in markets]
        )
        best_mis = -1.0
        best_m = None
        for m, prices, ts in market_data:
            vol = m.get("volume") or m.get("volumeNum")
            vol = float(vol) if vol is not None else 0.0
            if prices and ts:
                mis = _market_importance_score(prices, vol, ts)
            else:
                mis = math.log(1.0 + vol)
            if mis > best_mis:
                best_mis = mis
                best_m = m
        if best_m is None:
            best_m = markets[0]
        # Debug: log full market object so caller can see which id to use (check server logs)
        logger.info(
            "[best_market] Full market object keys: %s | id=%s market_id=%s conditionId=%s",
            list(best_m.keys()),
            best_m.get("id"),
            best_m.get("market_id"),
            best_m.get("conditionId"),
        )
        logger.info("[best_market] Full target market object: %s", json.dumps({k: v for k, v in best_m.items() if k not in ("description", "resolutionSource")}, default=str))
        market_id = best_m.get("id") or best_m.get("market_id")
        if market_id is not None:
            market_id = str(market_id)
        else:
            market_id = ""
        return EventWithBestMarket(
            event_id=eid,
            event_title=title,
            best_market=BestMarketSummary(
                id=market_id,
                question=best_m.get("question") or best_m.get("questionTitle") or "",
            ),
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        out_events_task = asyncio.gather(
            *[_best_market_for_event(client, e, sc) for e, sc in events_with_scores]
        )
        word_search_task = _word_search_markets(client, body.prompt, top_n=3)
        out_events, word_search_markets = await asyncio.gather(
            out_events_task, word_search_task
        )
        for wm in word_search_markets:
            if not wm.id:
                continue
            try:
                r = await client.get(f"{GAMMA_API_BASE}/markets/{wm.id.strip()}")
                if r.status_code == 200:
                    full = r.json()
                    m = full[0] if isinstance(full, list) and full else full
                    if isinstance(m, dict):
                        resolved = m.get("id") or m.get("market_id")
                        if resolved is not None:
                            wm.id = str(resolved)
            except Exception:
                pass

    # Compute embedding similarity for word-search results
    if word_search_markets and _model is not None:
        questions = [wm.question for wm in word_search_markets]
        q_embeddings = await loop.run_in_executor(None, _model.encode, questions)
        q_scores = _cosine_similarity(prompt_embedding, np.asarray(q_embeddings, dtype=np.float32))
        for i, wm in enumerate(word_search_markets):
            wm.score = round(float(q_scores[i]), 5)

    return SemanticSearchResponse(
        api_version="tag-based",
        prompt=body.prompt,
        matched_tags=matched_tags,
        tag_breakdown=tag_breakdown,
        events=list(out_events),
        total_events=len(out_events),
        word_search_markets=word_search_markets,
    )


# --- Knowledge graph endpoints (registered last so they appear in OpenAPI) ---
if _graph_available:

    @app.post("/api/graph/ingest", response_model=IngestResponse, tags=["Knowledge graph"])
    async def api_graph_ingest(fresh: bool = Query(False, description="Clear graph before ingesting")) -> IngestResponse:
        """Trigger Polymarket + Wikipedia ingestion pipeline."""
        try:
            if fresh:
                await clear_graph()
            poly = await ingest_polymarket()
            wiki = await ingest_wikipedia()
            return IngestResponse(status="complete", polymarket=poly, wikipedia=wiki)
        except Exception as exc:
            logger.exception("Graph ingest failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/graph/traverse", response_model=TraverseResponse, tags=["Knowledge graph"])
    async def api_graph_traverse(
        name: str = Query(..., description="Entity name to start from"),
        depth: int = Query(3, ge=1, le=6, description="Max hops"),
        include_events_markets: bool = Query(
            True,
            description="Include paths ending at Event or Market",
        ),
        include_persons_companies: bool = Query(
            True,
            description="Include paths ending at Person or Company",
        ),
    ) -> TraverseResponse:
        """Find connections from a named entity. Filter by end-node type: events/markets and/or persons/companies."""
        paths = await find_connections(
            name,
            max_depth=depth,
            include_events_markets=include_events_markets,
            include_persons_companies=include_persons_companies,
        )
        return TraverseResponse(
            name=name,
            depth=depth,
            include_events_markets=include_events_markets,
            include_persons_companies=include_persons_companies,
            paths=paths,
        )

    @app.post("/api/graph/postprocess", response_model=PostprocessResponse, tags=["Knowledge graph"])
    async def api_graph_postprocess() -> PostprocessResponse:
        """Merge duplicate Person/Company nodes (e.g. 'Elon' into 'Elon Musk'). Safe to run after ingestion."""
        try:
            result = await postprocess_merge_duplicate_entities()
            return PostprocessResponse(**result)
        except Exception as exc:
            logger.exception("Graph postprocess failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/graph/datasources", response_model=DatasourceResponse, tags=["Knowledge graph"])
    async def api_graph_datasources(
        name: str = Query(..., description="Entity to find linked data sources for"),
    ) -> DatasourceResponse:
        """Find all DataSource nodes reachable from a named entity."""
        ds = await find_indirect_datasources(name)
        return DatasourceResponse(name=name, datasources=ds)

    @app.get("/api/graph/search", response_model=SearchResponse, tags=["Knowledge graph"])
    async def api_graph_search(
        q: str = Query(..., min_length=1, description="Search query"),
    ) -> SearchResponse:
        """Full-text search across graph nodes."""
        results = await search_nodes(q)
        return SearchResponse(query=q, results=results)

    @app.get("/api/graph/stats", response_model=StatsResponse, tags=["Knowledge graph"])
    async def api_graph_stats() -> StatsResponse:
        """Graph statistics: node and relationship counts."""
        s = await graph_stats()
        return StatsResponse(**s)

    _END_TYPE_MAP = {
        "person": "Person", "event": "Event",
        "market": "Market", "company": "Company",
    }

    @app.get(
        "/api/graph/related-by-paths",
        response_model=RelatedByPathsResponse,
        tags=["Knowledge graph"],
    )
    async def api_graph_related_by_paths(
        q: str = Query(..., min_length=1, description="Search query"),
        depth: int = Query(4, ge=1, le=6, description="Max traversal hops"),
        limit: int = Query(10, ge=1, le=50, description="Max results"),
        end_types: str = Query(
            "person,event,company,market",
            description="Comma-separated destination types: person, event, company, market",
        ),
        weight_by: str = Query(
            "count",
            description="Scoring method: 'count' (raw path count) or 'length' (shorter paths weigh more)",
        ),
    ) -> RelatedByPathsResponse:
        """Find the top-N persons, events, markets, or companies most related
        to a query term by counting distinct graph paths."""
        parsed_types = tuple(
            _END_TYPE_MAP[t]
            for t in (s.strip().lower() for s in end_types.split(","))
            if t in _END_TYPE_MAP
        )
        if weight_by not in ("count", "length"):
            weight_by = "count"
        results, start_count, cached = await find_related_by_paths(
            query=q,
            max_depth=depth,
            limit=limit,
            end_types=parsed_types or ("Person", "Event", "Market", "Company"),
            weight_by=weight_by,
        )
        return RelatedByPathsResponse(
            query=q,
            results=results,
            start_nodes_matched=start_count,
            cached=cached,
        )

    @app.get(
        "/api/graph/bfs-layers",
        response_model=BFSLayersResponse,
        tags=["Knowledge graph"],
    )
    async def api_graph_bfs_layers(
        q: str = Query(..., min_length=1, description="Search query"),
        max_depth: int = Query(4, ge=1, le=6, description="Max BFS depth (layers)"),
    ) -> BFSLayersResponse:
        """BFS from nodes matching query, returning cumulative layers for
        animated graph visualization."""
        result = await find_bfs_layers(query=q, max_depth=max_depth)
        return BFSLayersResponse(**result)

    # In-memory cache for NY Times Top Stories (minimize API calls; keyed by section)
    _nytimes_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
    NYTIMES_CACHE_TTL_SEC = 60 * 15  # 15 minutes

    # NY Times Top Stories proxy (hides API key, avoids CORS)
    @app.get("/api/nytimes/top-stories", tags=["News"])
    async def api_nytimes_top_stories(
        section: str = Query("home", description="Section: home, world, business, technology, etc."),
    ) -> list[dict[str, Any]]:
        """Proxy to NY Times Top Stories API. Returns up to 4 articles. Cached 15 min per section."""
        import time
        now = time.monotonic()
        section = (section or "home").strip().lower() or "home"
        if section in _nytimes_cache:
            cached_list, ts = _nytimes_cache[section]
            if now - ts < NYTIMES_CACHE_TTL_SEC:
                return cached_list[:4]
            del _nytimes_cache[section]
        api_key = os.getenv("NYTIMES_API_KEY") or os.getenv("VITE_NYTIMES_API_KEY")
        if not api_key:
            logger.warning("NYTIMES_API_KEY not set; returning empty list")
            return []
        url = f"https://api.nytimes.com/svc/topstories/v2/{section}.json"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, params={"api-key": api_key})
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.exception("NY Times API request failed: %s", e)
            raise HTTPException(status_code=502, detail="News feed temporarily unavailable")
        results = data.get("results") or []
        out = []
        for i, a in enumerate(results):
            img = None
            if a.get("multimedia"):
                for m in a["multimedia"]:
                    if m.get("format") == "Large Thumbnail" or m.get("subtype") == "thumbnail":
                        img = m.get("url")
                        if img and not img.startswith("http"):
                            img = "https://static01.nyt.com/" + img
                        break
                if not img and a["multimedia"]:
                    u = a["multimedia"][-1].get("url")
                    if u:
                        img = u if u.startswith("http") else "https://static01.nyt.com/" + u
            out.append({
                "id": a.get("uri") or f"nyt-{i}",
                "title": a.get("title") or "Untitled",
                "abstract": a.get("abstract"),
                "url": a.get("url"),
                "section": a.get("section"),
                "byline": a.get("byline"),
                "published_date": a.get("published_date"),
                "image_url": img,
            })
        _nytimes_cache[section] = (out, now)
        return out[:4]

    # In-memory cache for NY Times Article Search (keyed by normalized query)
    _nytimes_search_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}

    @app.get("/api/nytimes/search", tags=["News"])
    async def api_nytimes_search(
        q: str = Query(..., min_length=1, description="Search query (e.g. topic or event title)"),
    ) -> list[dict[str, Any]]:
        """Search NY Times articles by query. Returns up to 4 articles. Cached 15 min per query."""
        import time
        now = time.monotonic()
        query_key = (q or "").strip().lower()[:200] or "news"
        if query_key in _nytimes_search_cache:
            cached_list, ts = _nytimes_search_cache[query_key]
            if now - ts < NYTIMES_CACHE_TTL_SEC:
                return cached_list[:4]
            del _nytimes_search_cache[query_key]
        api_key = os.getenv("NYTIMES_API_KEY") or os.getenv("VITE_NYTIMES_API_KEY")
        if not api_key:
            logger.warning("NYTIMES_API_KEY not set; returning empty list")
            return []
        url = "https://api.nytimes.com/svc/search/v2/articlesearch.json"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url, params={"api-key": api_key, "q": q.strip(), "page": 0})
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.exception("NY Times Article Search failed: %s", e)
            raise HTTPException(status_code=502, detail="News search temporarily unavailable")
        docs = (data.get("response") or {}).get("docs") or []
        out = []
        for i, doc in enumerate(docs):
            headline = doc.get("headline")
            if isinstance(headline, dict):
                title = headline.get("main") or headline.get("print_headline") or "Untitled"
            elif isinstance(headline, str):
                title = headline.strip() or "Untitled"
            else:
                title = "Untitled"
            img = None
            multimedia = doc.get("multimedia") or []
            for m in multimedia:
                if not isinstance(m, dict):
                    continue
                if m.get("subtype") == "thumbnail" or (m.get("width") and m.get("height")):
                    img = m.get("url")
                    if img and not img.startswith("http"):
                        img = "https://static01.nyt.com/" + img
                    break
            if not img and multimedia:
                m = multimedia[0]
                if isinstance(m, dict):
                    img = m.get("url")
                    if img and not img.startswith("http"):
                        img = "https://static01.nyt.com/" + img
            out.append({
                "id": doc.get("_id") or f"nyt-search-{i}",
                "title": title,
                "abstract": doc.get("snippet"),
                "url": doc.get("web_url"),
                "section": (doc.get("section_name") or doc.get("news_desk") or "").replace(";", ", "),
                "byline": (doc.get("byline") or {}).get("original") if isinstance(doc.get("byline"), dict) else doc.get("byline"),
                "published_date": doc.get("pub_date", "")[:10] if doc.get("pub_date") else None,
                "image_url": img,
            })
        _nytimes_search_cache[query_key] = (out, now)
        return out[:4]


class BasketRequest(BaseModel):
    target_market_id: str
    input_market_ids: list[str]
    days: int = 7
    use_semantic_filter: bool = True
    top_k_semantic: int = 10
    min_similarity: float = 0.4
    max_target_similarity: float = 1


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
        max_target_similarity: Maximum similarity to target - filters out near-duplicates (default: 0.95)
    
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
    logger.info(
        "basket request: target_market_id=%s input_market_ids=%s",
        request.target_market_id,
        request.input_market_ids,
    )
    print("[basket] target_market_id:", request.target_market_id)
    print("[basket] input_market_ids:", request.input_market_ids)
    try:
        result = build_synthetic_basket(
            target_market_id=request.target_market_id,
            input_market_ids=request.input_market_ids,
            days=request.days,
            verbose=False,
            use_semantic_filter=request.use_semantic_filter,
            top_k_semantic=request.top_k_semantic,
            min_similarity=request.min_similarity,
            max_target_similarity=request.max_target_similarity
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
    logger.info("basket-no-target request: input_market_ids=%s", request.input_market_ids)
    print("[basket-no-target] input_market_ids:", request.input_market_ids)
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
    logger.info("basket-llm-no-target request: input_market_ids=%s", request.input_market_ids)
    print("[basket-llm-no-target] input_market_ids:", request.input_market_ids)
    try:
        result = build_basket_llm_no_target(
            input_market_ids=request.input_market_ids,
            top_k=request.top_k
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
