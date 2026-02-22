"""
Test script for the basket-no-target API endpoint.
Creates a basket using semantic similarity and softmax weighting without a target market.
Optionally compares against a hidden target market for validation.
"""
import requests
import json
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# API configuration
API_URL = "http://localhost:8000/api/basket-no-target"

# Optional: Hidden target market ID for validation (set to None to disable)
TARGET_MARKET_ID = "1375498"  # Set to None if no target

# Input Market IDs (various Elon/Tesla/SpaceX markets)
INPUT_MARKET_IDS = [
    "573830",   # Grok 5 released by March 31, 2026?
    "638650",   # Will the chopsticks catch SpaceX Starship Flight Test 12 Superheavy booster?
    "665354",   # Will Elon register any party before 2027?
    "665482",   # Will Elon Musk announce Presidential run before 2027?
    "676802",   # Musk out as Tesla CEO before 2027?
    "676812",   # SpaceX Starship fully reusable before 2027?
    "676817",   # Will Tesla launch robotaxis in California by June 30?
    "676900",   # Will Elon Musk be richest person on March 31?
    "676937",   # Will Elon Musk be richest person on December 31?
    "821114",
    "682706",
    "898685",
    "1296852",
    "1262834",
    "1285768",
    "1183478"
]


def get_clob_token_ids(market_id):
    """Fetch CLOB token IDs from a Polymarket market ID."""
    url = f"https://gamma-api.polymarket.com/markets/{market_id}"
    response = requests.get(url)
    
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch market {market_id}: {response.status_code}")
    
    data = response.json()
    clob_ids = data.get('clobTokenIds', [])
    
    if isinstance(clob_ids, str):
        import json
        clob_ids = json.loads(clob_ids)
    
    if len(clob_ids) < 2:
        raise ValueError(f"Market {market_id} doesn't have CLOB token IDs")
    
    return clob_ids[0], clob_ids[1], data.get('question', 'Unknown'), data.get('description', '')


def fetch_historical_prices(clob_token_id, start_ts, end_ts):
    """Fetch historical prices from Polymarket using CLOB token ID."""
    url = "https://clob.polymarket.com/prices-history"
    params = {
        "market": clob_token_id,
        "startTs": int(start_ts),
        "endTs": int(end_ts),
        "fidelity": 60
    }
    
    response = requests.get(url, params=params)
    data = response.json().get('history', [])
    
    if not data:
        return pd.Series(dtype=float)
    
    df = pd.DataFrame(data)
    df['datetime'] = pd.to_datetime(df['t'], unit='s')
    df.set_index('datetime', inplace=True)
    return df['p'].astype(float)

def test_basket_no_target():
    """Call the basket-no-target API and display results."""
    
    print("=" * 80)
    print("TESTING BASKET-NO-TARGET API")
    print("=" * 80)
    print(f"\nNumber of Input Markets: {len(INPUT_MARKET_IDS)}")
    if TARGET_MARKET_ID:
        print(f"Hidden Target Market: {TARGET_MARKET_ID} (for validation)")
    print(f"\nCalling API at {API_URL}...")
    
    # Make API request
    payload = {
        "input_market_ids": INPUT_MARKET_IDS,
        "top_k": 10,
        "temperature": 0.05,
        "use_diversity_filter": True,
        "max_pairwise_similarity": 0.85
    }
    
    try:
        response = requests.post(API_URL, json=payload, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        
        print("\n" + "=" * 80)
        print("RESULTS")
        print("=" * 80)
        
        print(f"\nTotal Markets in Basket: {result['total_markets']}")
        print(f"Temperature: {result['temperature']}")
        print(f"\nCentroid Question (Most Representative):")
        print(f"  {result['centroid_question']}")
        
        print("\n" + "-" * 80)
        print("SOFTMAX WEIGHTS (sorted by weight)")
        print("-" * 80)
        
        # Sort weights by magnitude
        weights = sorted(result['weights'], key=lambda x: abs(x['weight']), reverse=True)
        
        for i, w in enumerate(weights, 1):
            weight = w['weight']
            similarity = w['similarity']
            title = w['title']
            market_id = w['market_id']
            
            print(f"\n{i}. Market ID: {market_id}")
            print(f"   Weight: {weight:+.6f} ({weight*100:.2f}%)")
            print(f"   Similarity to centroid: {similarity:.4f}")
            print(f"   Question: {title}")
        
        # Verify weights sum to 1
        total_weight = sum(w['weight'] for w in result['weights'])
        print("\n" + "-" * 80)
        print(f"Total Weight (should be ~1.0): {total_weight:.6f}")
        print("=" * 80)
        
        # If target market is provided, fetch price data and visualize
        if TARGET_MARKET_ID:
            print("\n📊 Fetching price data for comparison with target market...")
            
            # Time window (7 days)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            start_ts = start_date.timestamp()
            end_ts = end_date.timestamp()
            
            # Fetch target market prices
            try:
                target_clob, _, target_question, _ = get_clob_token_ids(TARGET_MARKET_ID)
                target_series = fetch_historical_prices(target_clob, start_ts, end_ts)
                target_series.name = 'Target'
                
                # Fetch prices for markets in the basket
                input_series_list = []
                basket_market_ids = [w['market_id'] for w in result['weights']]
                basket_weights = {w['market_id']: w['weight'] for w in result['weights']}
                
                for market_id in basket_market_ids:
                    clob_id, _, question, _ = get_clob_token_ids(market_id)
                    series = fetch_historical_prices(clob_id, start_ts, end_ts)
                    series.name = question
                    input_series_list.append(series)
                
                # Resample and align
                target_resampled = target_series.resample('1h').last().ffill()
                input_resampled_list = []
                for series in input_series_list:
                    resampled = series.resample('1h').last().ffill()
                    resampled.name = series.name
                    input_resampled_list.append(resampled)
                
                # Concat on same time grid
                df = pd.concat([target_resampled] + input_resampled_list, axis=1, sort=True)
                df = df.ffill()
                df = df.dropna()
                
                if df.empty:
                    print("⚠️  No overlapping price data found")
                else:
                    # Calculate synthetic price using basket weights
                    y = df['Target'].values
                    X_cols = [col for col in df.columns if col != 'Target']
                    X = df[X_cols].values
                    
                    # Apply weights in the order of basket_market_ids
                    weights_array = np.array([basket_weights[mid] for mid in basket_market_ids])
                    synthetic = X @ weights_array
                    
                    # Calculate R-squared
                    ss_res = np.sum((y - synthetic)**2)
                    ss_tot = np.sum((y - y.mean())**2)
                    r_squared = 1 - (ss_res / ss_tot)
                    
                    print(f"\n✅ Price data aligned: {len(df)} hourly observations")
                    print(f"R² Score vs Target: {r_squared:.6f}")
                    
                    # Create visualization
                    timestamps = df.index
                    target_prices = y
                    synthetic_prices = synthetic
                    
                    plt.figure(figsize=(14, 8))
                    
                    # Main plot: Target vs Synthetic
                    plt.subplot(2, 1, 1)
                    plt.plot(timestamps, target_prices, label='Target Price (Hidden)', color='blue', linewidth=2, marker='o', markersize=3)
                    plt.plot(timestamps, synthetic_prices, label='Synthetic Basket (No-Target Method)', color='orange', linewidth=2, linestyle='--', marker='x', markersize=3)
                    plt.title(f'Softmax Basket vs Target Market (R² = {r_squared:.4f})\nTarget: {target_question}', fontsize=12, fontweight='bold')
                    plt.xlabel('Date', fontsize=10)
                    plt.ylabel('Probability', fontsize=10)
                    plt.legend(fontsize=10, loc='best')
                    plt.grid(True, alpha=0.3)
                    plt.xticks(rotation=45)
                    
                    # Residuals plot
                    plt.subplot(2, 1, 2)
                    residuals = target_prices - synthetic_prices
                    plt.plot(timestamps, residuals, label='Residuals (Target - Synthetic)', color='red', linewidth=1.5, marker='o', markersize=2)
                    plt.axhline(y=0, color='black', linestyle='--', linewidth=1, alpha=0.5)
                    plt.title('Residuals Over Time', fontsize=11)
                    plt.xlabel('Date', fontsize=10)
                    plt.ylabel('Residual', fontsize=10)
                    plt.legend(fontsize=10)
                    plt.grid(True, alpha=0.3)
                    plt.xticks(rotation=45)
                    
                    plt.tight_layout()
                    plt.show()
                    
                    print("\n✅ Visualization complete!")
                    
            except Exception as e:
                print(f"⚠️  Could not fetch price data: {e}")
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Error calling API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    test_basket_no_target()
