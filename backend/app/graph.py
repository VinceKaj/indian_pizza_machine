"""
Knowledge graph module: Neo4j-backed graph of Polymarket events, Wikipedia
entities, and their relationships.  Provides ingestion pipelines and traversal
APIs exposed via a FastAPI APIRouter.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

try:
    from neo4j import AsyncGraphDatabase, AsyncDriver
    _NEO4J_AVAILABLE = True
except ImportError:
    AsyncGraphDatabase = None  # type: ignore[assignment,misc]
    AsyncDriver = None  # type: ignore[assignment,misc]
    _NEO4J_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "polymarket123")

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
WIKI_API_BASE = "https://en.wikipedia.org/w/api.php"
WIKI_HEADERS = {
    "User-Agent": "IndianPizzaMachine/1.0 (knowledge-graph bot; contact: admin@example.com)",
    "Accept": "application/json",
}

SKIP_TAGS = {
    "All", "Featured", "Parent For Derivative",
    "Hide From China", "Hide From New",
}

TICKER_MAP: dict[str, str] = {
    "TSLA": "Tesla", "AAPL": "Apple", "GOOGL": "Alphabet",
    "GOOG": "Alphabet", "AMZN": "Amazon", "MSFT": "Microsoft",
    "META": "Meta Platforms", "NVDA": "NVIDIA", "NFLX": "Netflix",
    "DIS": "Disney", "BA": "Boeing", "JPM": "JPMorgan Chase",
    "V": "Visa", "WMT": "Walmart", "BTC": "Bitcoin",
    "ETH": "Ethereum", "SOL": "Solana", "XRP": "Ripple",
    "DOGE": "Dogecoin", "SPY": "S&P 500", "INTC": "Intel",
    "AMD": "AMD", "CRM": "Salesforce", "PYPL": "PayPal",
    "UBER": "Uber", "ABNB": "Airbnb", "COIN": "Coinbase",
    "GBTC": "Bitcoin", "MSTR": "MicroStrategy", "SQ": "Block Inc",
    "SHOP": "Shopify", "SNAP": "Snap Inc", "TWTR": "Twitter",
    "PLTR": "Palantir", "RIVN": "Rivian", "LCID": "Lucid Motors",
    "GM": "General Motors", "F": "Ford", "NIO": "NIO",
    "BABA": "Alibaba", "TSM": "TSMC", "SPOT": "Spotify",
    "SLV": "Silver", "GLD": "Gold",
}

KNOWN_COMPANIES: set[str] = {
    "Google", "Apple", "Amazon", "Microsoft", "Meta", "Facebook",
    "Tesla", "SpaceX", "OpenAI", "Anthropic", "Twitter", "X Corp",
    "Netflix", "Disney", "Boeing", "Lockheed Martin", "Raytheon",
    "Goldman Sachs", "Morgan Stanley", "JPMorgan", "Citigroup",
    "Bank of America", "Wells Fargo", "BlackRock", "Vanguard",
    "Berkshire Hathaway", "Walmart", "Target", "Costco",
    "Samsung", "TSMC", "Intel", "AMD", "NVIDIA", "Qualcomm",
    "Pfizer", "Moderna", "Johnson & Johnson", "Merck", "AstraZeneca",
    "ExxonMobil", "Chevron", "Shell", "BP",
    "TikTok", "ByteDance", "Tencent", "Alibaba", "Baidu",
    "Uber", "Lyft", "Airbnb", "DoorDash", "Coinbase", "Binance",
    "FTX", "Ripple", "Solana", "Cardano",
    "NATO", "WHO", "UN", "EU", "FBI", "CIA", "SEC", "Fed",
    "Federal Reserve", "Pentagon", "NASA", "FEMA", "EPA",
    "ICC", "IMF", "World Bank", "OPEC",
    "Hamas", "Hezbollah", "Taliban", "ISIS",
    "Republican Party", "Democratic Party", "GOP",
    "Supreme Court", "Congress", "Senate", "House",
}

# Noise phrases that NER picks up that aren't real person names
_PERSON_BLOCKLIST: set[str] = {
    # Places & geography
    "New York", "Los Angeles", "San Francisco", "San Diego", "San Antonio",
    "San Jose", "United States", "United Kingdom", "North Korea", "South Korea",
    "North America", "South America", "Middle East", "White House", "Wall Street",
    "Silicon Valley", "Capitol Hill", "Mar Lago", "Mar A Lago",
    "Las Vegas", "Hong Kong", "Tel Aviv", "New Zealand", "Sri Lanka",
    "Costa Rica", "Puerto Rico", "El Salvador", "Saudi Arabia", "South Africa",
    "North Carolina", "South Carolina", "West Virginia", "New Jersey",
    "New Hampshire", "New Mexico", "Rhode Island", "West Bank", "Gaza Strip",
    "Buenos Aires", "Kuala Lumpur", "St Louis", "Fort Worth", "Baton Rouge",
    "Monte Carlo", "Abu Dhabi", "Sao Paulo", "Des Moines",
    # Sports teams & leagues
    "Calgary Flames", "Edmonton Oilers", "Florida Panthers", "Nashville Predators",
    "Carolina Hurricanes", "Tampa Bay", "Tampa Bay Lightning", "Tampa Bay Buccaneers",
    "Golden State", "Golden State Warriors", "Boston Celtics", "Boston Red Sox",
    "Los Angeles Lakers", "Los Angeles Dodgers", "Los Angeles Clippers",
    "New York Yankees", "New York Mets", "New York Knicks", "New York Rangers",
    "New York Giants", "New York Jets", "San Francisco Giants",
    "Green Bay", "Green Bay Packers", "Kansas City", "Kansas City Chiefs",
    "Real Madrid", "Manchester United", "Manchester City", "Paris Saint",
    "Inter Miami", "Red Bull", "Red Sox", "White Sox",
    "Stanley Cup", "Champions League", "Premier League", "World Series",
    "Super Bowl", "World Cup", "Grand Prix", "Europa League",
    "March Madness", "Final Four", "All Star",
    # Sports terms
    "Most Improved Player", "Most Valuable Player", "Defensive Player",
    "Rookie Year", "Regular Season", "Play In", "Wild Card",
    "Conference Finals", "Division Series",
    # Political / generic terms
    "Prime Minister", "Vice President", "General Election", "Holy See",
    "Executive Order", "Supreme Court", "National Guard", "State Department",
    "Department Of", "National Security", "Foreign Affairs", "Armed Forces",
    "Red Sea", "Black Sea", "Dead Sea", "South China",
    # Time / generic
    "Next Year", "Last Year", "This Year", "First Time", "Top Ten",
    "Second Half", "First Half", "Third Quarter", "Fourth Quarter",
    "Year End", "Year Over", "End Of", "Of The",
    "First Round", "Second Round", "Third Round",
}
_PERSON_BLOCKLIST_LOWER: set[str] = {p.lower() for p in _PERSON_BLOCKLIST}

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_driver: AsyncDriver | None = None
_nlp: Any = None  # spaCy model, loaded lazily

# Related-by-paths cache: (key) -> (results, start_count, monotonic_timestamp)
_RELATED_CACHE: OrderedDict[tuple, tuple[list[dict], int, float]] = OrderedDict()
_RELATED_CACHE_TTL = 300   # seconds
_RELATED_CACHE_MAX = 500   # max entries

router = APIRouter(tags=["knowledge-graph"])

# ═══════════════════════════════════════════════════════════════════════════
# Driver lifecycle
# ═══════════════════════════════════════════════════════════════════════════


async def init_driver() -> AsyncDriver:
    """Create and verify the Neo4j async driver, then ensure schema."""
    if not _NEO4J_AVAILABLE:
        raise ImportError(
            "neo4j package not installed. Run: pip install neo4j"
        )
    global _driver
    _driver = AsyncGraphDatabase.driver(
        NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD),
    )
    await _driver.verify_connectivity()
    logger.info("Neo4j connected at %s", NEO4J_URI)
    await _ensure_constraints()
    return _driver


async def close_driver() -> None:
    """Shut down the Neo4j driver pool."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed.")


def _get_driver():
    if _driver is None:
        raise HTTPException(
            status_code=503,
            detail="Neo4j not connected. Install neo4j package and start Neo4j, then restart the server.",
        )
    return _driver

# ═══════════════════════════════════════════════════════════════════════════
# Schema constraints & indexes
# ═══════════════════════════════════════════════════════════════════════════


async def _ensure_constraints() -> None:
    driver = _get_driver()
    stmts = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Event)      REQUIRE e.poly_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Market)     REQUIRE m.poly_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Tag)        REQUIRE t.slug    IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Person)     REQUIRE p.name    IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Company)    REQUIRE c.name    IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (d:DataSource) REQUIRE d.name    IS UNIQUE",
    ]
    async with driver.session() as session:
        for s in stmts:
            await session.run(s)

    async with driver.session() as session:
        try:
            await session.run(
                "CREATE FULLTEXT INDEX nodeSearch IF NOT EXISTS "
                "FOR (n:Event|Market|Person|Company|Tag) "
                "ON EACH [n.name, n.title, n.question, n.label, n.description]"
            )
        except Exception:
            logger.debug("Full-text index creation skipped (may already exist)")

    logger.info("Graph constraints and indexes ensured.")

# ═══════════════════════════════════════════════════════════════════════════
# NLP entity extraction  (spaCy → regex fallback; BERT skipped - too slow for batch)
# ═══════════════════════════════════════════════════════════════════════════

_NER_ENGINE: str = "none"  # set once by _init_ner()


def _init_ner() -> None:
    """Lazily initialise the best available NER engine (spaCy or regex only).
    BERT/transformers NER is not used: it is too slow for batch ingestion on CPU."""
    global _nlp, _NER_ENGINE
    if _NER_ENGINE != "none":
        return

    # 1️⃣ Try spaCy (fast and good quality)
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
        _NER_ENGINE = "spacy"
        logger.info("NER engine: spaCy en_core_web_sm")
        return
    except Exception as exc:
        logger.info("spaCy unavailable (%s), using regex fallback", exc)

    _NER_ENGINE = "regex"
    logger.warning("NER engine: regex. For better entities, install: pip install spacy && python -m spacy download en_core_web_sm")


def _is_likely_person(name: str) -> bool:
    """Heuristic: a person name has 2-4 capitalized words, none too long."""
    if name.lower() in _PERSON_BLOCKLIST_LOWER:
        return False
    parts = name.split()
    if not (2 <= len(parts) <= 4):
        return False
    if any(len(p) > 15 for p in parts):
        return False
    if all(p.isupper() for p in parts):
        return False
    return True


def _is_likely_company(name: str) -> bool:
    """Heuristic: known company or has a corporate suffix."""
    if name in KNOWN_COMPANIES:
        return True
    suffixes = (
        "Inc", "Corp", "Ltd", "LLC", "Group", "Bank", "Fund",
        "Holdings", "Capital", "Partners", "Labs",
        "Technologies", "Therapeutics", "Pharmaceuticals",
        "Energy", "Motors", "Airlines", "Airways",
    )
    return any(name.endswith(s) for s in suffixes)


_LEADING_NOISE = {
    "will", "does", "can", "has", "have", "would", "could", "should",
    "shall", "did", "is", "are", "was", "were", "may", "might",
    "if", "when", "where", "who", "what", "how", "after", "before",
    "during", "under", "over", "between", "within", "until", "since",
    "about", "do", "the", "a", "an", "and", "or", "but", "for", "not",
    "former", "current", "president", "senator", "governor", "mayor",
    "secretary", "representative", "congressman", "minister", "king",
    "queen", "prince", "princess", "ceo", "cto", "cfo", "chairman",
    "director", "pope", "judge", "justice", "general", "admiral",
    "coach", "dr", "mr", "mrs", "ms",
}


def _clean_name(raw: str) -> str:
    """Strip leading noise/question words that the regex accidentally captures."""
    parts = raw.split()
    while parts and parts[0].lower() in _LEADING_NOISE:
        parts.pop(0)
    # Strip trailing noise too
    while parts and parts[-1].lower() in {"the", "a", "an", "and", "or", "of", "in", "to", "for"}:
        parts.pop()
    return " ".join(parts).strip()


def _extract_via_spacy(text: str) -> dict[str, set[str]]:
    """Use spaCy NER (best quality if available)."""
    persons: set[str] = set()
    companies: set[str] = set()
    doc = _nlp(text[:10000])
    for ent in doc.ents:
        name = _clean_name(ent.text.strip())
        if len(name) < 2:
            continue
        if ent.label_ == "PERSON":
            if _is_likely_person(name):
                persons.add(name)
        elif ent.label_ == "ORG":
            if len(name) >= 2:
                companies.add(name)
    return {"persons": persons, "companies": companies}


def _extract_via_regex(text: str) -> dict[str, set[str]]:
    """Last-resort regex NER."""
    persons: set[str] = set()
    companies: set[str] = set()
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", text):
        name = _clean_name(m.group(1))
        if len(name) < 3:
            continue
        if _is_likely_company(name):
            companies.add(name)
        elif _is_likely_person(name):
            persons.add(name)
    return {"persons": persons, "companies": companies}


def extract_entities(text: str) -> dict[str, set[str]]:
    """Return ``{"persons": {...}, "companies": {...}}`` extracted from *text*."""
    _init_ner()

    persons: set[str] = set()
    companies: set[str] = set()

    # Always: ticker detection
    for ticker, company in TICKER_MAP.items():
        if re.search(rf"\b{re.escape(ticker)}\b", text):
            companies.add(company)

    # Always: known company name detection
    text_lower = text.lower()
    for company in KNOWN_COMPANIES:
        if company.lower() in text_lower:
            companies.add(company)

    # NER engine dispatch (spaCy or regex only; BERT too slow for batch)
    if _NER_ENGINE == "spacy":
        ner_result = _extract_via_spacy(text)
    else:
        ner_result = _extract_via_regex(text)

    persons.update(ner_result["persons"])
    companies.update(ner_result["companies"])

    # Final cleanup: remove any "person" that is actually a known company
    known_lower = {c.lower() for c in KNOWN_COMPANIES}
    persons = {p for p in persons if p.lower() not in known_lower and p not in companies}

    return {"persons": persons, "companies": companies}

# ═══════════════════════════════════════════════════════════════════════════
# Graph reset
# ═══════════════════════════════════════════════════════════════════════════


async def clear_graph() -> dict[str, int]:
    """Delete all nodes and relationships. Returns count of deleted nodes."""
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (n) DETACH DELETE n RETURN count(n) AS deleted"
        )
        data = await result.single()
        deleted = data["deleted"] if data else 0
    await _ensure_constraints()
    logger.info("Graph cleared: %d nodes deleted", deleted)
    return {"deleted": deleted}


# ═══════════════════════════════════════════════════════════════════════════
# Polymarket ingestion
# ═══════════════════════════════════════════════════════════════════════════


async def ingest_polymarket() -> dict[str, int]:
    """Fetch active Polymarket events → create Event / Market / Tag /
    Person / Company nodes and their relationships."""
    driver = _get_driver()
    counts = {
        "events": 0, "markets": 0, "tags": 0,
        "persons": 0, "companies": 0, "mentions": 0,
    }

    # ---- fetch events ----
    all_events: list[dict] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for offset in range(0, 1000, 100):
            try:
                r = await client.get(
                    f"{GAMMA_API_BASE}/events",
                    params={
                        "limit": 100, "offset": offset,
                        "active": "true", "closed": "false",
                    },
                )
                r.raise_for_status()
                batch = r.json()
                if not batch:
                    break
                all_events.extend(batch if isinstance(batch, list) else [batch])
            except Exception:
                logger.warning("Failed to fetch events at offset %d", offset)
                break

    if not all_events:
        return counts

    # ---- ensure Polymarket DataSource ----
    async with driver.session() as session:
        await session.run(
            "MERGE (d:DataSource {name: $name}) "
            "SET d.type = $type, d.url = $url",
            name="Polymarket", type="api", url="https://polymarket.com",
        )

    # ---- process in batches ----
    batch_size = 50
    # Per-market entity mentions: {market_poly_id: {"persons": set, "companies": set}}
    market_entity_map: dict[str, dict[str, set[str]]] = {}

    for i in range(0, len(all_events), batch_size):
        chunk = all_events[i : i + batch_size]

        event_rows: list[dict] = []
        market_rows: list[dict] = []
        tag_rows: list[dict] = []
        person_event_rows: list[dict] = []
        company_event_rows: list[dict] = []
        person_market_rows: list[dict] = []
        company_market_rows: list[dict] = []

        for ev in chunk:
            eid = str(ev.get("id", ""))
            if not eid:
                continue
            title = ev.get("title") or ""
            description = ev.get("description") or ""

            event_rows.append({
                "poly_id": eid,
                "title": title,
                "slug": ev.get("slug") or "",
                "description": description[:2000],
                "volume": float(ev.get("volume") or 0),
                "liquidity": float(ev.get("liquidity") or 0),
                "active": bool(ev.get("active")),
                "end_date": ev.get("end_date") or "",
            })

            # NER on event-level text (title + description)
            event_text = f"{title}. {description}"
            event_entities = extract_entities(event_text)
            for person in event_entities["persons"]:
                person_event_rows.append({
                    "name": person, "event_id": eid,
                    "context": title[:200],
                })
            for company in event_entities["companies"]:
                company_event_rows.append({
                    "name": company, "event_id": eid,
                    "context": title[:200],
                })

            for m in ev.get("markets") or []:
                mid = str(m.get("id", ""))
                question = m.get("question") or m.get("questionTitle") or ""
                if not mid:
                    continue

                market_rows.append({
                    "poly_id": mid,
                    "question": question,
                    "volume": float(
                        m.get("volume") or m.get("volumeNum") or 0
                    ),
                    "last_price": float(m.get("lastTradePrice") or 0),
                    "active": bool(m.get("active")),
                    "event_id": eid,
                })

                # NER per market question
                if question:
                    m_entities = extract_entities(question)
                    for person in m_entities["persons"]:
                        person_market_rows.append({
                            "name": person, "market_id": mid,
                            "context": question[:200],
                        })
                        # Also link to event
                        person_event_rows.append({
                            "name": person, "event_id": eid,
                            "context": question[:200],
                        })
                    for company in m_entities["companies"]:
                        company_market_rows.append({
                            "name": company, "market_id": mid,
                            "context": question[:200],
                        })
                        company_event_rows.append({
                            "name": company, "event_id": eid,
                            "context": question[:200],
                        })

            for tag in ev.get("tags") or []:
                slug = tag.get("slug", "")
                label = tag.get("label", "")
                if slug and label and label not in SKIP_TAGS:
                    tag_rows.append({
                        "slug": slug, "label": label, "event_id": eid,
                    })

        # ---- write to Neo4j ----
        async with driver.session() as session:
            if event_rows:
                await session.run(
                    "UNWIND $rows AS r "
                    "MERGE (e:Event {poly_id: r.poly_id}) "
                    "SET e.title = r.title, e.slug = r.slug, "
                    "    e.description = r.description, "
                    "    e.volume = r.volume, e.liquidity = r.liquidity, "
                    "    e.active = r.active, e.end_date = r.end_date "
                    "WITH e "
                    "MATCH (d:DataSource {name: 'Polymarket'}) "
                    "MERGE (e)-[:SOURCED_FROM]->(d)",
                    rows=event_rows,
                )
                counts["events"] += len(event_rows)

            if market_rows:
                await session.run(
                    "UNWIND $rows AS r "
                    "MERGE (m:Market {poly_id: r.poly_id}) "
                    "SET m.question = r.question, m.volume = r.volume, "
                    "    m.last_price = r.last_price, m.active = r.active "
                    "WITH m, r "
                    "MATCH (e:Event {poly_id: r.event_id}) "
                    "MERGE (e)-[:HAS_MARKET]->(m) "
                    "WITH m "
                    "MATCH (d:DataSource {name: 'Polymarket'}) "
                    "MERGE (m)-[:SOURCED_FROM]->(d)",
                    rows=market_rows,
                )
                counts["markets"] += len(market_rows)

            if tag_rows:
                await session.run(
                    "UNWIND $rows AS r "
                    "MERGE (t:Tag {slug: r.slug}) "
                    "SET t.label = r.label "
                    "WITH t, r "
                    "MATCH (e:Event {poly_id: r.event_id}) "
                    "MERGE (e)-[:TAGGED_WITH]->(t)",
                    rows=tag_rows,
                )
                counts["tags"] += len({t["slug"] for t in tag_rows})

            # Person → Event
            if person_event_rows:
                await session.run(
                    "UNWIND $rows AS r "
                    "MERGE (p:Person {name: r.name}) "
                    "WITH p, r "
                    "MATCH (e:Event {poly_id: r.event_id}) "
                    "MERGE (e)-[rel:MENTIONS]->(p) "
                    "SET rel.context = r.context "
                    "WITH p "
                    "MATCH (d:DataSource {name: 'Polymarket'}) "
                    "MERGE (p)-[:SOURCED_FROM]->(d)",
                    rows=person_event_rows,
                )
                counts["persons"] += len({r["name"] for r in person_event_rows})

            # Person → Market (direct link to the market question that mentions them)
            if person_market_rows:
                await session.run(
                    "UNWIND $rows AS r "
                    "MERGE (p:Person {name: r.name}) "
                    "WITH p, r "
                    "MATCH (m:Market {poly_id: r.market_id}) "
                    "MERGE (m)-[rel:MENTIONS]->(p) "
                    "SET rel.context = r.context",
                    rows=person_market_rows,
                )

            # Company → Event
            if company_event_rows:
                await session.run(
                    "UNWIND $rows AS r "
                    "MERGE (c:Company {name: r.name}) "
                    "WITH c, r "
                    "MATCH (e:Event {poly_id: r.event_id}) "
                    "MERGE (e)-[rel:MENTIONS]->(c) "
                    "SET rel.context = r.context "
                    "WITH c "
                    "MATCH (d:DataSource {name: 'Polymarket'}) "
                    "MERGE (c)-[:SOURCED_FROM]->(d)",
                    rows=company_event_rows,
                )
                counts["companies"] += len({r["name"] for r in company_event_rows})

            # Company → Market
            if company_market_rows:
                await session.run(
                    "UNWIND $rows AS r "
                    "MERGE (c:Company {name: r.name}) "
                    "WITH c, r "
                    "MATCH (m:Market {poly_id: r.market_id}) "
                    "MERGE (m)-[rel:MENTIONS]->(c) "
                    "SET rel.context = r.context",
                    rows=company_market_rows,
                )

            counts["mentions"] += (
                len(person_event_rows) + len(person_market_rows)
                + len(company_event_rows) + len(company_market_rows)
            )

    # ---- co-mention: persons in the same event ----
    async with driver.session() as session:
        await session.run(
            "MATCH (p1:Person)<-[:MENTIONS]-(e:Event)-[:MENTIONS]->(p2:Person) "
            "WHERE id(p1) < id(p2) "
            "MERGE (p1)-[:CO_MENTIONED_WITH]->(p2)"
        )

    # ---- co-mention: person + company in the same event ----
    async with driver.session() as session:
        await session.run(
            "MATCH (p:Person)<-[:MENTIONS]-(e:Event)-[:MENTIONS]->(c:Company) "
            "MERGE (p)-[:AFFILIATED_WITH]->(c)"
        )

    # ---- co-mention: persons in the same market question ----
    async with driver.session() as session:
        await session.run(
            "MATCH (p1:Person)<-[:MENTIONS]-(m:Market)-[:MENTIONS]->(p2:Person) "
            "WHERE id(p1) < id(p2) "
            "MERGE (p1)-[:CO_MENTIONED_WITH]->(p2)"
        )

    logger.info("Polymarket ingestion complete: %s", counts)
    return counts

# ═══════════════════════════════════════════════════════════════════════════
# Wikipedia enrichment
# ═══════════════════════════════════════════════════════════════════════════


async def _wiki_query(
    title: str, client: httpx.AsyncClient,
) -> dict[str, Any] | None:
    """Single Wikipedia API call. Returns page data or None."""
    try:
        r = await client.get(
            WIKI_API_BASE,
            params={
                "action": "query",
                "titles": title,
                "prop": "extracts|categories",
                "exintro": "true",
                "explaintext": "true",
                "cllimit": "20",
                "format": "json",
                "redirects": "1",
            },
            headers=WIKI_HEADERS,
            timeout=10.0,
        )
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid == "-1":
                return None
            ptitle = page.get("title", title)
            extract = page.get("extract", "")
            if not extract or len(extract) < 30:
                return None
            return {
                "title": ptitle,
                "extract": extract,
                "categories": [
                    c.get("title", "")
                    for c in (page.get("categories") or [])
                ],
                "url": (
                    "https://en.wikipedia.org/wiki/"
                    + ptitle.replace(" ", "_")
                ),
            }
    except Exception as exc:
        logger.warning("Wikipedia lookup failed for '%s': %s", title, exc)
    return None


async def _wiki_summary(
    name: str, client: httpx.AsyncClient,
) -> dict[str, Any] | None:
    """Try exact name, then fallback variants to find a Wikipedia article."""
    result = await _wiki_query(name, client)
    if result:
        return result
    # Try with disambiguation suffixes for prominent people
    for suffix in ("(politician)", "(businessman)", "(executive)"):
        result = await _wiki_query(f"{name} {suffix}", client)
        if result:
            return result
    return None


async def ingest_wikipedia() -> dict[str, int]:
    """Enrich existing Person / Company nodes with Wikipedia summaries,
    and discover affiliations and person-to-person links."""
    driver = _get_driver()
    counts = {
        "enriched_persons": 0, "enriched_companies": 0,
        "new_affiliations": 0, "new_relations": 0,
    }

    # Ensure Wikipedia DataSource
    async with driver.session() as session:
        await session.run(
            "MERGE (d:DataSource {name: $name}) "
            "SET d.type = $type, d.url = $url",
            name="Wikipedia", type="encyclopedia",
            url="https://en.wikipedia.org",
        )

    # Collect un-enriched entities, prioritized by how many events mention them
    persons: list[str] = []
    companies: list[str] = []

    async with driver.session() as session:
        result = await session.run(
            "MATCH (p:Person) WHERE p.wiki_url IS NULL "
            "OPTIONAL MATCH (p)<-[:MENTIONS]-(e) "
            "WITH p, count(e) AS mentions "
            "RETURN p.name AS name, mentions "
            "ORDER BY mentions DESC LIMIT 300"
        )
        raw_persons = await result.data()
        persons = [
            r["name"] for r in raw_persons
            if r.get("name") and _is_likely_person(r["name"])
        ]
        logger.info(
            "Person nodes in DB: %d total, %d pass filter for Wikipedia",
            len(raw_persons), len(persons),
        )

        result = await session.run(
            "MATCH (c:Company) WHERE c.wiki_url IS NULL "
            "OPTIONAL MATCH (c)<-[:MENTIONS]-(e) "
            "WITH c, count(e) AS mentions "
            "RETURN c.name AS name, mentions "
            "ORDER BY mentions DESC LIMIT 150"
        )
        raw_companies = await result.data()
        companies = [r["name"] for r in raw_companies if r.get("name")]
        logger.info(
            "Company nodes in DB: %d total, %d pass filter for Wikipedia",
            len(raw_companies), len(companies),
        )

    logger.info(
        "Wikipedia enrichment: %d persons, %d companies to look up",
        len(persons), len(companies),
    )
    if persons:
        logger.info("Top persons for Wikipedia: %s", persons[:10])
    if companies:
        logger.info("Top companies for Wikipedia: %s", companies[:10])

    async with httpx.AsyncClient(timeout=15.0) as client:
        # ---- persons ----
        wiki_hits = 0
        wiki_misses = 0
        for name in persons:
            wiki = await _wiki_summary(name, client)
            if not wiki:
                wiki_misses += 1
                continue
            wiki_hits += 1

            extract = wiki["extract"][:3000]

            async with driver.session() as session:
                await session.run(
                    "MATCH (p:Person {name: $name}) "
                    "SET p.description = $desc, p.wiki_url = $url "
                    "WITH p "
                    "MATCH (d:DataSource {name: 'Wikipedia'}) "
                    "MERGE (p)-[:SOURCED_FROM]->(d)",
                    name=name, desc=extract[:500], url=wiki["url"],
                )
            counts["enriched_persons"] += 1

            related = extract_entities(extract)

            for org in related["companies"]:
                if org == name:
                    continue
                async with driver.session() as session:
                    await session.run(
                        "MERGE (c:Company {name: $org}) "
                        "WITH c "
                        "MATCH (p:Person {name: $person}) "
                        "MERGE (p)-[:AFFILIATED_WITH]->(c) "
                        "WITH c "
                        "MATCH (d:DataSource {name: 'Wikipedia'}) "
                        "MERGE (c)-[:SOURCED_FROM]->(d)",
                        org=org, person=name,
                    )
                    counts["new_affiliations"] += 1

            for other in related["persons"]:
                if other == name or len(other) < 3:
                    continue
                async with driver.session() as session:
                    await session.run(
                        "MERGE (p2:Person {name: $other}) "
                        "WITH p2 "
                        "MATCH (p1:Person {name: $person}) "
                        "WHERE p1 <> p2 "
                        "MERGE (p1)-[:RELATED_TO]->(p2)",
                        other=other, person=name,
                    )
                    counts["new_relations"] += 1

            await asyncio.sleep(0.15)  # polite rate-limit on Wikipedia

        logger.info(
            "Wikipedia person lookup done: %d hits, %d misses out of %d",
            wiki_hits, wiki_misses, len(persons),
        )

        # ---- companies ----
        for name in companies:
            wiki = await _wiki_summary(name, client)
            if not wiki:
                continue

            extract = wiki["extract"][:3000]

            async with driver.session() as session:
                await session.run(
                    "MATCH (c:Company {name: $name}) "
                    "SET c.description = $desc, c.wiki_url = $url "
                    "WITH c "
                    "MATCH (d:DataSource {name: 'Wikipedia'}) "
                    "MERGE (c)-[:SOURCED_FROM]->(d)",
                    name=name, desc=extract[:500], url=wiki["url"],
                )
            counts["enriched_companies"] += 1

            related = extract_entities(extract)
            for person in related["persons"]:
                if person == name or len(person) < 3:
                    continue
                async with driver.session() as session:
                    await session.run(
                        "MERGE (p:Person {name: $person}) "
                        "WITH p "
                        "MATCH (c:Company {name: $company}) "
                        "MERGE (p)-[:AFFILIATED_WITH]->(c) "
                        "WITH p "
                        "MATCH (d:DataSource {name: 'Wikipedia'}) "
                        "MERGE (p)-[:SOURCED_FROM]->(d)",
                        person=person, company=name,
                    )
                    counts["new_affiliations"] += 1

            await asyncio.sleep(0.15)

    logger.info("Wikipedia enrichment complete: %s", counts)
    return counts

# ═══════════════════════════════════════════════════════════════════════════
# Traversal & query helpers
# ═══════════════════════════════════════════════════════════════════════════


# Allowed end-node labels for traverse filtering
TRAVERSE_LABEL_EVENTS_MARKETS = ("Event", "Market")
TRAVERSE_LABEL_PERSONS_COMPANIES = ("Person", "Company")


async def find_connections(
    node_name: str,
    max_depth: int = 3,
    include_events_markets: bool = True,
    include_persons_companies: bool = True,
) -> list[dict]:
    """Variable-length path traversal from a named node.
    Optionally restrict paths so the end node is one of: Event/Market and/or Person/Company."""
    driver = _get_driver()
    depth = min(max_depth, 6)
    target_labels: list[str] = []
    if include_events_markets:
        target_labels.extend(TRAVERSE_LABEL_EVENTS_MARKETS)
    if include_persons_companies:
        target_labels.extend(TRAVERSE_LABEL_PERSONS_COMPANIES)
    # If both False, we treat as "no filter" (all end nodes) to avoid empty result
    if not target_labels:
        target_labels = list(TRAVERSE_LABEL_EVENTS_MARKETS) + list(TRAVERSE_LABEL_PERSONS_COMPANIES)

    # Exclude paths through DataSource (e.g. Polymarket) so SOURCED_FROM is not traversable
    cypher = (
        "MATCH (start) "
        "WHERE start.name = $name OR start.title = $name "
        "      OR start.label = $name "
        f"MATCH path = (start)-[*1..{depth}]-(connected) "
        "WHERE (size($target_labels) = 0 OR any(lbl IN $target_labels WHERE lbl IN labels(connected))) "
        "  AND none(n IN nodes(path) WHERE n:DataSource) "
        "RETURN "
        "  [n IN nodes(path) | {labels: labels(n), "
        "    name: coalesce(n.name, n.title, n.label, n.question, n.slug), "
        "    id: coalesce(n.poly_id, n.name)}] AS nodes, "
        "  [r IN relationships(path) | type(r)] AS rels "
        "LIMIT 100"
    )
    async with driver.session() as session:
        result = await session.run(
            cypher,
            name=node_name,
            target_labels=target_labels,
        )
        return await result.data()


async def postprocess_merge_duplicate_entities() -> dict[str, Any]:
    """Merge Person/Company nodes whose name is a proper substring of another
    (e.g. merge 'Elon' into 'Elon Musk'). Uses APOC when available."""
    driver = _get_driver()
    merged_persons = 0
    merged_companies = 0
    errors: list[str] = []

    async def find_merge_pairs(label: str) -> list[tuple[str, int]]:
        """Return list of (short_name, long_node_id) to merge short into long."""
        cypher = (
            "MATCH (a:" + label + "), (b:" + label + ") "
            "WHERE a <> b AND b.name CONTAINS a.name AND size(a.name) < size(b.name) "
            "WITH a, b ORDER BY a.name, size(b.name) DESC "
            "WITH a.name AS shortName, collect(b)[0] AS longNode "
            "RETURN shortName, id(longNode) AS longId"
        )
        async with driver.session() as session:
            result = await session.run(cypher)
            return [(r["shortName"], r["longId"]) for r in await result.data()]

    async def merge_with_apoc(label: str, short_name: str, long_id: int) -> bool:
        """Merge short into long using APOC. Returns True if merged."""
        cypher = (
            "MATCH (short:" + label + " {name: $shortName}) "
            "MATCH (long:" + label + ") WHERE id(long) = $longId "
            "CALL apoc.refactor.mergeNodes([long, short]) YIELD node "
            "RETURN node"
        )
        try:
            async with driver.session() as session:
                await session.run(cypher, shortName=short_name, longId=long_id)
            return True
        except Exception as e:
            errors.append(f"{label} {short_name!r}: {e}")
            return False

    async def merge_manual(label: str, short_name: str, long_id: int) -> bool:
        """Merge short into long using apoc.create.relationship, then delete short."""
        try:
            async with driver.session() as session:
                # Copy (short)-[r]-(other) to (long)-[r]-(other) preserving direction
                res = await session.run(
                    "MATCH (short:" + label + " {name: $shortName})-[r]-(other) "
                    "MATCH (long:" + label + ") WHERE id(long) = $longId AND other <> long "
                    "WITH long, other, type(r) AS relType, properties(r) AS relProps, "
                    "  startNode(r) = short AS fromShort "
                    "WITH CASE WHEN fromShort THEN long ELSE other END AS fromN, "
                    "  CASE WHEN fromShort THEN other ELSE long END AS toN, relType, relProps "
                    "CALL apoc.create.relationship(fromN, relType, relProps, toN) YIELD rel "
                    "RETURN count(rel) AS created",
                    shortName=short_name, longId=long_id,
                )
                await res.consume()
                # Delete short and its relationships
                await session.run(
                    "MATCH (short:" + label + " {name: $shortName}) DETACH DELETE short",
                    shortName=short_name,
                )
            return True
        except Exception as e:
            errors.append(f"{label} {short_name!r} (manual): {e}")
            return False

    # Prefer APOC mergeNodes; fall back to manual (uses apoc.create.relationship)
    apoc_available: bool | None = None

    for label in ("Person", "Company"):
        pairs = await find_merge_pairs(label)
        for short_name, long_id in pairs:
            if apoc_available is None:
                try:
                    ok = await merge_with_apoc(label, short_name, long_id)
                    apoc_available = True
                except Exception:
                    apoc_available = False
                    ok = await merge_manual(label, short_name, long_id)
            else:
                ok = await (merge_with_apoc if apoc_available else merge_manual)(
                    label, short_name, long_id
                )
            if ok:
                if label == "Person":
                    merged_persons += 1
                else:
                    merged_companies += 1

    logger.info(
        "Postprocess merge: %d persons, %d companies merged; %d errors",
        merged_persons, merged_companies, len(errors),
    )
    return {
        "merged_persons": merged_persons,
        "merged_companies": merged_companies,
        "errors": errors[:20],
        "apoc_used": apoc_available,
    }


async def find_indirect_datasources(node_name: str) -> list[dict]:
    """Starting from *node_name*, find all reachable DataSource nodes."""
    driver = _get_driver()
    async with driver.session() as session:
        result = await session.run(
            "MATCH (start) "
            "WHERE start.name = $name OR start.title = $name "
            "      OR start.label = $name "
            "MATCH path = (start)-[*1..5]-(ds:DataSource) "
            "RETURN DISTINCT ds.name AS datasource, ds.type AS type, "
            "  ds.url AS url, length(path) AS distance, "
            "  [n IN nodes(path) | "
            "    coalesce(n.name, n.title, n.label, '')] AS via "
            "ORDER BY distance "
            "LIMIT 50",
            name=node_name,
        )
        return await result.data()


async def search_nodes(query: str) -> list[dict]:
    """Full-text search (falls back to CONTAINS if index is missing)."""
    driver = _get_driver()
    async with driver.session() as session:
        try:
            result = await session.run(
                "CALL db.index.fulltext.queryNodes('nodeSearch', $q) "
                "YIELD node, score "
                "RETURN labels(node) AS labels, "
                "  coalesce(node.name, node.title, node.label, "
                "           node.question) AS name, "
                "  coalesce(node.poly_id, node.slug, node.name) AS id, "
                "  node.description AS description, score "
                "ORDER BY score DESC LIMIT 25",
                q=query,
            )
            return await result.data()
        except Exception:
            result = await session.run(
                "MATCH (n) "
                "WHERE n.name CONTAINS $q OR n.title CONTAINS $q "
                "      OR n.label CONTAINS $q "
                "RETURN labels(n) AS labels, "
                "  coalesce(n.name, n.title, n.label, n.question) AS name, "
                "  coalesce(n.poly_id, n.slug, n.name) AS id, "
                "  n.description AS description "
                "LIMIT 25",
                q=query,
            )
            return await result.data()


async def graph_stats() -> dict[str, Any]:
    """Node and relationship counts by label / type."""
    driver = _get_driver()
    stats: dict[str, Any] = {
        "nodes": {}, "relationships": {},
        "total_nodes": 0, "total_relationships": 0,
    }
    async with driver.session() as session:
        result = await session.run(
            "MATCH (n) "
            "RETURN labels(n)[0] AS label, count(*) AS cnt "
            "ORDER BY cnt DESC"
        )
        for rec in await result.data():
            stats["nodes"][rec["label"]] = rec["cnt"]
            stats["total_nodes"] += rec["cnt"]

        result = await session.run(
            "MATCH ()-[r]->() "
            "RETURN type(r) AS type, count(*) AS cnt "
            "ORDER BY cnt DESC"
        )
        for rec in await result.data():
            stats["relationships"][rec["type"]] = rec["cnt"]
            stats["total_relationships"] += rec["cnt"]

    return stats

# ═══════════════════════════════════════════════════════════════════════════
# Related-by-paths: resolve, subset filter, cache, aggregation
# ═══════════════════════════════════════════════════════════════════════════

_VALID_END_TYPES = frozenset({"Person", "Event", "Market", "Company"})
_DEFAULT_END_TYPES = ("Company", "Event", "Market", "Person")


async def _resolve_query_to_start_element_ids(
    query: str, max_starts: int = 20,
) -> list[str]:
    """Return Neo4j elementIds for nodes matching *query* (full-text then CONTAINS)."""
    driver = _get_driver()
    async with driver.session() as session:
        try:
            result = await session.run(
                "CALL db.index.fulltext.queryNodes('nodeSearch', $q) "
                "YIELD node, score "
                "RETURN elementId(node) AS eid "
                "ORDER BY score DESC LIMIT $lim",
                q=query, lim=max_starts,
            )
            data = await result.data()
            if data:
                return [r["eid"] for r in data]
        except Exception:
            pass
        result = await session.run(
            "MATCH (n) "
            "WHERE n.name CONTAINS $q OR n.title CONTAINS $q "
            "      OR n.label CONTAINS $q OR n.question CONTAINS $q "
            "RETURN elementId(n) AS eid LIMIT $lim",
            q=query, lim=max_starts,
        )
        return [r["eid"] for r in await result.data()]


def _path_fails_subset_rule(node_names: list[str]) -> bool:
    """True when the path is redundant: an earlier node's name is a non-empty
    substring of a later node's name (case-insensitive), e.g.
    ``["Elon", "Tesla", "Elon Musk"]`` fails because ``"elon"`` is in ``"elon musk"``."""
    cleaned = [n.strip().lower() for n in node_names if n and n.strip()]
    for i in range(len(cleaned)):
        if len(cleaned[i]) < 2:
            continue
        for j in range(i + 1, len(cleaned)):
            if len(cleaned[j]) < 2:
                continue
            if cleaned[i] != cleaned[j] and cleaned[i] in cleaned[j]:
                return True
    return False


def _rbp_cache_key(
    query: str, depth: int, limit: int,
    end_types: tuple[str, ...], weight_by: str,
) -> tuple:
    return (query.strip().lower(), depth, limit, end_types, weight_by)


def _rbp_cache_get(key: tuple) -> tuple[list[dict], int] | None:
    if key in _RELATED_CACHE:
        results, start_count, ts = _RELATED_CACHE[key]
        if time.monotonic() - ts < _RELATED_CACHE_TTL:
            _RELATED_CACHE.move_to_end(key)
            return results, start_count
        del _RELATED_CACHE[key]
    return None


def _rbp_cache_put(key: tuple, results: list[dict], start_count: int) -> None:
    _RELATED_CACHE[key] = (results, start_count, time.monotonic())
    _RELATED_CACHE.move_to_end(key)
    while len(_RELATED_CACHE) > _RELATED_CACHE_MAX:
        _RELATED_CACHE.popitem(last=False)


async def find_related_by_paths(
    query: str,
    max_depth: int = 4,
    limit: int = 10,
    end_types: tuple[str, ...] = _DEFAULT_END_TYPES,
    weight_by: str = "count",
) -> tuple[list[dict], int, bool]:
    """Top-N Person/Event/Market/Company nodes most related to *query* by
    counting (or length-weighting) distinct graph paths.

    Returns ``(results, start_nodes_matched, cached)``.
    """
    depth = min(max_depth, 6)
    et = tuple(sorted(t for t in end_types if t in _VALID_END_TYPES))
    if not et:
        et = _DEFAULT_END_TYPES

    ck = _rbp_cache_key(query, depth, limit, et, weight_by)
    hit = _rbp_cache_get(ck)
    if hit is not None:
        return hit[0], hit[1], True

    start_ids = await _resolve_query_to_start_element_ids(query)
    if not start_ids:
        return [], 0, False

    driver = _get_driver()
    label_filter = " OR ".join(f"end:{lbl}" for lbl in et)
    cypher = (
        "MATCH (start) WHERE elementId(start) IN $start_ids "
        f"MATCH path = (start)-[*1..{depth}]-(end) "
        f"WHERE ({label_filter}) "
        "  AND end <> start "
        "  AND none(n IN nodes(path) WHERE n:DataSource) "
        "RETURN "
        "  [n IN nodes(path) | coalesce(n.name, n.title, n.label, "
        "       n.question, n.slug, '')] AS node_names, "
        "  length(path) AS path_length, "
        "  elementId(end) AS end_id, "
        "  labels(end) AS end_labels, "
        "  coalesce(end.name, end.title, end.question, end.label, "
        "           end.slug) AS end_name, "
        "  coalesce(end.poly_id, end.slug, end.name) AS end_ext_id, "
        "  end.description AS end_description "
        "LIMIT 2000"
    )
    async with driver.session() as session:
        result = await session.run(cypher, start_ids=start_ids)
        raw_paths = await result.data()

    # Filter by subset rule, then aggregate per destination node
    agg: dict[str, dict] = {}
    for row in raw_paths:
        if _path_fails_subset_rule(row["node_names"]):
            continue

        end_id = row["end_id"]
        path_len = row["path_length"]

        if end_id not in agg:
            end_labels = row["end_labels"]
            node_type = "Unknown"
            for lbl in ("Person", "Event", "Market", "Company"):
                if lbl in end_labels:
                    node_type = lbl
                    break
            agg[end_id] = {
                "type": node_type,
                "name": row["end_name"],
                "id": row["end_ext_id"],
                "description": (row.get("end_description") or "")[:200],
                "path_count": 0,
                "weighted_score": 0.0,
                "min_path_length": path_len,
            }

        entry = agg[end_id]
        entry["path_count"] += 1
        entry["weighted_score"] += 1.0 / (1.0 + path_len)
        if path_len < entry["min_path_length"]:
            entry["min_path_length"] = path_len

    if weight_by == "length":
        sorted_items = sorted(
            agg.values(), key=lambda x: x["weighted_score"], reverse=True,
        )
    else:
        sorted_items = sorted(
            agg.values(), key=lambda x: x["path_count"], reverse=True,
        )

    results: list[dict] = []
    for item in sorted_items[:limit]:
        score = (
            round(item["weighted_score"], 4)
            if weight_by == "length"
            else float(item["path_count"])
        )
        results.append({
            "type": item["type"],
            "name": item["name"],
            "id": item["id"],
            "description": item["description"],
            "connection_score": score,
            "path_count": item["path_count"],
            "min_path_length": item["min_path_length"],
        })

    if limit <= 20 and depth <= 5:
        _rbp_cache_put(ck, results, len(start_ids))

    return results, len(start_ids), False


# ═══════════════════════════════════════════════════════════════════════════
# FastAPI endpoints (mounted via router)
# ═══════════════════════════════════════════════════════════════════════════


class IngestResponse(BaseModel):
    status: str
    polymarket: dict[str, int] = {}
    wikipedia: dict[str, int] = {}


class TraverseResponse(BaseModel):
    name: str
    depth: int
    include_events_markets: bool = True
    include_persons_companies: bool = True
    paths: list[dict] = []


class DatasourceResponse(BaseModel):
    name: str
    datasources: list[dict] = []


class SearchResponse(BaseModel):
    query: str
    results: list[dict] = []


class StatsResponse(BaseModel):
    nodes: dict[str, int] = {}
    relationships: dict[str, int] = {}
    total_nodes: int = 0
    total_relationships: int = 0


class PostprocessResponse(BaseModel):
    merged_persons: int = 0
    merged_companies: int = 0
    errors: list[str] = []
    apoc_used: bool = False


class RelatedByPathsItem(BaseModel):
    type: str
    name: str
    id: str
    description: str = ""
    connection_score: float
    path_count: int
    min_path_length: int


class RelatedByPathsResponse(BaseModel):
    query: str
    results: list[RelatedByPathsItem] = []
    start_nodes_matched: int = 0
    cached: bool = False


@router.post("/ingest", response_model=IngestResponse)
async def api_ingest() -> IngestResponse:
    """Trigger the full ingestion pipeline:
    Polymarket events then Wikipedia enrichment."""
    try:
        poly = await ingest_polymarket()
        wiki = await ingest_wikipedia()
        return IngestResponse(
            status="complete", polymarket=poly, wikipedia=wiki,
        )
    except Exception as exc:
        logger.exception("Ingestion failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/traverse", response_model=TraverseResponse)
async def api_traverse(
    name: str = Query(..., description="Entity name to start from"),
    depth: int = Query(3, ge=1, le=6, description="Max hops"),
    include_events_markets: bool = Query(
        True,
        description="Include paths that end at Event or Market nodes",
    ),
    include_persons_companies: bool = Query(
        True,
        description="Include paths that end at Person or Company nodes",
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


@router.get("/datasources", response_model=DatasourceResponse)
async def api_datasources(
    name: str = Query(..., description="Entity to find linked data sources for"),
) -> DatasourceResponse:
    """Find all DataSource nodes reachable from a named entity."""
    ds = await find_indirect_datasources(name)
    return DatasourceResponse(name=name, datasources=ds)


@router.get("/search", response_model=SearchResponse)
async def api_search(
    q: str = Query(..., min_length=1, description="Search query"),
) -> SearchResponse:
    """Full-text search across all graph nodes."""
    results = await search_nodes(q)
    return SearchResponse(query=q, results=results)


@router.get("/stats", response_model=StatsResponse)
async def api_stats() -> StatsResponse:
    """Graph statistics: node and relationship counts."""
    s = await graph_stats()
    return StatsResponse(**s)
