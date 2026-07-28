# oanda_client.py

import requests
import pandas as pd
from config import OANDA_API_KEY

def fetch_candles(instrument, granularity="H1", count=1000):
    """Fetch latest candles from OANDA v20 API for any instrument."""
    url = f"https://api-fxpractice.oanda.com/v3/instruments/{instrument}/candles"
    params = {
        "granularity": granularity,
        "count": count,
        "price": "M"
    }
    headers = {
        "Authorization": f"Bearer {OANDA_API_KEY}",
        "Accept": "application/json"
    }
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