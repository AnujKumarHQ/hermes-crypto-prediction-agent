import requests
import json

def test_polymarket():
    print("Testing Polymarket...")
    # Gamma API public search endpoint
    url = "https://gamma-api.polymarket.com/public-search?q=BTC"
    try:
        response = requests.get(url, timeout=10)
        print(f"Polymarket response status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Polymarket returned {len(data)} items")
            # print the first 2 items
            for i, item in enumerate(data[:2]):
                print(f"Item {i+1}: {json.dumps(item, indent=2)[:500]}...")
        else:
            print(response.text)
    except Exception as e:
        print(f"Polymarket error: {e}")

def test_kalshi():
    print("\nTesting Kalshi...")
    # Kalshi V2 public markets endpoint
    url = "https://external-api.kalshi.com/trade-api/v2/markets?search=BTC&status=open"
    try:
        response = requests.get(url, timeout=10)
        print(f"Kalshi response status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            markets = data.get("markets", [])
            print(f"Kalshi returned {len(markets)} markets")
            for i, m in enumerate(markets[:2]):
                print(f"Market {i+1}: {json.dumps(m, indent=2)[:500]}...")
        else:
            print(response.text)
    except Exception as e:
        print(f"Kalshi error: {e}")

if __name__ == "__main__":
    test_polymarket()
    test_kalshi()
