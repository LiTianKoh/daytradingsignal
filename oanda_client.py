# oanda_client.py

import requests
import pandas as pd
from config import OANDA_API_KEY, OANDA_ACCOUNT_ID, OANDA_INSTRUMENT, OANDA_GRANULARITY

def fetch_candles(instrument=OANDA_INSTRUMENT, granularity=OANDA_GRANULARITY, count=1000):
    """Fetch latest candles from OANDA v20 API."""
    url = f"https://api-fxtrade.oanda.com/v3/instruments/{instrument}/candles"
    params = {
        "granularity": granularity,
        "count": count,
        "price": "M"  # Midpoint prices
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

def fetch_daily_candles(instrument=OANDA_INSTRUMENT, count=400):
    """Fetch daily candles for Daily S/R (equivalent of request.security(..., "D", ...))."""
    return fetch_candles(instrument, "D", count)