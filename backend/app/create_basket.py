import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import requests
from datetime import datetime, timedelta
import logging

from app.filter_inputs import filter_by_semantic_similarity

logger = logging.getLogger(__name__)


def get_clob_token_ids(market_id):
    """
    Fetch CLOB token IDs from a Polymarket market ID.
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


def fetch_historical_prices(clob_token_id, start_ts, end_ts):
    """
    Fetches historical prices from Polymarket using CLOB token ID.
    """
    url = "https://clob.polymarket.com/prices-history"
    params = {
        "market": clob_token_id,
        "startTs": int(start_ts),
        "endTs": int(end_ts),
        "fidelity": 60  # 60-minute fidelity
    }
    
    response = requests.get(url, params=params)
    data = response.json().get('history', [])
    
    if not data:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    
    df = pd.DataFrame(data)
    df['datetime'] = pd.to_datetime(df['t'], unit='s')
    df.set_index('datetime', inplace=True)
    s = df['p'].astype(float)
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    return s


def build_synthetic_basket(target_market_id, input_market_ids, days=7, verbose=False,
                           use_semantic_filter=True, top_k_semantic=10, min_similarity=0.4,
                           max_target_similarity=0.95):
    """
    Build a synthetic basket to replicate a target market using input markets.
    
    Args:
        target_market_id: Polymarket market ID for the target
        input_market_ids: List of Polymarket market IDs for inputs
        days: Number of days of historical data to use (default: 7)
        verbose: Whether to print progress messages (default: False)
        use_semantic_filter: Whether to filter inputs by semantic similarity (default: True)
        top_k_semantic: Number of top semantically similar markets to keep (default: 10)
        min_similarity: Minimum cosine similarity threshold (default: 0.4)
        max_target_similarity: Maximum similarity to target - filters out near-duplicates (default: 0.95)
    
    Returns:
        dict with:
            - target_prices: list of floats
            - synthetic_prices: list of floats
            - weights: list of dicts with {title, market_id, weight}
            - r_squared: float
            - timestamps: list of ISO datetime strings
    """
    logger.info(f"🚀 Starting basket creation for target market {target_market_id}")
    logger.info(f"📊 Parameters: {len(input_market_ids)} input markets, {days} days, semantic_filter={use_semantic_filter}")
    
    # Set time window
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    start_ts = start_date.timestamp()
    end_ts = end_date.timestamp()
    
    logger.info(f"📅 Time window: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")

    # 1. Fetch target market metadata
    logger.info(f"[1/5] 🎯 Fetching target market metadata...")
    target_clob, _, target_question, target_description = get_clob_token_ids(target_market_id)
    logger.info(f"Target: {target_question}")
    
    # 2. Fetch input market metadata and optionally filter by semantic similarity
    logger.info(f"[2/5] 📥 Fetching input market metadata...")
    
    # First, fetch all candidate market questions and descriptions
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
    
    logger.info(f"Successfully fetched {len(candidate_dict)}/{len(input_market_ids)} candidate markets")
    
    # Apply semantic filtering if enabled
    # if use_semantic_filter and len(candidate_dict) > top_k_semantic:
    if use_semantic_filter and len(candidate_dict) > 2:
        filtered_market_ids = filter_by_semantic_similarity(
            target_question, 
            candidate_dict, 
            top_k=top_k_semantic,
            min_similarity=min_similarity,
            verbose=verbose,
            target_description=target_description,
            max_target_similarity=max_target_similarity
        )
    else:
        filtered_market_ids = list(candidate_dict.keys())
        logger.info(f"Using all {len(filtered_market_ids)} input markets (semantic filtering disabled or not needed)")
    
    # Fetch CLOB token IDs for filtered markets
    input_info = []
    for market_id in filtered_market_ids:
        clob_id, _, question, description = get_clob_token_ids(market_id)
        input_info.append({'market_id': market_id, 'clob_id': clob_id, 'question': question})

    # 3. Fetch historical prices
    logger.info(f"[3/5] 💹 Fetching price histories for {len(input_info)+1} markets...")
    target_series = fetch_historical_prices(target_clob, start_ts, end_ts)
    target_series.name = 'Target'
    logger.info(f"Target: {len(target_series)} data points")
    
    input_series_list = []
    for i, info in enumerate(input_info):
        series = fetch_historical_prices(info['clob_id'], start_ts, end_ts)
        series.name = info['question']
        input_series_list.append(series)
        logger.info(f"Input {i+1}/{len(input_info)}: {len(series)} data points")

    # 4. Align and resample data
    logger.info(f"[4/5] 📐 Aligning time series data to hourly bars...")
    
    def ensure_datetime_index(series):
        if series.empty:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        if not isinstance(series.index, pd.DatetimeIndex):
            series = series.copy()
            series.index = pd.to_datetime(series.index)
        return series

    target_series = ensure_datetime_index(target_series)
    target_resampled = target_series.resample('1h').last().ffill()
    logger.info(f"Target: {len(target_series)} ticks → {len(target_resampled)} bars")
    
    input_resampled_list = []
    for i, series in enumerate(input_series_list):
        series = ensure_datetime_index(series)
        resampled = series.resample('1h').last().ffill()
        resampled.name = series.name
        input_resampled_list.append(resampled)
    
    # Align to target's index so we keep every target observation
    idx = target_resampled.index
    input_aligned = [
        s.reindex(idx).ffill().bfill()
        for s in input_resampled_list
    ]
    df = pd.concat([target_resampled] + input_aligned, axis=1)
    df = df.dropna(subset=['Target'])
    df = df.fillna(0.0)
    
    logger.info(f"After alignment: {len(df)} hourly observations")
    
    if df.empty:
        raise ValueError("No overlapping time-series data after alignment.")

    # 5. Solve linear regression (OLS)
    logger.info(f"[5/5] 🧮 Solving for optimal weights using OLS...")
    y = df['Target'].values
    X = df.drop(columns=['Target']).values
    
    # Standard least squares: minimize ||y - Xw||^2
    ols_weights, residuals, rank, s = np.linalg.lstsq(X, y, rcond=None)
    
    # Calculate synthetic price
    df['Synthetic'] = X @ ols_weights
    
    # Calculate R-squared
    ss_res = np.sum((y - df['Synthetic'].values)**2)
    ss_tot = np.sum((y - y.mean())**2)
    r_squared = 1 - (ss_res / ss_tot)

    logger.info(f"✅ Basket created successfully! R² = {r_squared:.4f}")
    logger.info("Weights:")
    for i, info in enumerate(input_info):
        logger.info(f"  {ols_weights[i]:+.6f} | {info['question'][:60]}...")
    
    # Format output for API
    weights_output = [
        {
            "title": info['question'],
            "market_id": info['market_id'],
            "weight": float(ols_weights[i])
        }
        for i, info in enumerate(input_info)
    ]
    
    # Return results
    return {
        'target_prices': df['Target'].tolist(),
        'synthetic_prices': df['Synthetic'].tolist(),
        'weights': weights_output,
        'r_squared': float(r_squared),
        'timestamps': [ts.isoformat() for ts in df.index],
        'target_question': target_question
    }


def main(target_market_id, input_market_ids, days=7):
    result = build_synthetic_basket(target_market_id, input_market_ids, days=days, verbose=True)