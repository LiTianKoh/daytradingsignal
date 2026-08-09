# oanda_client.py

import requests
import pandas as pd
from config import OANDA_API_KEY, OANDA_API_URL, OANDA_DXY_INSTRUMENT

def fetch_candles(instrument, granularity="H1", count=1000):
    url = f"{OANDA_API_URL}/v3/instruments/{instrument}/candles"
    params = {"granularity": granularity, "count": count, "price": "M"}
    headers = {"Authorization": f"Bearer {OANDA_API_KEY}", "Accept": "application/json"}
    resp = requests.get(url, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    candles = []
    for c in data['candles']:
        candles.append({
            "time": pd.to_datetime(c['time']),
            "open": float(c['mid']['o']),
            "high": float(c['mid']['h']),
            "low": float(c['mid']['l']),
            "close": float(c['mid']['c'])
        })
    return pd.DataFrame(candles)

def fetch_dxy_candles(granularity="H1", count=500, retries=3):
    import yfinance as yf
    import time
    
    interval_map = {"H1": "60m", "H4": "1h", "D": "1d"}
    interval = interval_map.get(granularity, "60m")
    
    for attempt in range(retries):
        try:
            ticker = yf.Ticker("DX-Y.NYB")
            df = ticker.history(period=f"{max(count // 24 + 7, 7)}d", interval=interval)
            if df.empty:
                raise ValueError("No DXY data")
            df = df.reset_index()
            df['time'] = pd.to_datetime(df['Datetime'])
            df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'}, inplace=True)
            return df[['time', 'open', 'high', 'low', 'close']].tail(count)
        except Exception as e:
            if "Rate limited" in str(e) and attempt < retries - 1:
                wait = (attempt + 1) * 10  # 10, 20, 30 seconds
                time.sleep(wait)
                continue
            else:
                raise