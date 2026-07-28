# app.py

import threading
import time
import logging
from flask import Flask, jsonify
from engine import TradingViewEngine
from oanda_client import fetch_candles
from config import INSTRUMENTS
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ─── GLOBALS ──────────────────────────────────────────────────────────────────
engines = {}  # {instrument_name: engine_instance}
bot_running = False

# ─── SEND TO GOOGLE APPS SCRIPT ──────────────────────────────────────────────

def send_signal(signal, webhook_url):
    if not signal:
        return
    try:
        resp = requests.post(webhook_url, json={"signal": signal}, timeout=10)
        logger.info(f"✅ Signal sent: {resp.status_code} - {signal['dir']} {signal['pair']} @ {signal['entry']}")
    except Exception as e:
        logger.error(f"❌ Failed to send signal: {e}")

# ─── BOT MAIN LOOP ────────────────────────────────────────────────────────────

def run_bot_for_instrument(instrument_config):
    """Run a single instrument's trading engine."""
    instrument = instrument_config["name"]
    granularity = instrument_config.get("granularity", "H1")
    webhook = instrument_config["webhook"]
    
    logger.info(f"🚀 Starting engine for {instrument}")

    try:
        df = fetch_candles(instrument, granularity, count=500)
        engine = TradingViewEngine()
        engine.ingest_batch(df)
        logger.info(f"✅ {instrument}: Processed {len(df)} historical bars.")
        engines[instrument] = engine
    except Exception as e:
        logger.error(f"❌ {instrument}: Initialization failed: {e}")
        return

    while True:
        try:
            new_df = fetch_candles(instrument, granularity, count=2)
            if len(new_df) > 0 and engine:
                last_time = engine.times[-1] if engine.times else None
                for _, row in new_df.iterrows():
                    if last_time is None or row['time'] > last_time:
                        signal = engine.step(
                            row['open'], row['high'], row['low'], row['close'], row['time']
                        )
                        if signal:
                            logger.info(f"📈 {instrument}: SIGNAL - {signal['signal']} {signal['dir']} @ {signal['entry']}")
                            send_signal(signal, webhook)
                        last_time = row['time']

            time.sleep(60)  # Check every minute

        except Exception as e:
            logger.error(f"❌ {instrument}: Loop error: {e}")
            time.sleep(60)

# ─── START ALL INSTRUMENTS ────────────────────────────────────────────────────

def start_all_engines():
    """Start a separate thread for each instrument."""
    global bot_running
    bot_running = True
    
    for instrument_config in INSTRUMENTS:
        thread = threading.Thread(
            target=run_bot_for_instrument,
            args=(instrument_config,),
            daemon=True
        )
        thread.start()
        logger.info(f"✅ Started thread for {instrument_config['name']}")
        time.sleep(2)  # Stagger startup to avoid rate limits

# ─── FLASK ROUTES ──────────────────────────────────────────────────────────────

@app.route('/')
def health():
    """Health check endpoint."""
    status = "running" if bot_running else "initializing"
    instrument_status = {}
    for name, engine in engines.items():
        instrument_status[name] = {
            "bars": len(engine.closes) if engine else 0,
            "lr_valid": engine.lr_valid if engine else False,
        }
    return jsonify({
        "status": status,
        "instruments": instrument_status
    })

@app.route('/status')
def status():
    """Detailed status endpoint."""
    instrument_status = {}
    for name, engine in engines.items():
        if engine:
            instrument_status[name] = {
                "bars": len(engine.closes),
                "last_bar": str(engine.times[-1]) if engine.times else None,
                "lr_valid": engine.lr_valid,
                "ema200": engine.ema200,
                "atr": engine.atr_val,
                "in_consolidation": any(engine.cons_active) if engine.cons_active else False
            }
    return jsonify({
        "status": "running" if bot_running else "stopped",
        "instruments": instrument_status
    })

@app.route('/test_signal/<instrument>')
def test_signal(instrument):
    """Send a test signal to verify Telegram integration."""
    test_signal_data = {
        "signal": "Type 3 Trend (LR Channel Band)",
        "dir": "Long",
        "pair": instrument,
        "tf": "H1",
        "entry": "1.28450",
        "sl": "1.28200",
        "tp": "1.28825",
        "lr": "✅ Bullish",
        "ema": "✅",
        "cons": "➖",
        "div": "➖",
        "conv": "⏳",
        "choch": "➖",
        "time": str(int(time.time() * 1000))
    }
    
    # Find the webhook URL for this instrument
    webhook = None
    for inst in INSTRUMENTS:
        if inst["name"] == instrument:
            webhook = inst["webhook"]
            break
    
    if not webhook:
        return jsonify({"error": f"Instrument {instrument} not found"}), 404
    
    try:
        resp = requests.post(webhook, json={"signal": test_signal_data}, timeout=10)
        return jsonify({
            "status": "test signal sent",
            "instrument": instrument,
            "response_code": resp.status_code,
            "response_text": resp.text
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/test_oanda/<instrument>')
def test_oanda(instrument):
    """Test OANDA connection."""
    try:
        df = fetch_candles(instrument, "H1", count=10)
        return jsonify({
            "status": "connected",
            "instrument": instrument,
            "bars_fetched": len(df),
            "latest_close": float(df['close'].iloc[-1]) if len(df) > 0 else None,
            "latest_time": str(df['time'].iloc[-1]) if len(df) > 0 else None
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Start all instrument engines in background threads
    start_all_engines()
    
    # Keep Flask running
    app.run(host='0.0.0.0', port=8080)