import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import requests
from datetime import datetime, timedelta

# Set style
# sns.set_style("whitegrid")
# plt.rcParams['figure.figsize'] = (14, 8)

def get_clob_token_ids(market_id):
    """
    Fetch CLOB token IDs from a Polymarket market ID.
    Returns (yes_token_id, no_token_id, market_question)
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
    
    return clob_ids[0], clob_ids[1], data.get('question', 'Unknown')

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
        return pd.Series(dtype=float)
    
    df = pd.DataFrame(data)
    df['datetime'] = pd.to_datetime(df['t'], unit='s')
    df.set_index('datetime', inplace=True)
    return df['p'].astype(float)

def build_synthetic_basket(target_market_id, input_market_ids, days=7, verbose=False):
    """
    Build a synthetic basket to replicate a target market using input markets.
    
    Args:
        target_market_id: Polymarket market ID for the target
        input_market_ids: List of Polymarket market IDs for inputs
        days: Number of days of historical data to use (default: 7)
        verbose: Whether to print progress messages (default: False)
    
    Returns:
        dict with:
            - target_prices: list of floats
            - synthetic_prices: list of floats
            - weights: list of dicts with {title, market_id, weight}
            - r_squared: float
            - timestamps: list of ISO datetime strings
    """
    # Set time window
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    start_ts = start_date.timestamp()
    end_ts = end_date.timestamp()
    
    if verbose:
        print(f"Time window: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        print("=" * 60)

    # 1. Fetch CLOB token IDs and market info
    if verbose:
        print(f"\n[1/4] Fetching market metadata...")
    target_clob, _, target_question = get_clob_token_ids(target_market_id)
    if verbose:
        print(f"Target: {target_question}")
    
    input_info = []
    for market_id in input_market_ids:
        clob_id, _, question = get_clob_token_ids(market_id)
        input_info.append({'market_id': market_id, 'clob_id': clob_id, 'question': question})
        if verbose:
            print(f"Input:  {question}")

    # 2. Fetch historical prices
    if verbose:
        print(f"\n[2/4] Fetching price histories...")
    target_series = fetch_historical_prices(target_clob, start_ts, end_ts)
    target_series.name = 'Target'
    if verbose:
        print(f"Target: {len(target_series)} data points")
    
    input_series_list = []
    for info in input_info:
        series = fetch_historical_prices(info['clob_id'], start_ts, end_ts)
        series.name = info['question']
        input_series_list.append(series)
        if verbose:
            print(f"Input:  {len(series)} data points - {info['question'][:50]}")

    # 3. Align and resample data
    if verbose:
        print(f"\n[3/4] Aligning time series data...")
        print("Resampling each series to hourly bars...")
    
    target_resampled = target_series.resample('1h').last().ffill()
    if verbose:
        print(f"Target: {len(target_series)} ticks → {len(target_resampled)} bars")
    
    input_resampled_list = []
    for i, series in enumerate(input_series_list):
        resampled = series.resample('1h').last().ffill()
        resampled.name = series.name
        input_resampled_list.append(resampled)
        if verbose:
            print(f"Input {i+1}: {len(series)} ticks → {len(resampled)} bars")
    
    # Concat on same time grid
    df = pd.concat([target_resampled] + input_resampled_list, axis=1, sort=True)
    df = df.ffill()
    df = df.dropna()
    
    if verbose:
        print(f"After alignment: {len(df)} aligned observations")
    
    if df.empty:
        raise ValueError("No overlapping time-series data after alignment.")

    # 4. Solve linear regression (OLS)
    if verbose:
        print(f"\n[4/4] Solving for optimal weights using OLS...")
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

    if verbose:
        print("\n" + "=" * 60)
        print("OPTIMAL BASKET WEIGHTS (OLS)")
        print("=" * 60)
        for i, info in enumerate(input_info):
            print(f"{ols_weights[i]:+.4f}  | {info['question']}")
        print(f"\nR² (fit quality): {r_squared:.4f}")
    
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
    result = build_synthetic_basket(target_market_id, input_market_ids, days=days)