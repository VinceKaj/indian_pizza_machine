"""
Test script for the basket API endpoint.
Calls the endpoint and visualizes the results.
"""
import requests
import matplotlib.pyplot as plt
from datetime import datetime

# API configuration
API_URL = "http://localhost:8000/api/basket"

# Market IDs
TARGET_MARKET_ID = "1375498"
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
    "1183478",
    "916717",
    "836162"
]

def test_basket_endpoint():
    """Call the basket API and visualize results."""
    
    print("=" * 80)
    print("TESTING BASKET API")
    print("=" * 80)
    print(f"\nTarget Market ID: {TARGET_MARKET_ID}")
    print(f"Number of Input Markets: {len(INPUT_MARKET_IDS)}")
    print(f"\nCalling API at {API_URL}...")
    
    # Make API request
    payload = {
        "target_market_id": TARGET_MARKET_ID,
        "input_market_ids": INPUT_MARKET_IDS,
        "days": 7
    }
    
    try:
        response = requests.post(API_URL, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.RequestException as e:
        print(f"\n❌ ERROR: API request failed: {e}")
        return
    
    print("✅ API call successful!\n")
    
    # Extract data
    target_prices = result['target_prices']
    synthetic_prices = result['synthetic_prices']
    weights = result['weights']
    r_squared = result['r_squared']
    timestamps = [datetime.fromisoformat(ts) for ts in result['timestamps']]
    target_question = result['target_question']
    
    # Print weights in descending order by absolute magnitude
    print("=" * 80)
    print("BASKET WEIGHTS (sorted by magnitude)")
    print("=" * 80)
    
    # Sort weights by absolute value
    sorted_weights = sorted(weights, key=lambda w: abs(w['weight']), reverse=True)
    
    for w in sorted_weights:
        weight_val = w['weight']
        title = w['title']
        market_id = w['market_id']
        print(f"{weight_val:+.6f}  | {title}")
    
    print("\n" + "=" * 80)
    print(f"R² Score: {r_squared:.6f}")
    print(f"Target Market: {target_question}")
    print(f"Data Points: {len(target_prices)}")
    print("=" * 80)
    
    # Plot results
    plt.figure(figsize=(14, 8))
    
    # Main plot: Target vs Synthetic
    plt.subplot(2, 1, 1)
    plt.plot(timestamps, target_prices, label='Target Price', color='blue', linewidth=2, marker='o', markersize=3)
    plt.plot(timestamps, synthetic_prices, label='Synthetic Basket', color='orange', linewidth=2, linestyle='--', marker='x', markersize=3)
    plt.title(f'Synthetic Basket vs Target Market (R² = {r_squared:.4f})\n{target_question}', fontsize=12, fontweight='bold')
    plt.xlabel('Date', fontsize=10)
    plt.ylabel('Probability', fontsize=10)
    plt.legend(fontsize=10, loc='best')
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    
    # Residuals plot
    plt.subplot(2, 1, 2)
    residuals = [t - s for t, s in zip(target_prices, synthetic_prices)]
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

if __name__ == "__main__":
    test_basket_endpoint()
