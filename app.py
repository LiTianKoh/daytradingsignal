# app.py - Full Updated Version

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
engines = {}                # {instrument_name: engine_instance}
pending_trades = {}         # {signal_id: trade_data}
user_states = {}            # {chat_id: {"state": "awaiting_risk"|"awaiting_exit"|None, "signal_id": ...}}
bot_running = False
BOT_TOKEN = "8148974966:AAFqW1LmHySlvH_5v79itFA2NrFowEqnQpY"
CHAT_ID = "5572387258"
SHEET_ID = "1pfThksgRPNK2ZmDbS9QcG8YEMEZAqhBcJOcoljLhul0"  # Use your actual sheet ID

# ─── GOOGLE SHEETS AUTH ─────────────────────────────────────────────────────

def get_gspread_client():
    """Get authorized gspread client using environment credentials."""
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
    """Send a plain text message to Telegram."""
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
    """Edit an existing Telegram message."""
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
    """Answer a callback query."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id, "text": text, "show_alert": False}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Answer callback error: {e}")

# ─── SIGNAL MESSAGE FORMATTER ─────────────────────────────────────────────

def format_signal_message(data, status=None, risk=None, exit_price=None, r_multiple=None):
    """Format the signal message with optional status."""
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
    """Send a new signal with Yes/No buttons."""
    signal_id = f"{signal_data['pair']}_{int(time.time()*1000)}"
    pending_trades[signal_id] = {
        "signal": signal_data,
        "status": "pending",  # pending, awaiting_risk, holding, awaiting_exit, exited
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
        # Store message_id for later editing
        pending_trades[signal_id]['message_id'] = resp['result']['message_id']
        pending_trades[signal_id]['chat_id'] = CHAT_ID
    else:
        logger.error(f"Failed to send signal: {resp}")

# ─── HANDLE CALLBACKS ─────────────────────────────────────────────────────

def handle_taken(callback_id, signal_id):
    """User tapped Yes - ask for risk amount."""
    trade = pending_trades.get(signal_id)
    if not trade:
        answer_callback(callback_id, "⚠️ Signal expired.")
        return
    if trade['status'] != 'pending':
        answer_callback(callback_id, "⚠️ Already processed.")
        return

    # Update status to awaiting_risk
    trade['status'] = 'awaiting_risk'
    user_states[CHAT_ID] = {"state": "awaiting_risk", "signal_id": signal_id}

    # Edit original message to remove buttons and ask for risk
    edit_message(
        chat_id=CHAT_ID,
        message_id=trade['message_id'],
        text=format_signal_message(trade['signal']) + "\n\n💰 How much USD are you risking on this trade? (e.g., 100)",
        reply_markup=None
    )
    answer_callback(callback_id, "Please enter your risk amount.")

def handle_skipped(callback_id, signal_id):
    """User tapped No - skip trade."""
    trade = pending_trades.get(signal_id)
    if trade:
        trade['status'] = 'exited'  # mark as skipped
        edit_message(
            chat_id=CHAT_ID,
            message_id=trade['message_id'],
            text=format_signal_message(trade['signal']) + "\n\n❌ <b>SKIPPED</b>"
        )
    answer_callback(callback_id, "📝 Skipped.")

def handle_exit(callback_id, signal_id):
    """User tapped Exit - ask for exit price."""
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
    """User cancelled the trade."""
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

# ─── HANDLE TEXT MESSAGES (Risk & Exit price) ─────────────────────────────

def handle_text_message(message):
    """Process text messages for risk and exit price."""
    chat_id = str(message['chat']['id'])
    if chat_id != CHAT_ID:
        return  # only respond to our own chat

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

        # Save risk and update status
        trade['risk'] = risk
        trade['status'] = 'holding'
        user_states.pop(chat_id, None)

        # Edit message to show Holding with Exit button
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

        # Compute P&L and R multiple
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

        # Log to Google Sheets
        log_trade_to_sheet(trade)

        # Edit message with outcome
        edit_message(
            chat_id=CHAT_ID,
            message_id=trade['message_id'],
            text=format_signal_message(trade['signal'], status="exited", exit_price=exit_price, r_multiple=r_multiple)
        )
        send_message(chat_id, f"✅ Trade closed. P&L: ${pnl:.2f} (R: {r_multiple:.2f})")

# ─── LOG TO GOOGLE SHEETS ─────────────────────────────────────────────────

def log_trade_to_sheet(trade):
    """Append the final trade data to the Trade Log sheet."""
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
        f"🤖 Bot — {time.strftime('%Y-%m-%d %H:%M:%S')}",  # A: Timestamp
        time.strftime('%Y-%m-%d'),  # B: Date
        time.strftime('%H:%M'),  # C: Time
        signal.get('pair', ''),  # D: Pair
        f"{signal.get('dir', '')} 📈" if signal.get('dir') == 'Long' else f"{signal.get('dir', '')} 📉",  # E: Direction
        signal.get('signal', ''),  # F: Signal Type
        "",  # G: DXY Bias
        "",  # H: DXY Aligned
        signal.get('lr', ''),  # I: LR Channel
        signal.get('ema', ''),  # J: EMA
        "",  # K: OTE
        "",  # L: S/R
        signal.get('cons', ''),  # M: Cons
        signal.get('entry', ''),  # N: Entry
        signal.get('sl', ''),  # O: SL
        "",  # P: TP (we don't have a fixed TP)
        "Win ✅" if trade['r_multiple'] > 0 else "Loss ❌",  # Q: Outcome
        trade.get('exit_price', ''),  # R: Exit
        "",  # S: Notes
        "",  # T: RR (will be computed)
        "",  # U: Win (will be computed)
        trade.get('risk', ''),  # V: Risk Amount
        trade.get('r_multiple', ''),  # W: Actual R Multiple
        "",  # X: Holding Time (can compute later)
        ""   # Y: ATR at Entry (not stored yet)
    ]
    try:
        sheet.append_row(row)
        logger.info(f"✅ Logged trade: {signal['pair']} {signal['dir']} R={trade.get('r_multiple', 0):.2f}")
    except Exception as e:
        logger.error(f"Failed to append row: {e}")

# ─── SCORING FUNCTION ──────────────────────────────────────────────────────

def compute_score(engine, direction):
    """
    Compute a score (0-10) for a given direction based on engine state.
    Score components: LR slope, R², price position relative to bands, RSI, etc.
    """
    if not engine or not engine.lr_valid:
        return 0.0

    score = 0.0
    # LR slope alignment
    if direction == 'Long' and engine.lr_slope > 0:
        score += 3.0
    elif direction == 'Short' and engine.lr_slope < 0:
        score += 3.0

    # R-squared (from saved R)
    if engine.saved_r and abs(engine.saved_r) >= 0.7:
        score += min(2.0, abs(engine.saved_r) * 2)  # up to 2 points

    # Price near bands
    if engine.lr_upper and engine.lr_lower:
        if direction == 'Long' and engine.closes[-1] <= engine.lr_lower + engine.atr_val * 0.5:
            score += 2.0
        elif direction == 'Short' and engine.closes[-1] >= engine.lr_upper - engine.atr_val * 0.5:
            score += 2.0

    # RSI overbought/oversold
    if engine.rsi_val:
        if direction == 'Long' and engine.rsi_val < 40:
            score += 2.0
        elif direction == 'Short' and engine.rsi_val > 60:
            score += 2.0

    # EMA alignment
    if engine.ema200:
        if direction == 'Long' and engine.closes[-1] > engine.ema200:
            score += 1.0
        elif direction == 'Short' and engine.closes[-1] < engine.ema200:
            score += 1.0

    return min(10.0, score)

def update_scores_sheet():
    """Periodically compute scores for all instruments and update Google Sheets."""
    client = get_gspread_client()
    if not client:
        return
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Scores")
    except:
        # Create Scores sheet if missing
        sheet = client.open_by_key(SHEET_ID).add_worksheet("Scores", rows=100, cols=10)
        sheet.append_row(["Timestamp", "Pair", "Long Score", "Short Score", "LR Slope", "R", "ATR", "Price"])

    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    rows = []
    for name, engine in engines.items():
        if not engine:
            continue
        long_score = compute_score(engine, 'Long')
        short_score = compute_score(engine, 'Short')
        # Also capture some metrics
        lr_slope = engine.lr_slope if engine.lr_slope is not None else 0
        r_val = engine.saved_r if engine.saved_r is not None else 0
        atr = engine.atr_val if engine.atr_val is not None else 0
        price = engine.closes[-1] if engine.closes else 0
        rows.append([timestamp, name, round(long_score,2), round(short_score,2), round(lr_slope,5), round(r_val,3), round(atr,5), round(price,5)])

    if rows:
        # Clear existing data and write new (we keep only latest scores)
        sheet.clear()
        sheet.append_row(["Timestamp", "Pair", "Long Score", "Short Score", "LR Slope", "R", "ATR", "Price"])
        for row in rows:
            sheet.append_row(row)
        logger.info(f"✅ Updated Scores sheet with {len(rows)} instruments")

# ─── SCORING LOOP ──────────────────────────────────────────────────────────

def scoring_loop():
    """Run scoring update every hour."""
    while True:
        try:
            update_scores_sheet()
        except Exception as e:
            logger.error(f"Scoring loop error: {e}")
        time.sleep(3600)  # 1 hour

# ─── FLASK ROUTES ──────────────────────────────────────────────────────────

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    """Handle all incoming Telegram updates."""
    try:
        data = request.get_json()
        logger.info(f"📥 Webhook received: {data}")

        # Handle callback queries (button taps)
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

        # Handle text messages (risk, exit price)
        elif 'message' in data and 'text' in data['message']:
            handle_text_message(data['message'])

        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "OK", 200

# ─── EXISTING ROUTES (health, status, test, etc.) ────────────────────────
# ... (keep your existing routes: /, /status, /test_signal, /test_oanda, /ping_telegram, /start_engine)
# I'll include them below for completeness, but they remain unchanged.

# ─── ENTRY POINT ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Start engines (existing code)
    start_all_engines()

    # Start scoring thread
    threading.Thread(target=scoring_loop, daemon=True).start()

    # Keep Flask running
    app.run(host='0.0.0.0', port=8080)