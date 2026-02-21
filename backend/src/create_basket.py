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

def build_synthetic_basket(target_market_id, input_market_ids, days=7):

    """
    Build a synthetic basket to replicate a target market using input markets.
    
    Args:
        target_market_id: Polymarket market ID for the target
        input_market_ids: List of Polymarket market IDs for inputs
        days: Number of days of historical data to use (default: 7)
    
    Returns:
        dict with weights, market info, R-squared, and dataframe
    """
    # Set time window
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    start_ts = start_date.timestamp()
    end_ts = end_date.timestamp()
    
    print(f"Time window: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print("=" * 60)

    # 1. Fetch CLOB token IDs and market info
    print(f"\n[1/4] Fetching market metadata...")
    target_clob, _, target_question = get_clob_token_ids(target_market_id)
    print(f"Target: {target_question}")
    
    input_info = []
    for market_id in input_market_ids:
        clob_id, _, question = get_clob_token_ids(market_id)
        input_info.append({'market_id': market_id, 'clob_id': clob_id, 'question': question})
        print(f"Input:  {question}")

    # 2. Fetch historical prices
    print(f"\n[2/4] Fetching price histories...")
    target_series = fetch_historical_prices(target_clob, start_ts, end_ts)
    target_series.name = 'Target'
    print(f"Target: {len(target_series)} data points")
    
    input_series_list = []
    for info in input_info:
        series = fetch_historical_prices(info['clob_id'], start_ts, end_ts)
        series.name = info['question'][:40] + '...' if len(info['question']) > 40 else info['question']
        input_series_list.append(series)
        print(f"Input:  {len(series)} data points - {info['question'][:50]}")

    # 3. Align and resample data
    print(f"\n[3/4] Aligning time series data...")
    
    # Resample each series INDIVIDUALLY to 5-minute bars first (close price of each bar)
    # This aligns irregular market ticks to a regular time grid
    print("Resampling each series to 5-minute bars...")
    target_resampled = target_series.resample('5min').ffill()
    print(f"Target: {len(target_series)} ticks → {len(target_resampled)} bars")
    
    input_resampled_list = []
    for i, series in enumerate(input_series_list):
        resampled = series.resample('5min').ffill()
        resampled.name = series.name
        input_resampled_list.append(resampled)
        print(f"Input {i+1}: {len(series)} ticks → {len(resampled)} bars")
    
    # Now concat the resampled series - they're all on the same time grid
    df = pd.concat([target_resampled] + input_resampled_list, axis=1, sort=True)
    print(f"\nAfter concat: {len(df)} rows")
    print(f"Date range: {df.index.min()} to {df.index.max()}")
    
    # Forward fill any remaining gaps
    df = df.ffill()
    
    # Drop rows with any NaN values
    initial_len = len(df)
    df = df.dropna()
    print(f"After dropna: {len(df)} aligned observations ({initial_len - len(df)} rows dropped)")
    
    if df.empty:
        print("\nDEBUG: DataFrame is empty after alignment!")
        raise ValueError("No overlapping time-series data after alignment.")

    # 4. Solve linear regression (Least Squares)
    print(f"\n[4/4] Solving for optimal weights...")
    y = df['Target'].values
    X = df.drop(columns=['Target']).values
    
    # Standard least squares: minimize ||y - Xw||^2
    weights, residuals, rank, s = np.linalg.lstsq(X, y, rcond=None)
    
    # Calculate synthetic price
    df['Synthetic'] = X @ weights
    
    # Calculate R-squared
    ss_res = np.sum((y - df['Synthetic'].values)**2)
    ss_tot = np.sum((y - y.mean())**2)
    r_squared = 1 - (ss_res / ss_tot)

    # 5. Display results
    print("\n" + "=" * 60)
    print("OPTIMAL BASKET WEIGHTS")
    print("=" * 60)
    for i, info in enumerate(input_info):
        print(f"{weights[i]:+.4f}  | {info['question']}")
    print(f"\nR² (fit quality): {r_squared:.4f}")
    print(f"Mean Absolute Error: {np.mean(np.abs(y - df['Synthetic'].values)):.4f}")

    # 6. Visualize
    plt.figure(figsize=(14, 6))
    plt.plot(df.index, df['Target'], label='Real Target Price', color='blue', linewidth=2)
    plt.plot(df.index, df['Synthetic'], label='Synthetic Basket Price', color='orange', linestyle='--', linewidth=2)
    plt.title(f'Synthetic Basket vs Target Market\n{target_question}', fontsize=12)
    plt.xlabel('Date', fontsize=10)
    plt.ylabel('Probability', fontsize=10)
    plt.legend(fontsize=10)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()
    
    # Return results
    return {
        'weights': weights,
        'r_squared': r_squared,
        'target_question': target_question,
        'input_markets': [info['question'] for info in input_info],
        'dataframe': df
    }

def main(target_market_id, input_market_ids, days=7):
    result = build_synthetic_basket(target_market_id, input_market_ids, days=days)