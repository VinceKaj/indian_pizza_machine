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
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

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


class SemanticSearchResponse(BaseModel):
    api_version: str = "tag-based"
    prompt: str
    matched_tags: list[MatchedTag]
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
    print(">>> Semantic search API: TAG-BASED (matched_tags + events) <<<", flush=True)
    logger.info("Loading sentence-transformer model '%s' …", EMBEDDING_MODEL_NAME)
    _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    logger.info("Model loaded.")

    await _refresh_updates()
    # Populate tag cache once before accepting requests so semantic search works immediately
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


@app.get("/api/version")
async def api_version() -> dict[str, str]:
    """Return API version so frontend can verify tag-based semantic search is loaded."""
    return {"semantic_search": "tag-based", "api_version": "tag-based"}


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


@app.get("/api/polymarket/prices-history")
async def get_prices_history(
    market: str = Query(..., description="CLOB token id (asset id) for the market"),
    interval: str = Query("1d", description="Aggregation: max, all, 1m, 1w, 1d, 6h, 1h"),
) -> Any:
    """
    Proxy to Polymarket CLOB prices-history. Pass the market (token id) from
    event market clobTokenIds (e.g. first id for Yes outcome).
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
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
            params={"q": query[:200], "limit_per_type": 10},
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
        return EventWithBestMarket(
            event_id=eid,
            event_title=title,
            best_market=BestMarketSummary(
                id=str(best_m.get("id", "")),
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

    return SemanticSearchResponse(
        api_version="tag-based",
        prompt=body.prompt,
        matched_tags=matched_tags,
        events=list(out_events),
        total_events=len(out_events),
        word_search_markets=word_search_markets,
    )
