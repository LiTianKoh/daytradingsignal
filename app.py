# app.py

import threading
import time
import logging
from flask import Flask, jsonify, request  # ✅ Added 'request'
from engine import TradingViewEngine
from oanda_client import fetch_candles
from config import INSTRUMENTS
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ─── GLOBALS ──────────────────────────────────────────────────────────────────
engines = {}  # {instrument_name: engine_instance}
bot_running = False
pending_signals = {}  # ✅ Moved here after imports

# ─── TELEGRAM FUNCTIONS ──────────────────────────────────────────────────────

def send_telegram_signal(signal_data):
    """Send a signal directly to Telegram with Yes/No buttons."""
    signal_id = f"{signal_data['pair']}_{int(time.time()*1000)}"
    pending_signals[signal_id] = signal_data

    token = "8148974966:AAFqW1LmHySlvH_5v79itFA2NrFowEqnQpY"
    chat_id = "5572387258"
    message = format_signal_message(signal_data)
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Yes, taken", "callback_data": f"taken_{signal_id}"},
            {"text": "❌ No, skipped", "callback_data": f"skipped_{signal_id}"}
        ]]
    }
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "reply_markup": keyboard}
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        logger.info(f"✅ Telegram sent: {resp.status_code} - {signal_data['pair']} {signal_data['dir']}")
    except Exception as e:
        logger.error(f"❌ Failed to send Telegram: {e}")

def format_signal_message(data):
    """Format the signal message for Telegram."""
    dirEmoji = "📈" if data.get("dir") == "Long" else "📉"
    timeStr = data.get("time", str(int(time.time() * 1000)))
    
    entry = float(data.get("entry", 0))
    sl = float(data.get("sl", 0))
    tp = float(data.get("tp", 0))
    risk = abs(entry - sl)
    reward = abs(tp - entry)

    return (
        f"🚨 <b>SIGNAL ALERT</b>\n\n"
        f"{dirEmoji} <b>{data.get('pair', '—')} — {data.get('signal', '—')} {data.get('dir', '').upper()}</b>\n"
        f"🕐 {data.get('tf', 'H1')} chart\n\n"
        f"<code>"
        f"Entry:  {data.get('entry', '—')}\n"
        f"Stop:   {data.get('sl', '—')}  (−{risk:.5f})\n"
        f"Target: {data.get('tp', '—')}  (+{reward:.5f} · 1.5R)"
        f"</code>\n\n"
        f"─────── <b>CONDITIONS</b> ───────\n"
        f"LR Channel     {data.get('lr', '—')}\n"
        f"200 EMA        {data.get('ema', '—')}\n"
        f"Consolidation  {data.get('cons', '—')}\n"
        f"Divergence     {data.get('div', '—')}\n"
        f"Convergence    {data.get('conv', '—')}\n"
        f"CHoCH          {data.get('choch', '—')}\n"
        f"────────────────────────\n\n"
        f"<b>Did you take this trade?</b>"
    )

def answer_callback(callback_id, text):
    """Answer a Telegram callback query."""
    token = "8148974966:AAFqW1LmHySlvH_5v79itFA2NrFowEqnQpY"
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id, "text": text, "show_alert": False}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Failed to answer callback: {e}")

def edit_telegram_message(original_msg, signal_data, response):
    """Edit the original message to show the response."""
    token = "8148974966:AAFqW1LmHySlvH_5v79itFA2NrFowEqnQpY"
    chat_id = original_msg['chat']['id']
    msg_id = original_msg['message_id']
    
    status = "✅ TAKEN — Logged!" if response == "taken" else "❌ SKIPPED — Logged for review."
    message = format_signal_message(signal_data) + f"\n\n{status}"
    
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": msg_id, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Failed to edit message: {e}")

# ─── GOOGLE SHEETS LOGGING ──────────────────────────────────────────────────

def log_to_google_sheet(data):
    """Log a trade to Google Sheets (only called when 'taken' is clicked)."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        client = gspread.authorize(creds)
        
        # ✅ Replace with YOUR actual Sheet ID
        sheet_id = "1pfThksgRPNK2ZmDbS9QcG8YEMEZAqhBcJOcoljLhul0"
        sheet = client.open_by_key(sheet_id).worksheet("Trade Log")
        
        # Format the row to match your columns
        row = [
            f"🤖 Bot — {time.strftime('%Y-%m-%d %H:%M:%S')}",  # A: Timestamp
            "",  # B: Date (leave empty, will be filled manually)
            "",  # C: Time
            data.get('pair', ''),  # D: Pair
            f"{data.get('dir', '')} 📈" if data.get('dir') == 'Long' else f"{data.get('dir', '')} 📉",  # E: Direction
            data.get('signal', ''),  # F: Signal Type
            "",  # G: DXY Bias
            "",  # H: DXY Aligned
            data.get('lr', ''),  # I: LR Channel
            data.get('ema', ''),  # J: EMA
            "",  # K: OTE Zone
            "",  # L: S/R Zone
            data.get('cons', ''),  # M: Consolidation
            data.get('entry', ''),  # N: Entry
            data.get('sl', ''),  # O: SL
            data.get('tp', ''),  # P: TP
            "",  # Q: Outcome
            "",  # R: Exit
            "",  # S: Notes
            "",  # T: RR (auto-calculated)
            ""   # U: Win (auto-calculated)
        ]
        
        sheet.append_row(row)
        logger.info(f"✅ Logged to Google Sheets: {data['pair']} {data['dir']}")
        
    except Exception as e:
        logger.error(f"❌ Failed to log to Google Sheets: {e}")

# ─── SEND SIGNAL (UPDATED) ──────────────────────────────────────────────────

def send_signal(signal, webhook_url=None):
    """Send signal - now uses Telegram directly."""
    if not signal:
        return
    send_telegram_signal(signal)

# ─── BOT MAIN LOOP ────────────────────────────────────────────────────────────

def run_bot_for_instrument(instrument_config):
    """Run a single instrument's trading engine."""
    global bot_running
    
    instrument = instrument_config["name"]
    granularity = instrument_config.get("granularity", "H1")
    
    logger.info(f"🚀 Starting engine for {instrument}")

    try:
        df = fetch_candles(instrument, granularity, count=500)
        engine = TradingViewEngine()
        engine.ingest_batch(df)
        logger.info(f"✅ {instrument}: Processed {len(df)} historical bars.")
        engines[instrument] = engine
        bot_running = True
    except Exception as e:
        logger.error(f"❌ {instrument}: Initialization failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        bot_running = False
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
                            send_signal(signal)
                        last_time = row['time']

            time.sleep(60)  # Check every minute

        except Exception as e:
            logger.error(f"❌ {instrument}: Loop error: {e}")
            time.sleep(60)

# ─── START ALL ENGINES ──────────────────────────────────────────────────────

def start_all_engines():
    """Start a separate thread for each instrument."""
    global bot_running
    
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
    """Send a test signal directly to Telegram (bypasses webhook)."""
    logging.info(f"🔍 Test signal requested for {instrument}")
    
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
    
    try:
        send_telegram_signal(test_signal_data)
        return jsonify({
            "status": "test signal sent",
            "instrument": instrument
        })
    except Exception as e:
        logging.error(f"❌ Test signal failed: {e}")
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

@app.route('/ping_telegram')
def ping_telegram():
    """Send a simple ping message to Telegram."""
    try:
        token = "8148974966:AAFqW1LmHySlvH_5v79itFA2NrFowEqnQpY"
        chat_id = "5572387258"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": "🟢 Bot is alive and connected!",
            "parse_mode": "HTML"
        }
        resp = requests.post(url, json=payload, timeout=10)
        return jsonify({
            "status": "message sent",
            "telegram_response": resp.status_code
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/start_engine')
def start_engine():
    """Manually start the trading engine."""
    global bot_running
    if bot_running:
        return jsonify({"status": "already running"})
    thread = threading.Thread(target=run_bot_for_instrument, args=(INSTRUMENTS[0],), daemon=True)
    thread.start()
    return jsonify({"status": "engine starting"})

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    """Handle Telegram callback queries (Yes/No taps)."""
    try:
        data = request.get_json()
        logger.info(f"📥 Webhook received: {data}")
        
        if 'callback_query' in data:
            callback = data['callback_query']
            callback_id = callback['id']
            raw = callback['data']
            parts = raw.split('_', 1)
            response = parts[0]
            signal_id = parts[1] if len(parts) > 1 else None

            if not signal_id:
                answer_callback(callback_id, "⚠️ Invalid signal.")
                return "OK", 200

            signal_data = pending_signals.pop(signal_id, None)
            if not signal_data:
                answer_callback(callback_id, "⚠️ Signal expired.")
                return "OK", 200

            if response == "taken":
                log_to_google_sheet(signal_data)
                answer_callback(callback_id, "✅ Logged!")
            else:
                answer_callback(callback_id, "📝 Skipped.")

            edit_telegram_message(callback['message'], signal_data, response)

        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "OK", 200

# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    start_all_engines()
    app.run(host='0.0.0.0', port=8080)