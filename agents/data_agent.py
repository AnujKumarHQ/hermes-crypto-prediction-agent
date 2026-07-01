import requests
import pandas as pd
import logging
from typing import Optional
import config

logger = logging.getLogger(__name__)

def fetch_binance_klines(symbol: str, interval: str = "1m", limit: int = 1000) -> Optional[pd.DataFrame]:
    """
    Direct fallback that fetches historical OHLCV candles from Binance API.
    Very fast, free, and returns up to 1000 bars.
    """
    binance_symbol = f"{symbol}USDT"
    url = f"https://api.binance.com/api/v3/klines"
    params = {
        "symbol": binance_symbol,
        "interval": interval,
        "limit": limit
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # Parse Binance response into DataFrame
            df = pd.DataFrame(data, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_asset_volume", "number_of_trades",
                "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
            ])
            # Keep only the needed columns and cast to appropriate types
            df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms")
            df["open"] = df["open"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            df["close"] = df["close"].astype(float)
            df["volume"] = df["volume"].astype(float)
            
            # Select and reorder columns
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            return df
        else:
            logger.warning(f"Binance klines failed: {response.text}")
    except Exception as e:
        logger.warning(f"Binance klines error: {e}")
    return None

def fetch_historical_bars(symbol: str, interval: str = "1m", limit: int = 1000) -> pd.DataFrame:
    """
    Fetches the last N bars of OHLCV data for a crypto asset.
    Attempts to use Apify first (if token is available), and falls back to Binance API.
    """
    # 1. Attempt using Apify Yahoo Finance Scraper
    if config.APIFY_TOKEN:
        try:
            from apify_client import ApifyClient
            client = ApifyClient(config.APIFY_TOKEN)
            
            # Format ticker for Yahoo Finance (e.g. BTC-USD)
            y_ticker = f"{symbol}-USD"
            
            # Set up inputs for Yahoo Finance Scraper
            # Interval map: '1m', '5m', '1h', '1d'
            run_input = {
                "symbols": [y_ticker],
                "interval": interval,
                "range": "1d" if interval == "1m" else "5d", # Adjust range based on interval
            }
            
            logger.info(f"Triggering Apify Yahoo Finance Scraper for {y_ticker}...")
            # Run the actor and wait for it to finish
            run = client.actor("parseforge/yahoo-finance-scraper").call(run_input=run_input, timeout_secs=60)
            
            # Fetch results from dataset
            dataset_items = client.dataset(run["defaultDatasetId"]).list_items().items
            
            if dataset_items:
                # Parse items into a DataFrame
                df = pd.DataFrame(dataset_items)
                # Parse columns
                df["timestamp"] = pd.to_datetime(df["date"])
                df["open"] = df["open"].astype(float)
                df["high"] = df["high"].astype(float)
                df["low"] = df["low"].astype(float)
                df["close"] = df["close"].astype(float)
                df["volume"] = df["volume"].astype(float)
                
                df = df[["timestamp", "open", "high", "low", "close", "volume"]].sort_values("timestamp")
                df = df.tail(limit).reset_index(drop=True)
                
                logger.info(f"Successfully scraped {len(df)} bars from Apify for {symbol}")
                return df
                
        except Exception as e:
            logger.warning(f"Apify scraping failed: {e}. Falling back to Binance API.")
            
    # 2. Fallback to Binance public API
    logger.info(f"Fetching data from Binance API fallback for {symbol}...")
    df = fetch_binance_klines(symbol, interval, limit)
    if df is not None:
        logger.info(f"Successfully retrieved {len(df)} bars from Binance API for {symbol}")
        return df
        
    # 3. Create dummy/mock data if everything else fails
    logger.critical("All data sources failed. Creating emergency mock historical data.")
    import numpy as np
    import datetime
    
    dates = [datetime.datetime.now() - datetime.timedelta(minutes=i) for i in range(limit)]
    dates.reverse()
    
    # Generate random walk
    start_price = 95000.0 if symbol == "BTC" else 3200.0
    prices = start_price * np.exp(np.cumsum(np.random.normal(0, 0.0002, limit)))
    
    df = pd.DataFrame({
        "timestamp": dates,
        "open": prices * (1 - 0.0001),
        "high": prices * (1 + 0.0005),
        "low": prices * (1 - 0.0005),
        "close": prices,
        "volume": np.random.uniform(10, 100, limit)
    })
    return df

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = fetch_historical_bars("BTC", limit=5)
    print(df)
