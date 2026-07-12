# engine.py

import numpy as np
import pandas as pd
from config import PARAMS
from indicators import atr, rsi, ema, lr_channel, find_pivots

class TradingViewEngine:
    def __init__(self):
        self.p = PARAMS

        # Data buffers
        self.opens = []
        self.highs = []
        self.lows = []
        self.closes = []
        self.times = []

        # State variables (match Pine's "var")
        self.atr_val = None
        self.rsi_val = None
        self.ema200 = None

        # LR State
        self.lr_valid = False
        self.lr_slope = None
        self.lr_upper = None
        self.lr_lower = None
        self.lr_start = None
        self.viol_count = 0
        self.saved_m = None
        self.saved_b = None
        self.saved_sd = None
        self.saved_r = None
        self.saved_start = None
        self.saved_end = None

        # ZigZag
        self.zz_dir = 0
        self.zz_run_high = None
        self.zz_run_high_bar = None
        self.zz_run_low = None
        self.zz_run_low_bar = None
        self.zz_h1 = None
        self.zz_hbar1 = None
        self.zz_h2 = None
        self.zz_hbar2 = None
        self.zz_l1 = None
        self.zz_lbar1 = None
        self.zz_l2 = None
        self.zz_lbar2 = None

        # Pivots (used for CHoCH)
        self.ms_h1 = None
        self.ms_hbar1 = None
        self.ms_h2 = None
        self.ms_hbar2 = None
        self.ms_l1 = None
        self.ms_lbar1 = None
        self.ms_l2 = None
        self.ms_lbar2 = None
        self.last_was_up = False
        self.last_was_dn = False
        self.choch_bull_fired = False
        self.choch_bear_fired = False

        # Divergence / Convergence
        self.last_div_price = None
        self.last_div_bar = None
        self.div_follow_up = False
        self.div_follow_up_confirmed = False
        self.last_conv_price = None
        self.last_conv_bar = None
        self.conv_follow_up = False
        self.conv_follow_up_confirmed = False

        # Fibonacci / OTE
        self.last_fib_high_price = None
        self.last_fib_high_bar = None
        self.last_fib_low_price = None
        self.last_fib_low_bar = None
        self.fib_dir = 0
        self.ote_done = False
        self.last_drawn_high = None
        self.last_drawn_low = None

        # Consolidation
        self.cons_ph_price = []
        self.cons_ph_bar = []
        self.cons_pl_price = []
        self.cons_pl_bar = []
        self.cons_left = []
        self.cons_right = []
        self.cons_top = []
        self.cons_bottom = []
        self.cons_active = []

        # Wait states
        self.waiting_for_choch_long = False
        self.waiting_for_choch_short = False

        # Daily S/R (simplified – we'll hold daily pivots)
        self.daily_highs = []
        self.daily_lows = []
        self.daily_closes = []
        self.daily_times = []
        self.daily_pivots_high = []  # (price, idx)
        self.daily_pivots_low = []
        self.sr_channels = []  # list of (top, bottom, strength)

    def ingest_batch(self, df):
        """Process a batch of historical bars sequentially."""
        for _, row in df.iterrows():
            self.step(
                row['open'], row['high'], row['low'], row['close'], row['time']
            )

    def step(self, o, h, l, c, ts):
        # Append
        self.opens.append(o)
        self.highs.append(h)
        self.lows.append(l)
        self.closes.append(c)
        self.times.append(ts)

        # Trim to reasonable size (5000 bars)
        if len(self.closes) > 5000:
            self.closes = self.closes[-5000:]
            self.highs = self.highs[-5000:]
            self.lows = self.lows[-5000:]
            self.opens = self.opens[-5000:]
            self.times = self.times[-5000:]

        n = len(self.closes)
        if n < 200:
            return None  # Not enough data

        # Convert to pandas Series for indicator calc
        close_series = pd.Series(self.closes)
        high_series = pd.Series(self.highs)
        low_series = pd.Series(self.lows)

        # ── 1. ATR ────────────────────────────────────────────────
        if n >= self.p['atrLen']:
            self.atr_val = atr(high_series, low_series, close_series, self.p['atrLen']).iloc[-1]

        # ── 2. RSI ────────────────────────────────────────────────
        if n >= self.p['rsiLen']:
            self.rsi_val = rsi(close_series, self.p['rsiLen']).iloc[-1]

        # ── 3. EMA200 ─────────────────────────────────────────────
        self.ema200 = ema(close_series, 200).iloc[-1]

        # ── 4. LR Channel ──────────────────────────────────────────
        self._update_lr(close_series)

        # ── 5. Pivots (for CHoCH & ZigZag) ──────────────────────
        self._update_pivots(high_series, low_series)

        # ── 6. ZigZag ─────────────────────────────────────────────
        self._update_zigzag(h, l, c)

        # ── 7. Divergence / Convergence ──────────────────────────
        self._update_divergence()

        # ── 8. Fibonacci / OTE ────────────────────────────────────
        self._update_fib()

        # ── 9. Consolidation ──────────────────────────────────────
        self._update_consolidation()

        # ── 10. CHoCH & Market Structure ──────────────────────────
        self._update_choch()

        # ── 11. Signal Gating ─────────────────────────────────────
        signal = self._check_signals()
        return signal

    # ─── PRIVATE METHODS ──────────────────────────────────────────

    def _update_lr(self, close_series):
        n = len(close_series)
        if self.lr_start is None:
            self.lr_start = n - 1

        dyn_len = min(n - self.lr_start, self.p['lrMaxLen'])
        if dyn_len < self.p['lrMinLen']:
            return

        m, b, sd, r = lr_channel(close_series, dyn_len)
        if m is None:
            return

        start_bar = n - dyn_len
        mid_end = m * (dyn_len - 1) + b
        upper = mid_end + self.p['lrDevMult'] * sd
        lower = mid_end - self.p['lrDevMult'] * sd
        r_ok = abs(r) >= self.p['lrMinR']
        in_band = lower <= close_series.iloc[-1] <= upper

        self.lr_slope = m
        self.lr_upper = upper
        self.lr_lower = lower

        if r_ok and in_band:
            self.lr_valid = True
            self.viol_count = 0
            self.saved_m = m
            self.saved_b = b
            self.saved_sd = sd
            self.saved_r = r
            self.saved_start = start_bar
            self.saved_end = n - 1
        else:
            self.lr_valid = False
            self.viol_count += 1
            if self.viol_count >= self.p['lrGrace']:
                # Reset LR state (match Pine's reset)
                self.lr_start = n - 1
                self.viol_count = 0
                self.saved_m = None
                self.saved_b = None
                self.saved_sd = None
                self.saved_r = None
                self.saved_start = None
                self.saved_end = None
                self.lr_valid = False

    def _update_pivots(self, high_series, low_series):
        """Update market structure pivots (ms_h1, ms_l1, etc.)"""
        n = len(high_series)
        if n < self.p['swingLen'] * 2 + 1:
            return

        # Find pivots in the last ~200 bars (efficient)
        h_vals, h_idx, l_vals, l_idx = find_pivots(
            high_series.values, low_series.values,
            self.p['swingLen'], self.p['swingLen']
        )

        if h_vals:
            # Update ms_h2 -> ms_h1 -> new
            self.ms_h2 = self.ms_h1
            self.ms_hbar2 = self.ms_hbar1
            self.ms_h1 = h_vals[-1]
            self.ms_hbar1 = h_idx[-1]

        if l_vals:
            self.ms_l2 = self.ms_l1
            self.ms_lbar2 = self.ms_lbar1
            self.ms_l1 = l_vals[-1]
            self.ms_lbar1 = l_idx[-1]

    def _update_zigzag(self, h, l, c):
        """Stateful ZigZag logic."""
        if self.zz_run_high is None:
            self.zz_run_high = h
            self.zz_run_high_bar = len(self.closes) - 1
        if self.zz_run_low is None:
            self.zz_run_low = l
            self.zz_run_low_bar = len(self.closes) - 1

        if h > self.zz_run_high:
            self.zz_run_high = h
            self.zz_run_high_bar = len(self.closes) - 1
        if l < self.zz_run_low:
            self.zz_run_low = l
            self.zz_run_low_bar = len(self.closes) - 1

        atr_mult = self.atr_val * self.p['atrMult'] if self.atr_val else 999

        # Long → Short
        if self.zz_dir != -1 and (self.zz_run_high - l) >= atr_mult:
            self.zz_h2 = self.zz_h1
            self.zz_hbar2 = self.zz_hbar1
            self.zz_h1 = self.zz_run_high
            self.zz_hbar1 = self.zz_run_high_bar
            self.zz_dir = -1
            self.zz_run_low = l
            self.zz_run_low_bar = len(self.closes) - 1

        # Short → Long
        elif self.zz_dir != 1 and (h - self.zz_run_low) >= atr_mult:
            self.zz_l2 = self.zz_l1
            self.zz_lbar2 = self.zz_lbar1
            self.zz_l1 = self.zz_run_low
            self.zz_lbar1 = self.zz_run_low_bar
            self.zz_dir = 1
            self.zz_run_high = h
            self.zz_run_high_bar = len(self.closes) - 1

    def _update_divergence(self):
        """Check divergence/convergence between price swings and RSI."""
        if self.rsi_val is None or self.atr_val is None:
            return

        n = len(self.closes)
        if n < 2:
            return

        # Bullish Divergence: price makes lower low, RSI makes higher low
        # Bearish Divergence: price makes higher high, RSI makes lower high

        # Simplified: check last two ZigZag lows/highs
        if self.zz_h1 is not None and self.zz_h2 is not None:
            # Get RSI at those bars
            rsi_h1 = self._rsi_at_bar(self.zz_hbar1)
            rsi_h2 = self._rsi_at_bar(self.zz_hbar2)
            if rsi_h1 is not None and rsi_h2 is not None:
                if self.zz_h1 > self.zz_h2 and rsi_h1 < rsi_h2:
                    # Bearish Divergence
                    self.div_follow_up = True
                    self.last_div_price = self.zz_h1
                    self.last_div_bar = self.zz_hbar1
                    self.div_follow_up_confirmed = False
                elif self.zz_h1 < self.zz_h2 and rsi_h1 > rsi_h2:
                    # Bullish Convergence (follow-up)
                    self.conv_follow_up = True
                    self.last_conv_price = self.zz_l1
                    self.last_conv_bar = self.zz_lbar1
                    self.conv_follow_up_confirmed = False

        # Check follow-up confirmation
        if self.div_follow_up and self.zz_h1 is not None and self.last_div_price is not None:
            if self.zz_h1 < self.last_div_price:
                self.div_follow_up_confirmed = True
                self.div_follow_up = False
        if self.conv_follow_up and self.zz_l1 is not None and self.last_conv_price is not None:
            if self.zz_l1 > self.last_conv_price:
                self.conv_follow_up_confirmed = True
                self.conv_follow_up = False

    def _rsi_at_bar(self, bar_idx):
        """Get RSI value at a specific bar index (from history)."""
        if bar_idx is None or bar_idx < self.p['rsiLen']:
            return None
        # We'd need to store historical RSI – for simplicity, recalc slice
        if bar_idx >= len(self.closes):
            return None
        slice_close = pd.Series(self.closes[:bar_idx+1])
        if len(slice_close) < self.p['rsiLen']:
            return None
        rsi_vals = rsi(slice_close, self.p['rsiLen'])
        return rsi_vals.iloc[-1] if not pd.isna(rsi_vals.iloc[-1]) else None

    def _update_fib(self):
        """Fibonacci state: detect bull/bear legs and OTE."""
        if self.zz_h1 is None or self.zz_l1 is None:
            return

        is_bull_leg = (self.zz_h1 > self.zz_h2) and (self.zz_l1 > self.zz_l2)
        is_bear_leg = (self.zz_h1 < self.zz_h2) and (self.zz_l1 < self.zz_l2)

        if is_bull_leg and self.zz_lbar1 < self.zz_hbar1:
            self.last_fib_low_price = self.zz_l1
            self.last_fib_low_bar = self.zz_lbar1
            self.last_fib_high_price = self.zz_h1
            self.last_fib_high_bar = self.zz_hbar1
            self.fib_dir = 1
            self.ote_done = False
        elif is_bear_leg and self.zz_hbar1 < self.zz_lbar1:
            self.last_fib_high_price = self.zz_h1
            self.last_fib_high_bar = self.zz_hbar1
            self.last_fib_low_price = self.zz_l1
            self.last_fib_low_bar = self.zz_lbar1
            self.fib_dir = -1
            self.ote_done = False

        # Live OTE detection (simplified: just check if current price is in OTE zone)
        # We'll rely on the main signal check for entries.

    def _update_consolidation(self):
        """Detect consolidation boxes from pivots."""
        # Simplified: detect if last two swing highs/lows are within buffer
        if len(self.cons_ph_price) < 2 or len(self.cons_pl_price) < 2:
            return

        ph1 = self.cons_ph_price[-1]
        ph2 = self.cons_ph_price[-2]
        phb1 = self.cons_ph_bar[-1]
        phb2 = self.cons_ph_bar[-2]
        pl1 = self.cons_pl_price[-1]
        pl2 = self.cons_pl_price[-2]
        plb1 = self.cons_pl_bar[-1]
        plb2 = self.cons_pl_bar[-2]

        buf = self.atr_val * self.p['consBuf'] if self.atr_val else 0.001
        if abs(ph1 - ph2) <= buf and abs(pl1 - pl2) <= buf:
            top = max(ph1, ph2)
            bottom = min(pl1, pl2)
            left = min(phb1, phb2, plb1, plb2)
            # Store consolidation box
            self.cons_left.append(left)
            self.cons_right.append(len(self.closes) - 1)
            self.cons_top.append(top)
            self.cons_bottom.append(bottom)
            self.cons_active.append(True)

        # Expire boxes if price breaks out
        for i in range(len(self.cons_active)):
            if self.cons_active[i]:
                if self.closes[-1] > self.cons_top[i] or self.closes[-1] < self.cons_bottom[i]:
                    self.cons_active[i] = False

    def _update_choch(self):
        """Detect Change of Character."""
        if self.ms_h1 is None or self.ms_l1 is None:
            return

        is_uptrend = self.ms_l1 > self.ms_l2 if self.ms_l2 is not None else False
        is_downtrend = self.ms_h1 < self.ms_h2 if self.ms_h2 is not None else False

        if is_uptrend and not self.last_was_up:
            self.choch_bear_fired = False
        if is_downtrend and not self.last_was_dn:
            self.choch_bull_fired = False

        self.last_was_up = is_uptrend
        self.last_was_dn = is_downtrend

        close = self.closes[-1]
        if is_downtrend and self.ms_h1 is not None and close > self.ms_h1 and not self.choch_bull_fired:
            self.choch_bull_fired = True
            # Trigger CHoCH Bull
        if is_uptrend and self.ms_l1 is not None and close < self.ms_l1 and not self.choch_bear_fired:
            self.choch_bear_fired = True
            # Trigger CHoCH Bear

    def _check_signals(self):
        """Main signal gating logic – returns dict if signal, else None."""
        if self.atr_val is None or self.ema200 is None:
            return None

        n = len(self.closes)
        close = self.closes[-1]
        high = self.highs[-1]
        low = self.lows[-1]

        # ── Conditions ─────────────────────────────────────────────

        # LR Status
        lr_bull = self.lr_valid and self.lr_slope is not None and self.lr_slope > 0
        lr_bear = self.lr_valid and self.lr_slope is not None and self.lr_slope < 0

        # Band proximity
        band_tol = self.atr_val * self.p['lrBandTol']
        near_lower = self.lr_valid and self.lr_lower is not None and low <= self.lr_lower + band_tol
        near_upper = self.lr_valid and self.lr_upper is not None and high >= self.lr_upper - band_tol

        # EMA proximity
        near_ema_long = abs(low - self.ema200) <= self.atr_val * 0.5 and close > self.ema200
        near_ema_short = abs(high - self.ema200) <= self.atr_val * 0.5 and close < self.ema200

        # Consolidation
        in_cons = any(self.cons_active)

        # CHoCH new events
        new_choch_bull = self.choch_bull_fired  # simplified
        new_choch_bear = self.choch_bear_fired

        # Divergence / Convergence confirmations
        div_conf = self.div_follow_up_confirmed
        conv_conf = self.conv_follow_up_confirmed

        # ── Signals ─────────────────────────────────────────────────

        # Reversal Long: waiting for CHoCH after Convergence
        if conv_conf and new_choch_bull:
            self.waiting_for_choch_long = True
        if div_conf and new_choch_bear:
            self.waiting_for_choch_short = True

        # Type 1: Reversal
        rev_long = self.waiting_for_choch_long and new_choch_bull
        rev_short = self.waiting_for_choch_short and new_choch_bear

        if rev_long: self.waiting_for_choch_long = False
        if rev_short: self.waiting_for_choch_short = False

        # Type 3: Trend
        trend_long = (not in_cons) and lr_bull and near_lower
        trend_short = (not in_cons) and lr_bear and near_upper

        # Type 4: CHoCH only
        choch_long = (not rev_long) and new_choch_bull
        choch_short = (not rev_short) and new_choch_bear

        # Type 5: Consolidation
        cons_long = in_cons and low <= self.cons_bottom[-1] + self.atr_val * 0.5 if self.cons_bottom else False
        cons_short = in_cons and high >= self.cons_top[-1] - self.atr_val * 0.5 if self.cons_top else False

        # ── Build signal ────────────────────────────────────────────

        signal = None
        if rev_long or trend_long or choch_long or cons_long:
            signal = {
                "signal": "Type 3 Trend (LR Channel Band)" if trend_long else
                          "Type 1 — Reversal" if rev_long else
                          "Type 4 — CHoCH" if choch_long else
                          "Type 5 — Consolidation",
                "dir": "Long",
                "pair": "GBPUSD",
                "tf": "1H",
                "entry": round(close, 5),
                "sl": round(close - self.atr_val * 2, 5),
                "tp": round(close + self.atr_val * 3, 5),
                "lr": "✅ Bullish" if lr_bull else "❌",
                "ema": "✅" if near_ema_long else "➖",
                "cons": "📦" if in_cons else "➖",
                "div": "✅" if div_conf else "⏳" if self.div_follow_up else "➖",
                "conv": "✅" if conv_conf else "⏳" if self.conv_follow_up else "➖",
                "choch": "✅" if new_choch_bull else "➖",
                "time": str(self.times[-1].timestamp() * 1000).split('.')[0]
            }

        elif rev_short or trend_short or choch_short or cons_short:
            signal = {
                "signal": "Type 3 Trend (LR Channel Band)" if trend_short else
                          "Type 1 — Reversal" if rev_short else
                          "Type 4 — CHoCH" if choch_short else
                          "Type 5 — Consolidation",
                "dir": "Short",
                "pair": "GBPUSD",
                "tf": "1H",
                "entry": round(close, 5),
                "sl": round(close + self.atr_val * 2, 5),
                "tp": round(close - self.atr_val * 3, 5),
                "lr": "✅ Bearish" if lr_bear else "❌",
                "ema": "✅" if near_ema_short else "➖",
                "cons": "📦" if in_cons else "➖",
                "div": "✅" if div_conf else "⏳" if self.div_follow_up else "➖",
                "conv": "✅" if conv_conf else "⏳" if self.conv_follow_up else "➖",
                "choch": "✅" if new_choch_bear else "➖",
                "time": str(self.times[-1].timestamp() * 1000).split('.')[0]
            }

        return signal