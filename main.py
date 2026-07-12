# main.py

import time
import requests
import logging
from config import GAS_WEBHOOK_URL, OANDA_INSTRUMENT
from oanda_client import fetch_candles, fetch_daily_candles
from engine import TradingViewEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def send_signal(signal):
    if not signal:
        return
    try:
        resp = requests.post(GAS_WEBHOOK_URL, json={"signal": signal}, timeout=10)
        logging.info(f"Signal sent: {resp.status_code} - {signal['dir']} {signal['pair']}")
    except Exception as e:
        logging.error(f"Failed to send signal: {e}")

def run():
    logging.info("🚀 Starting TradingView Python Engine (OANDA)")

    # Initial fetch
    df = fetch_candles(count=500)
    daily_df = fetch_daily_candles(count=300)

    engine = TradingViewEngine()

    # Process historical data
    engine.ingest_batch(df)
    logging.info(f"Processed {len(df)} historical bars.")

    # Live loop
    while True:
        try:
            # Fetch latest 2 bars to catch new data
            new_df = fetch_candles(count=2)
            if len(new_df) > 0:
                # Process only the most recent bar (if new)
                last_time = engine.times[-1] if engine.times else None
                for _, row in new_df.iterrows():
                    if last_time is None or row['time'] > last_time:
                        signal = engine.step(
                            row['open'], row['high'], row['low'], row['close'], row['time']
                        )
                        if signal:
                            logging.info(f"📈 SIGNAL: {signal['signal']} {signal['dir']} @ {signal['entry']}")
                            send_signal(signal)
                        last_time = row['time']

            # Sleep until next bar
            time.sleep(60)  # Check every minute

        except Exception as e:
            logging.error(f"Loop error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run()