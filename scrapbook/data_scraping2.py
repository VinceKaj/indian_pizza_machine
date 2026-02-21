import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from py_clob_client.client import ClobClient

# 1. SETUP & DATA INGESTION
def fetch_polymarket_history(token_id, start_ts, end_ts):
    """
    Fetches historical price data from Polymarket CLOB.
    """
    client = ClobClient("https://clob.polymarket.com")
    
    # Prices-history returns a list of { "t": timestamp, "p": price }
    history = client.get_prices_history(
        market=token_id, 
        startTs=int(start_ts), 
        endTs=int(end_ts),
        fidelity=1 # 1-minute resolution
    )
    
    df = pd.DataFrame(history)
    df['timestamp'] = pd.to_datetime(df['t'], unit='s', utc=True)
    df = df.rename(columns={'p': 'price'}).drop(columns=['t'])
    return df.set_index('timestamp')

def load_tweet_data(file_path):
    """
    Assuming you have Musk's tweets in a CSV with 'created_at'.
    """
    tweets = pd.read_csv(file_path)
    tweets['timestamp'] = pd.to_datetime(tweets['created_at'], utc=True)
    # We create a 'tweet_count' column where each tweet = 1
    tweets['tweet_count'] = 1
    return tweets.set_index('timestamp')[['tweet_count']]

# 2. THE ALIGNMENT ENGINE
def align_and_clean(price_df, tweet_df, freq='5T'):
    """
    Synchronizes both datasets into a single timeframe.
    """
    # Create a master timeline based on the price data range
    start, end = price_df.index.min(), price_df.index.max()
    master_index = pd.date_range(start=start, end=end, freq=freq, tz='UTC')
    
    # Resample Prices: Use 'mean' to get the average price in that window
    price_resampled = price_df['price'].resample(freq).mean().reindex(master_index)
    
    # Resample Tweets: Use 'sum' to count how many tweets occurred in that window
    tweet_resampled = tweet_df['tweet_count'].resample(freq).sum().reindex(master_index).fillna(0)
    
    # Merge
    combined = pd.concat([price_resampled, tweet_resampled], axis=1)
    
    # Forward-fill prices (if no trades happened in a 5m window, price stays same)
    combined['price'] = combined['price'].ffill()
    
    return combined.dropna()

# 3. FEATURE ENGINEERING (For Causality)
def prepare_for_stats(df):
    # Calculate Log Returns (essential for stationarity)
    df['returns'] = np.log(df['price'] / df['price'].shift(1))
    
    # Create a binary 'tweet_hit' (did he tweet at all in this window?)
    df['is_tweet'] = (df['tweet_count'] > 0).astype(int)
    
    return df.dropna()

# --- EXECUTION EXAMPLE ---
# start_date = int(datetime(2026, 1, 1).timestamp())
# end_date = int(datetime.now().timestamp())
# TOKEN_ID = "..." # You get this from the Gamma API

# price_data = fetch_polymarket_history(TOKEN_ID, start_date, end_date)
# tweet_data = load_tweet_data("musk_tweets_2026.csv")

# final_df = align_and_clean(price_data, tweet_data, freq='5T')
# final_df = prepare_for_stats(final_df)

# print(final_df.head())