"""
polymarket_data.py
==================
Stage 1 data extraction — pulls historical price series for target markets.

Key findings from real API response:
  - Event endpoint: GET https://gamma-api.polymarket.com/events?slug={slug}
  - Response is a LIST of event dicts, each with a "markets" list
  - Each market has "clobTokenIds": JSON string of [yes_token, no_token]
  - negRisk events have many bracket sub-markets (e.g. 0-19 tweets, 20-39, ...)
  - Price history: GET https://clob.polymarket.com/prices-history?market={token_id}&fidelity={minutes}
  - Resolved/closed markets may only return data at fidelity >= 720 (12h)

Strategy for negRisk events:
  - Reconstruct a single "implied count" series from bracket YES prices
  - Use weighted midpoint: sum(bracket_midpoint * YES_price) / sum(YES_prices)
  - This gives a continuous probability-weighted estimate of tweet count over time
"""

import json
import time
import requests
import pandas as pd
import numpy as np

# ── API base URLs ─────────────────────────────────────────────────────────────
GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL  = "https://clob.polymarket.com"

# ── Target market slugs ───────────────────────────────────────────────────────
TARGET_MARKETS = {
    "elon_tweets":     "elon-musk-of-tweets-february-17-february-24",
    "gold_price":      "what-will-gold-gc-hit-by-end-of-february",
    "spacex_launches": "how-many-spacex-launches-in-february",
    "tsla_price":      "tsla-above-in-february-2026",
}

FIDELITY_MINUTES = 60   # 1-hour candles for active markets


# ─────────────────────────────────────────────────────────────────────────────
# 1.  GAMMA API — resolve slug to market list
# ─────────────────────────────────────────────────────────────────────────────

def get_event_markets(slug: str) -> list[dict]:
    """
    Fetch all sub-markets for a given event slug.

    Returns list of dicts, each containing:
        question, groupItemTitle, groupItemThreshold,
        token_yes, token_no, active, closed, lastTradePrice
    """
    resp = requests.get(f"{GAMMA_URL}/events", params={"slug": slug}, timeout=15)
    resp.raise_for_status()
    events = resp.json()

    if not events:
        raise ValueError(f"No event found for slug: '{slug}'")

    event = events[0]
    raw_markets = event.get("markets", [])

    parsed = []
    for m in raw_markets:
        # clobTokenIds is a JSON-encoded string: '["token_yes", "token_no"]'
        raw_tokens = m.get("clobTokenIds", "[]")
        try:
            token_ids = json.loads(raw_tokens)
        except Exception:
            token_ids = []

        parsed.append({
            "question":           m.get("question", ""),
            "groupItemTitle":     m.get("groupItemTitle", ""),
            "groupItemThreshold": m.get("groupItemThreshold", 0),
            "token_yes":          token_ids[0] if len(token_ids) > 0 else None,
            "token_no":           token_ids[1] if len(token_ids) > 1 else None,
            "active":             m.get("active", False),
            "closed":             m.get("closed", False),
            "lastTradePrice":     m.get("lastTradePrice", None),
            "outcomePrices":      m.get("outcomePrices", '["0","1"]'),
        })

    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# 2.  CLOB API — fetch price history for a single token
# ─────────────────────────────────────────────────────────────────────────────

def get_price_history(
    token_id: str,
    fidelity: int = FIDELITY_MINUTES,
) -> pd.DataFrame:
    """
    Fetch CLOB price history for one token_id.

    Returns DataFrame with columns: timestamp (UTC datetime), price (float 0-1).
    Falls back to 720-min fidelity if fine-grained returns empty (resolved markets).
    """
    def _fetch(fid):
        resp = requests.get(
            f"{CLOB_URL}/prices-history",
            params={"market": token_id, "interval": "max", "fidelity": fid},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        history = data.get("history", [])
        if not history:
            return pd.DataFrame(columns=["timestamp", "price"])
        df = pd.DataFrame(history).rename(columns={"t": "timestamp", "p": "price"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df["price"] = df["price"].astype(float)
        return df.sort_values("timestamp").reset_index(drop=True)

    df = _fetch(fidelity)
    if df.empty:
        print(f"      ⚠ Empty at {fidelity}min — retrying at 720min")
        df = _fetch(720)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 3.  NEGRISK AGGREGATION — implied count from bracket probabilities
# ─────────────────────────────────────────────────────────────────────────────

def parse_bracket_midpoint(title: str) -> float | None:
    """
    Parse groupItemTitle like '320-339', '580+', '<20' into a numeric midpoint.

    Examples:
        '320-339' → 329.5
        '580+'    → 590.0
        '<20'     → 10.0
    """
    title = title.strip()
    if title.endswith("+"):
        return float(title[:-1]) + 10
    if title.startswith("<"):
        return float(title[1:]) / 2
    if "-" in title:
        parts = title.split("-")
        try:
            lo, hi = float(parts[0]), float(parts[1])
            return (lo + hi) / 2
        except ValueError:
            return None
    try:
        return float(title)
    except ValueError:
        return None


def build_implied_count_series(
    markets: list[dict],
    fidelity: int = FIDELITY_MINUTES,
    resample_freq: str = "1h",
) -> pd.DataFrame:
    """
    For a negRisk event, fetch YES price history for each bracket and compute
    a probability-weighted implied count at each timestamp.

    Formula:
        implied_count(t) = Σ(midpoint_i * p_yes_i(t)) / Σ(p_yes_i(t))

    This is the market's collective best-guess of the underlying value (tweet
    count, price level, etc.) at each point in time — a continuous signal
    extracted from discrete bracket probabilities.

    Returns: DataFrame with column 'implied_count', indexed by timestamp.
    """
    bracket_series: dict[float, pd.Series] = {}

    for m in markets:
        if m["token_yes"] is None:
            continue
        midpoint = parse_bracket_midpoint(m["groupItemTitle"])
        if midpoint is None:
            continue

        print(f"    [bracket {m['groupItemTitle']:>10}] mid={midpoint:<7}  token={m['token_yes'][:14]}...")
        try:
            df = get_price_history(m["token_yes"], fidelity=fidelity)
            if df.empty:
                continue
            s = df.set_index("timestamp")["price"]
            s = s.resample(resample_freq).last().ffill()
            bracket_series[midpoint] = s
            print(f"      ✓ {len(s)} rows")
        except Exception as e:
            print(f"      ✗ {e}")
        time.sleep(0.25)

    if not bracket_series:
        return pd.DataFrame(columns=["implied_count"])

    # Align all bracket series on common time index
    all_df = pd.DataFrame(bracket_series).ffill().bfill()
    midpoints = np.array(sorted(bracket_series.keys()))
    weights   = all_df[midpoints].values           # shape (T, N)
    row_sums  = weights.sum(axis=1, keepdims=True)
    row_sums  = np.where(row_sums == 0, 1.0, row_sums)
    implied   = (weights * midpoints).sum(axis=1) / row_sums.squeeze()

    return pd.DataFrame({"implied_count": implied}, index=all_df.index)


# ─────────────────────────────────────────────────────────────────────────────
# 4.  STANDARD MARKET — one YES price series per sub-market
# ─────────────────────────────────────────────────────────────────────────────

def build_standard_series(
    label: str,
    markets: list[dict],
    fidelity: int = FIDELITY_MINUTES,
    resample_freq: str = "1h",
) -> dict[str, pd.DataFrame]:
    """
    For a non-negRisk event, return one YES price series per sub-market.
    Column keys: '{label}__{groupItemTitle}__YES'
    """
    series = {}
    for m in markets:
        if m["token_yes"] is None:
            continue
        tag = m["groupItemTitle"] or m["question"][:35]
        key = f"{label}__{tag}__YES"
        print(f"    [market] {key[:60]}  token={m['token_yes'][:14]}...")
        try:
            df = get_price_history(m["token_yes"], fidelity=fidelity)
            if df.empty:
                print(f"      ✗ no data")
                continue
            s = df.set_index("timestamp")["price"]
            s = s.resample(resample_freq).last().ffill()
            series[key] = s.to_frame(name=key)
            print(f"      ✓ {len(s)} rows  ({s.index.min()} → {s.index.max()})")
        except Exception as e:
            print(f"      ✗ {e}")
        time.sleep(0.25)
    return series


# ─────────────────────────────────────────────────────────────────────────────
# 5.  DETECT NEGRISK vs STANDARD
# ─────────────────────────────────────────────────────────────────────────────

def is_neg_risk(markets: list[dict]) -> bool:
    """
    negRisk events have many bracket sub-markets with parseable groupItemTitles.
    Heuristic: >3 sub-markets AND >60% have parseable numeric brackets.
    """
    if len(markets) <= 3:
        return False
    parseable = sum(
        1 for m in markets
        if parse_bracket_midpoint(str(m.get("groupItemTitle", ""))) is not None
    )
    return parseable > len(markets) * 0.6


# ─────────────────────────────────────────────────────────────────────────────
# 6.  MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def run_extraction(
    fidelity:      int  = FIDELITY_MINUTES,
    resample_freq: str  = "1h",
    save_csv:      bool = True,
    csv_path:      str  = "polymarket_prices.csv",
) -> pd.DataFrame:
    """
    Full extraction pipeline:
      slug → market metadata → price history → merged DataFrame

    negRisk events (bracket markets) → one 'implied_count' column
    Standard events                  → one YES price column per outcome

    Returns wide DataFrame: rows=timestamps, columns=series, values=price (0-1) or count.
    """
    print("=" * 65)
    print("POLYMARKET DATA EXTRACTION PIPELINE")
    print("=" * 65)

    all_series: dict[str, pd.DataFrame] = {}

    for label, slug in TARGET_MARKETS.items():
        print(f"\n{'─'*65}")
        print(f"[{label}]  slug: {slug}")
        print(f"{'─'*65}")

        try:
            markets = get_event_markets(slug)
            print(f"  Found {len(markets)} sub-markets")
        except Exception as e:
            print(f"  ✗ Could not fetch event: {e}")
            continue

        if not markets:
            continue

        if is_neg_risk(markets):
            print(f"  → negRisk bracket market — building implied series")
            implied_df = build_implied_count_series(markets, fidelity, resample_freq)
            if not implied_df.empty:
                col = f"{label}__implied"
                implied_df.columns = [col]
                all_series[col] = implied_df
                print(f"  ✓ '{col}': {len(implied_df)} rows")
        else:
            print(f"  → Standard market — building YES price series per outcome")
            series = build_standard_series(label, markets, fidelity, resample_freq)
            all_series.update(series)

        time.sleep(0.3)

    if not all_series:
        raise RuntimeError("No data retrieved. Check slugs and network connectivity.")

    # ── Merge ─────────────────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"[merging] {len(all_series)} series")
    merged = pd.concat(list(all_series.values()), axis=1, join="outer").ffill().bfill()

    print(f"  → Shape:      {merged.shape}")
    print(f"  → Time range: {merged.index.min()} → {merged.index.max()}")
    print(f"  → Columns:")
    for col in merged.columns:
        print(f"       {col}")

    if save_csv:
        merged.to_csv(csv_path)
        print(f"\n  ✓ Saved to '{csv_path}'")

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY — inspect a slug without fetching price history
# ─────────────────────────────────────────────────────────────────────────────

def inspect_slug(slug: str):
    """Print a quick summary of sub-markets and their current prices."""
    markets = get_event_markets(slug)
    print(f"\nSlug: {slug}  ({len(markets)} sub-markets)\n")
    print(f"{'Title':<15} {'LastPrice':>10} {'Closed':>7}  Question")
    print("-" * 80)
    for m in markets:
        print(
            f"{str(m['groupItemTitle']):<15} "
            f"{str(m['lastTradePrice']):>10} "
            f"{str(m['closed']):>7}  "
            f"{m['question'][:50]}"
        )


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    df = run_extraction(
        fidelity=60,
        resample_freq="1h",
        save_csv=True,
        csv_path="polymarket_prices.csv",
    )
    print("\n── Last 5 rows ──")
    print(df.tail(5).to_string())