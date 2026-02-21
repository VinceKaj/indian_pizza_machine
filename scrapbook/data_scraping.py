"""
polymarket_data.py
==================
Stage 1 data extraction: fetch historical price series for target markets.

Pipeline:
  URL slug → Gamma API (event/market metadata + token IDs)
           → CLOB API (prices-history per token)
           → pd.DataFrame per market
           → merged DataFrame (aligned on timestamp)

Markets:
  - Elon Musk tweet count  (target)
  - Gold price end of Feb
  - SpaceX launches in Feb
  - TSLA above X in Feb 2026
"""

import time
import requests
import pandas as pd

# ── API base URLs ────────────────────────────────────────────────────────────
GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL  = "https://clob.polymarket.com"

# ── Market slugs extracted from the provided URLs ───────────────────────────
# Format: { label: event_slug }
TARGET_MARKETS = {
    "elon_tweets":    "elon-musk-of-tweets-february-17-february-24",
    "gold_price":     "what-will-gold-gc-hit-by-end-of-february",
    "spacex_launches":"how-many-spacex-launches-in-february",
    "tsla_price":     "tsla-above-in-february-2026",
}

# ── Fidelity / interval settings ─────────────────────────────────────────────
# For ACTIVE markets you can go as fine as 1-minute fidelity.
# For RESOLVED markets the API only returns ≥12h granularity (known limitation).
# We use 60-min fidelity as a safe default for active markets.
FIDELITY_MINUTES = 60          # minutes per data point
INTERVAL         = "max"       # pull full history ("max" | "1w" | "1d" | "6h" | "1h")


# ─────────────────────────────────────────────────────────────────────────────
# 1.  RESOLVE SLUG → MARKETS + TOKEN IDs via Gamma API
# ─────────────────────────────────────────────────────────────────────────────

def get_event_markets(slug: str) -> list[dict]:
    """
    Given a Polymarket event slug, return list of market dicts.
    Each dict contains: conditionId, question, tokens (list of {token_id, outcome}).
    """
    resp = requests.get(f"{GAMMA_URL}/events", params={"slug": slug}, timeout=10)
    resp.raise_for_status()
    events = resp.json()

    if not events:
        raise ValueError(f"No event found for slug: {slug}")

    # An event can contain multiple markets (one per outcome bracket).
    event = events[0]
    markets = event.get("markets", [])

    parsed = []
    for m in markets:
        tokens = [
            {"token_id": t["token_id"], "outcome": t["outcome"]}
            for t in m.get("tokens", [])
        ]
        parsed.append({
            "condition_id": m.get("conditionId"),
            "question":     m.get("question"),
            "tokens":       tokens,
            "active":       m.get("active"),
            "closed":       m.get("closed"),
        })

    return parsed


def discover_all_markets() -> dict[str, list[dict]]:
    """
    Resolve all TARGET_MARKETS slugs. Returns:
    { label: [ market_dict, ... ] }
    """
    result = {}
    for label, slug in TARGET_MARKETS.items():
        print(f"[discovery] Fetching markets for '{label}' ...")
        try:
            markets = get_event_markets(slug)
            result[label] = markets
            for m in markets:
                print(f"  → {m['question']}")
                for t in m["tokens"]:
                    print(f"     token_id={t['token_id']}  outcome={t['outcome']}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            result[label] = []
        time.sleep(0.3)   # be polite to the API
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2.  FETCH PRICE HISTORY via CLOB API
# ─────────────────────────────────────────────────────────────────────────────

def get_price_history(
    token_id:        str,
    interval:        str = INTERVAL,
    fidelity:        int = FIDELITY_MINUTES,
    start_ts:        int | None = None,
    end_ts:          int | None = None,
) -> pd.DataFrame:
    """
    Fetch CLOB price history for a single token_id.

    Returns a DataFrame with columns:
        timestamp (datetime, UTC), price (float, 0-1 probability)

    Note: for resolved markets fidelity < 720 (12h) may return empty data.
    """
    params: dict = {
        "market":   token_id,
        "interval": interval,
        "fidelity": fidelity,
    }
    if start_ts:
        params["startTs"] = start_ts
    if end_ts:
        params["endTs"]   = end_ts

    resp = requests.get(f"{CLOB_URL}/prices-history", params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    history = data.get("history", [])
    if not history:
        return pd.DataFrame(columns=["timestamp", "price"])

    df = pd.DataFrame(history)                       # columns: t (unix), p (price)
    df = df.rename(columns={"t": "timestamp", "p": "price"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df["price"]     = df["price"].astype(float)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def fetch_market_series(
    label:    str,
    markets:  list[dict],
    fidelity: int = FIDELITY_MINUTES,
) -> dict[str, pd.DataFrame]:
    """
    For a given market label and its list of market dicts,
    fetch price history for every YES token.

    Returns: { "label__question__YES": DataFrame, ... }
    """
    series = {}
    for m in markets:
        q = m["question"][:60].replace(" ", "_")   # short key fragment
        for t in m["tokens"]:
            if t["outcome"].upper() != "YES":
                continue                             # we focus on YES probability
            key = f"{label}__{q}__YES"
            print(f"  [fetch] {key}  token={t['token_id'][:12]}...")
            try:
                df = get_price_history(t["token_id"], fidelity=fidelity)
                if df.empty:
                    print(f"    ⚠ empty — trying 720-min fidelity (resolved market fallback)")
                    df = get_price_history(t["token_id"], fidelity=720)
                df = df.set_index("timestamp")
                df.columns = [key]                   # rename 'price' → market key
                series[key] = df
                print(f"    ✓ {len(df)} rows  ({df.index.min()} → {df.index.max()})")
            except Exception as e:
                print(f"    ✗ {e}")
            time.sleep(0.3)
    return series


# ─────────────────────────────────────────────────────────────────────────────
# 3.  MERGE ALL SERIES INTO A SINGLE ALIGNED DATAFRAME
# ─────────────────────────────────────────────────────────────────────────────

def merge_series(
    all_series: dict[str, pd.DataFrame],
    resample_freq: str = "1h",
) -> pd.DataFrame:
    """
    Merge all price series into one DataFrame aligned on a common time index.

    Steps:
      1. Resample each series to a fixed frequency (forward-fill gaps).
      2. Outer-join all series on timestamp.
      3. Forward-fill then back-fill to handle edge NaNs.

    Args:
        all_series:    dict of { key: single-column DataFrame indexed by timestamp }
        resample_freq: pandas offset string e.g. "1h", "30min", "1d"

    Returns:
        Wide DataFrame: rows = timestamps, columns = market keys, values = prices (0-1)
    """
    resampled = {}
    for key, df in all_series.items():
        rs = df.resample(resample_freq).last().ffill()
        resampled[key] = rs

    merged = pd.concat(resampled.values(), axis=1, join="outer")
    merged.columns = list(resampled.keys())
    merged = merged.ffill().bfill()
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# 4.  MAIN — run the full extraction pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_extraction(
    fidelity:      int = FIDELITY_MINUTES,
    resample_freq: str = "1h",
    save_csv:      bool = True,
    csv_path:      str = "polymarket_prices.csv",
) -> pd.DataFrame:
    """
    Full pipeline: slug discovery → price history → merged DataFrame.

    Returns the merged wide DataFrame and optionally saves to CSV.
    """
    print("=" * 60)
    print("POLYMARKET DATA EXTRACTION")
    print("=" * 60)

    # Step 1: discover markets
    all_markets = discover_all_markets()

    # Step 2: fetch price history for each market
    all_series = {}
    for label, markets in all_markets.items():
        if not markets:
            continue
        print(f"\n[fetching] {label}")
        series = fetch_market_series(label, markets, fidelity=fidelity)
        all_series.update(series)

    if not all_series:
        raise RuntimeError("No price data retrieved. Check slugs and API connectivity.")

    # Step 3: merge
    print(f"\n[merging] {len(all_series)} series at '{resample_freq}' frequency...")
    merged = merge_series(all_series, resample_freq=resample_freq)
    print(f"  → DataFrame shape: {merged.shape}")
    print(f"  → Time range: {merged.index.min()} → {merged.index.max()}")
    print(f"  → Columns:\n    " + "\n    ".join(merged.columns.tolist()))

    if save_csv:
        merged.to_csv(csv_path)
        print(f"\n  ✓ Saved to '{csv_path}'")

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY: manually specify token IDs (bypass slug resolution if needed)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_by_token_ids(
    token_map:     dict[str, str],
    fidelity:      int = FIDELITY_MINUTES,
    resample_freq: str = "1h",
) -> pd.DataFrame:
    """
    Alternative entry point if you already know the token IDs.

    Args:
        token_map: { "human_readable_label": "token_id_hex_string" }

    Example:
        df = fetch_by_token_ids({
            "elon_tweets_yes":  "0xABC...",
            "gold_above_2900":  "0xDEF...",
        })
    """
    all_series = {}
    for label, token_id in token_map.items():
        print(f"[fetch] {label}  token={token_id[:12]}...")
        try:
            df = get_price_history(token_id, fidelity=fidelity)
            if df.empty:
                df = get_price_history(token_id, fidelity=720)
            df = df.set_index("timestamp")
            df.columns = [label]
            all_series[label] = df
            print(f"  ✓ {len(df)} rows")
        except Exception as e:
            print(f"  ✗ {e}")
        time.sleep(0.3)

    return merge_series(all_series, resample_freq=resample_freq)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    df = run_extraction(
        fidelity=60,          # 1-hour candles
        resample_freq="1h",
        save_csv=True,
        csv_path="polymarket_prices.csv",
    )
    print("\nSample output:")
    print(df.tail(10).to_string())