# app.py

import threading
import time
import logging
from flask import Flask, jsonify
from engine import TradingViewEngine
from oanda_client import fetch_candles
from config import GAS_WEBHOOK_URL, OANDA_INSTRUMENT
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ─── GLOBALS ──────────────────────────────────────────────────────────────────
engine = None
bot_running = False

# ─── SEND TO GOOGLE APPS SCRIPT ──────────────────────────────────────────────

def send_signal(signal):
    if not signal:
        return
    try:
        resp = requests.post(GAS_WEBHOOK_URL, json={"signal": signal}, timeout=10)
        logger.info(f"✅ Signal sent: {resp.status_code} - {signal['dir']} {signal['pair']} @ {signal['entry']}")
    except Exception as e:
        logger.error(f"❌ Failed to send signal: {e}")

# ─── BOT MAIN LOOP ────────────────────────────────────────────────────────────

def run_bot():
    global engine, bot_running
    logger.info("🚀 Starting TradingView Python Engine (OANDA)")

    # Initial fetch
    try:
        df = fetch_candles(count=500)
        engine = TradingViewEngine()
        engine.ingest_batch(df)
        logger.info(f"✅ Processed {len(df)} historical bars.")
        bot_running = True
    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}")
        bot_running = False
        return

    # ── LIVE LOOP ──────────────────────────────────────────────────────────
    while True:
        try:
            if not bot_running:
                logger.warning("⚠️ Bot paused, waiting for restart...")
                time.sleep(60)
                continue

            # Fetch latest 2 bars (catch any new data)
            new_df = fetch_candles(count=2)
            if len(new_df) > 0 and engine:
                last_time = engine.times[-1] if engine.times else None
                for _, row in new_df.iterrows():
                    if last_time is None or row['time'] > last_time:
                        signal = engine.step(
                            row['open'], row['high'], row['low'], row['close'], row['time']
                        )
                        if signal:
                            logger.info(f"📈 SIGNAL: {signal['signal']} {signal['dir']} @ {signal['entry']}")
                            send_signal(signal)
                        last_time = row['time']

            # Sleep 60 seconds before next check
            time.sleep(60)

        except Exception as e:
            logger.error(f"❌ Loop error: {e}")
            time.sleep(60)

# ─── FLASK ROUTES ──────────────────────────────────────────────────────────────

@app.route('/')
def health():
    """Health check endpoint — keeps Render alive."""
    status = "running" if bot_running else "initializing"
    return jsonify({
        "status": status,
        "bars": len(engine.closes) if engine else 0,
        "last_bar": str(engine.times[-1]) if engine and engine.times else None
    })

@app.route('/status')
def status():
    """Detailed status endpoint."""
    if not engine:
        return jsonify({"status": "not_initialized"})
    return jsonify({
        "status": "running",
        "bars": len(engine.closes),
        "last_bar": str(engine.times[-1]) if engine.times else None,
        "lr_valid": engine.lr_valid,
        "ema200": engine.ema200,
        "atr": engine.atr_val,
        "in_consolidation": any(engine.cons_active) if engine.cons_active else False
    })

@app.route('/start')
def start_bot():
    """Manually restart the bot (useful for debugging)."""
    global bot_running, engine
    bot_running = False
    time.sleep(2)
    threading.Thread(target=run_bot, daemon=True).start()
    return jsonify({"status": "restarted"})

# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # Keep Flask running
    app.run(host='0.0.0.0', port=8080)