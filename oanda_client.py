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

def fetch_dxy_candles(granularity="H1", count=500):
    """
    Fetch DXY from Yahoo Finance (replaces OANDA USD_INDEX).
    """
    import yfinance as yf
    import pandas as pd
    
    interval_map = {
        "H1": "60m",
        "H4": "1h",   # Yahoo doesn't have 4h
        "D": "1d"
    }
    interval = interval_map.get(granularity, "60m")
    
    ticker = yf.Ticker("DX-Y.NYB")
    df = ticker.history(period=f"{max(count // 24 + 7, 7)}d", interval=interval)
    
    if df.empty:
        raise ValueError("No DXY data from Yahoo Finance")
    
    df = df.reset_index()
    df['time'] = pd.to_datetime(df['Datetime'])
    df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'}, inplace=True)
    
    return df[['time', 'open', 'high', 'low', 'close']].tail(count)