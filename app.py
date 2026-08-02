# app.py - Full Version with Risk/Exit Flow

import threading
import time
import logging
import os
import json
import base64
from flask import Flask, jsonify, request
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
engines = {}
pending_trades = {}
user_states = {}  # {chat_id: {"state": "awaiting_risk"|"awaiting_exit"|None, "signal_id": ...}}
bot_running = False
BOT_TOKEN = "8148974966:AAFqW1LmHySlvH_5v79itFA2NrFowEqnQpY"
CHAT_ID = "5572387258"
SHEET_ID = "1pfThksgRPNK2ZmDbS9QcG8YEMEZAqhBcJOcoljLhul0"

# ─── GOOGLE SHEETS AUTH ─────────────────────────────────────────────────────

def get_gspread_client():
    creds_base64 = os.environ.get('GOOGLE_CREDENTIALS')
    if not creds_base64:
        logger.error("❌ GOOGLE_CREDENTIALS not set")
        return None
    try:
        creds_json = base64.b64decode(creds_base64).decode('utf-8')
        creds_dict = json.loads(creds_json)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        logger.error(f"❌ Google Sheets auth error: {e}")
        return None

# ─── TELEGRAM HELPERS ──────────────────────────────────────────────────────

def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.json()
    except Exception as e:
        logger.error(f"Send message error: {e}")
        return None

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.json()
    except Exception as e:
        logger.error(f"Edit message error: {e}")
        return None

def answer_callback(callback_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id, "text": text, "show_alert": False}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Answer callback error: {e}")

# ─── SIGNAL MESSAGE FORMATTER ─────────────────────────────────────────────

def format_signal_message(data, status=None, risk=None, exit_price=None, r_multiple=None):
    dirEmoji = "📈" if data.get("dir") == "Long" else "📉"
    base = (
        f"🚨 <b>SIGNAL ALERT</b>\n\n"
        f"{dirEmoji} <b>{data.get('pair', '—')} — {data.get('signal', '—')} {data.get('dir', '').upper()}</b>\n"
        f"🕐 {data.get('tf', 'H1')} chart\n\n"
        f"<code>Entry:  {data.get('entry', '—')}\n"
        f"Stop:   {data.get('sl', '—')}</code>\n\n"
        f"─────── <b>CONDITIONS</b> ───────\n"
        f"LR Channel     {data.get('lr', '—')}\n"
        f"200 EMA        {data.get('ema', '—')}\n"
        f"Consolidation  {data.get('cons', '—')}\n"
        f"Divergence     {data.get('div', '—')}\n"
        f"Convergence    {data.get('conv', '—')}\n"
        f"CHoCH          {data.get('choch', '—')}\n"
        f"────────────────────────\n"
    )
    if status == "holding":
        return base + f"\n📌 <b>HOLDING</b> | Risk: ${risk:.2f}\n\nTap <b>Exit</b> to close the trade."
    elif status == "exited":
        return base + f"\n✅ <b>EXITED</b> | Exit: {exit_price} | R: {r_multiple:.2f}"
    else:
        return base + "\n<b>Did you take this trade?</b>"

# ─── SEND SIGNAL ───────────────────────────────────────────────────────────

def send_telegram_signal(signal_data):
    signal_id = f"{signal_data['pair']}_{int(time.time()*1000)}"
    pending_trades[signal_id] = {
        "signal": signal_data,
        "status": "pending",
        "risk": None,
        "exit_price": None,
        "r_multiple": None,
        "entry": signal_data['entry'],
        "sl": signal_data['sl'],
        "dir": signal_data['dir'],
        "pair": signal_data['pair'],
        "timestamp": time.time()
    }
    message = format_signal_message(signal_data)
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Yes, taken", "callback_data": f"taken_{signal_id}"},
                {"text": "❌ No, skipped", "callback_data": f"skipped_{signal_id}"}
            ]
        ]
    }
    resp = send_message(CHAT_ID, message, keyboard)
    if resp and resp.get('ok'):
        pending_trades[signal_id]['message_id'] = resp['result']['message_id']
        pending_trades[signal_id]['chat_id'] = CHAT_ID
    else:
        logger.error(f"Failed to send signal: {resp}")

# ─── HANDLE CALLBACKS ─────────────────────────────────────────────────────

def handle_taken(callback_id, signal_id):
    trade = pending_trades.get(signal_id)
    if not trade:
        answer_callback(callback_id, "⚠️ Signal expired.")
        return
    if trade['status'] != 'pending':
        answer_callback(callback_id, "⚠️ Already processed.")
        return

    trade['status'] = 'awaiting_risk'
    user_states[CHAT_ID] = {"state": "awaiting_risk", "signal_id": signal_id}

    edit_message(
        chat_id=CHAT_ID,
        message_id=trade['message_id'],
        text=format_signal_message(trade['signal']) + "\n\n💰 How much USD are you risking on this trade? (e.g., 100)",
        reply_markup=None
    )
    answer_callback(callback_id, "Please enter your risk amount.")

def handle_skipped(callback_id, signal_id):
    trade = pending_trades.get(signal_id)
    if trade:
        trade['status'] = 'exited'
        edit_message(
            chat_id=CHAT_ID,
            message_id=trade['message_id'],
            text=format_signal_message(trade['signal']) + "\n\n❌ <b>SKIPPED</b>"
        )
    answer_callback(callback_id, "📝 Skipped.")

def handle_exit(callback_id, signal_id):
    trade = pending_trades.get(signal_id)
    if not trade or trade['status'] != 'holding':
        answer_callback(callback_id, "⚠️ No active trade.")
        return
    trade['status'] = 'awaiting_exit'
    user_states[CHAT_ID] = {"state": "awaiting_exit", "signal_id": signal_id}
    edit_message(
        chat_id=CHAT_ID,
        message_id=trade['message_id'],
        text=format_signal_message(trade['signal'], status="holding", risk=trade['risk']) + "\n\n💵 Enter your exit price:"
    )
    answer_callback(callback_id, "Please enter your exit price.")

def handle_cancel(callback_id, signal_id):
    trade = pending_trades.get(signal_id)
    if trade:
        trade['status'] = 'exited'
        edit_message(
            chat_id=CHAT_ID,
            message_id=trade['message_id'],
            text=format_signal_message(trade['signal']) + "\n\n⛔ <b>CANCELLED</b>"
        )
        user_states.pop(CHAT_ID, None)
    answer_callback(callback_id, "Trade cancelled.")

# ─── HANDLE TEXT MESSAGES ────────────────────────────────────────────────

def handle_text_message(message):
    chat_id = str(message['chat']['id'])
    if chat_id != CHAT_ID:
        return

    text = message.get('text', '').strip()
    user_state = user_states.get(chat_id)
    if not user_state:
        return

    state = user_state['state']
    signal_id = user_state['signal_id']
    trade = pending_trades.get(signal_id)
    if not trade:
        user_states.pop(chat_id, None)
        return

    if state == 'awaiting_risk':
        try:
            risk = float(text)
            if risk <= 0:
                raise ValueError
        except ValueError:
            send_message(chat_id, "⚠️ Please enter a valid positive number (e.g., 100).")
            return

        trade['risk'] = risk
        trade['status'] = 'holding'
        user_states.pop(chat_id, None)

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🚪 Exit", "callback_data": f"exit_{signal_id}"},
                    {"text": "❌ Cancel", "callback_data": f"cancel_{signal_id}"}
                ]
            ]
        }
        edit_message(
            chat_id=CHAT_ID,
            message_id=trade['message_id'],
            text=format_signal_message(trade['signal'], status="holding", risk=risk),
            reply_markup=keyboard
        )
        send_message(chat_id, f"✅ Trade logged. Risk: ${risk:.2f}. Tap 'Exit' when you close the trade.")

    elif state == 'awaiting_exit':
        try:
            exit_price = float(text)
        except ValueError:
            send_message(chat_id, "⚠️ Please enter a valid price (e.g., 1.28500).")
            return

        entry = float(trade['entry'])
        sl = float(trade['sl'])
        risk = trade['risk']
        direction = trade['dir']
        stop_distance = abs(entry - sl)
        if direction == 'Long':
            pnl = (exit_price - entry) / stop_distance * risk
        else:
            pnl = (entry - exit_price) / stop_distance * risk
        r_multiple = pnl / risk

        trade['exit_price'] = exit_price
        trade['r_multiple'] = r_multiple
        trade['status'] = 'exited'
        user_states.pop(chat_id, None)

        log_trade_to_sheet(trade)

        edit_message(
            chat_id=CHAT_ID,
            message_id=trade['message_id'],
            text=format_signal_message(trade['signal'], status="exited", exit_price=exit_price, r_multiple=r_multiple)
        )
        send_message(chat_id, f"✅ Trade closed. P&L: ${pnl:.2f} (R: {r_multiple:.2f})")

# ─── LOG TO GOOGLE SHEETS ─────────────────────────────────────────────────

def log_trade_to_sheet(trade):
    client = get_gspread_client()
    if not client:
        logger.error("Cannot log: no Google Sheets client")
        return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Trade Log")
    except Exception as e:
        logger.error(f"Cannot open sheet: {e}")
        return

    signal = trade['signal']
    row = [
        f"🤖 Bot — {time.strftime('%Y-%m-%d %H:%M:%S')}",
        time.strftime('%Y-%m-%d'),
        time.strftime('%H:%M'),
        signal.get('pair', ''),
        f"{signal.get('dir', '')} 📈" if signal.get('dir') == 'Long' else f"{signal.get('dir', '')} 📉",
        signal.get('signal', ''),
        "",
        "",
        signal.get('lr', ''),
        signal.get('ema', ''),
        "",
        "",
        signal.get('cons', ''),
        signal.get('entry', ''),
        signal.get('sl', ''),
        "",
        "Win ✅" if trade['r_multiple'] > 0 else "Loss ❌",
        trade.get('exit_price', ''),
        "",
        "",
        "",
        trade.get('risk', ''),
        trade.get('r_multiple', ''),
        "",
        ""
    ]
    try:
        sheet.append_row(row)
        logger.info(f"✅ Logged trade: {signal['pair']} {signal['dir']} R={trade.get('r_multiple', 0):.2f}")
    except Exception as e:
        logger.error(f"Failed to append row: {e}")

# ─── SCORING ──────────────────────────────────────────────────────────────

def compute_score(engine, direction):
    if not engine or not engine.lr_valid:
        return 0.0
    score = 0.0
    if direction == 'Long' and engine.lr_slope > 0:
        score += 3.0
    elif direction == 'Short' and engine.lr_slope < 0:
        score += 3.0
    if engine.saved_r and abs(engine.saved_r) >= 0.7:
        score += min(2.0, abs(engine.saved_r) * 2)
    if engine.lr_upper and engine.lr_lower:
        if direction == 'Long' and engine.closes[-1] <= engine.lr_lower + engine.atr_val * 0.5:
            score += 2.0
        elif direction == 'Short' and engine.closes[-1] >= engine.lr_upper - engine.atr_val * 0.5:
            score += 2.0
    if engine.rsi_val:
        if direction == 'Long' and engine.rsi_val < 40:
            score += 2.0
        elif direction == 'Short' and engine.rsi_val > 60:
            score += 2.0
    if engine.ema200:
        if direction == 'Long' and engine.closes[-1] > engine.ema200:
            score += 1.0
        elif direction == 'Short' and engine.closes[-1] < engine.ema200:
            score += 1.0
    return min(10.0, score)

def update_scores_sheet():
    client = get_gspread_client()
    if not client:
        return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Scores")
    except:
        sheet = client.open_by_key(SHEET_ID).add_worksheet("Scores", rows=100, cols=10)
        sheet.append_row(["Timestamp", "Pair", "Long Score", "Short Score", "LR Slope", "R", "ATR", "Price"])

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    rows = []
    for name, engine in engines.items():
        if not engine:
            continue
        long_score = compute_score(engine, 'Long')
        short_score = compute_score(engine, 'Short')
        lr_slope = engine.lr_slope if engine.lr_slope is not None else 0
        r_val = engine.saved_r if engine.saved_r is not None else 0
        atr = engine.atr_val if engine.atr_val is not None else 0
        price = engine.closes[-1] if engine.closes else 0
        rows.append([timestamp, name, round(long_score,2), round(short_score,2), round(lr_slope,5), round(r_val,3), round(atr,5), round(price,5)])

    if rows:
        sheet.clear()
        sheet.append_row(["Timestamp", "Pair", "Long Score", "Short Score", "LR Slope", "R", "ATR", "Price"])
        for row in rows:
            sheet.append_row(row)
        logger.info(f"✅ Updated Scores sheet with {len(rows)} instruments")

def scoring_loop():
    while True:
        try:
            update_scores_sheet()
        except Exception as e:
            logger.error(f"Scoring loop error: {e}")
        time.sleep(3600)

# ─── BOT ENGINE ──────────────────────────────────────────────────────────

def run_bot_for_instrument(instrument_config):
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
                            send_telegram_signal(signal)
                        last_time = row['time']
            time.sleep(60)
        except Exception as e:
            logger.error(f"❌ {instrument}: Loop error: {e}")
            time.sleep(60)

def start_all_engines():
    global bot_running
    for instrument_config in INSTRUMENTS:
        thread = threading.Thread(
            target=run_bot_for_instrument,
            args=(instrument_config,),
            daemon=True
        )
        thread.start()
        logger.info(f"✅ Started thread for {instrument_config['name']}")
        time.sleep(2)

# ─── FLASK ROUTES ──────────────────────────────────────────────────────────

@app.route('/')
def health():
    status = "running" if bot_running else "initializing"
    instrument_status = {}
    for name, engine in engines.items():
        instrument_status[name] = {
            "bars": len(engine.closes) if engine else 0,
            "lr_valid": engine.lr_valid if engine else False,
        }
    return jsonify({"status": status, "instruments": instrument_status})

@app.route('/status')
def status():
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
    is_running = len(engines) > 0
    return jsonify({"status": "running" if is_running else "stopped", "instruments": instrument_status})

@app.route('/test_signal/<instrument>')
def test_signal(instrument):
    logger.info(f"🔍 Test signal requested for {instrument}")
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
        return jsonify({"status": "test signal sent", "instrument": instrument})
    except Exception as e:
        logger.error(f"❌ Test signal failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/test_oanda/<instrument>')
def test_oanda(instrument):
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
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": "🟢 Bot is alive and connected!", "parse_mode": "HTML"}
        resp = requests.post(url, json=payload, timeout=10)
        return jsonify({"status": "message sent", "telegram_response": resp.status_code})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/start_engine')
def start_engine():
    global bot_running
    if bot_running:
        return jsonify({"status": "already running"})
    thread = threading.Thread(target=run_bot_for_instrument, args=(INSTRUMENTS[0],), daemon=True)
    thread.start()
    return jsonify({"status": "engine starting"})

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json()
        logger.info(f"📥 Webhook received: {data}")

        if 'callback_query' in data:
            callback = data['callback_query']
            callback_id = callback['id']
            raw = callback['data']
            parts = raw.split('_', 1)
            action = parts[0]
            signal_id = parts[1] if len(parts) > 1 else None

            if not signal_id:
                answer_callback(callback_id, "Invalid signal.")
                return "OK", 200

            if action == 'taken':
                handle_taken(callback_id, signal_id)
            elif action == 'skipped':
                handle_skipped(callback_id, signal_id)
            elif action == 'exit':
                handle_exit(callback_id, signal_id)
            elif action == 'cancel':
                handle_cancel(callback_id, signal_id)
            else:
                answer_callback(callback_id, "Unknown action.")

        elif 'message' in data and 'text' in data['message']:
            handle_text_message(data['message'])

        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "OK", 200

# ─── ENTRY POINT ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    start_all_engines()
    threading.Thread(target=scoring_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=8080)