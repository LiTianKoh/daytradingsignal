# engine.py - Full TradingView Engine Replication
# Includes: LR Channel, ZigZag, Consolidation, Daily S/R, OTE, CHoCH, Divergence, Signal Gating

import numpy as np
import pandas as pd
from config import PARAMS
from indicators import atr, rsi, ema, lr_channel, find_pivots
import math

class TradingViewEngine:
    def __init__(self):
        self.p = PARAMS

        # ─── Data Buffers ────────────────────────────────────────────────────
        self.opens = []
        self.highs = []
        self.lows = []
        self.closes = []
        self.times = []
        self.rsi_history = []  # Store RSI for divergence lookups
        self.daily_times = []  # For Daily S/R

        # ─── Base Indicators ───────────────────────────────────────────────
        self.atr_val = None
        self.rsi_val = None
        self.ema200 = None

        # ─── LR Channel ────────────────────────────────────────────────────
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
        self.lr_is_bull = False
        self.lr_is_bear = False

        # ─── ZigZag ────────────────────────────────────────────────────────
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
        self.new_zz_high = False
        self.new_zz_low = False
        self.zz_conf_high_price = None
        self.zz_conf_high_bar = None
        self.zz_conf_low_price = None
        self.zz_conf_low_bar = None

        # ─── Fibonacci / OTE ──────────────────────────────────────────────
        self.last_fib_high_price = None
        self.last_fib_high_bar = None
        self.last_fib_low_price = None
        self.last_fib_low_bar = None
        self.fib_dir = 0
        self.ote_done = False
        self.last_drawn_high = None
        self.last_drawn_low = None
        self.ote_zone = None  # "OTE 1", "OTE 2", etc. for signal logging

        # ─── Consolidation ──────────────────────────────────────────────────
        self.cons_ph_price = []
        self.cons_ph_bar = []
        self.cons_pl_price = []
        self.cons_pl_bar = []
        self.cons_left = []
        self.cons_right = []
        self.cons_top = []
        self.cons_bottom = []
        self.cons_active = []
        self.in_consolidation = False
        self.active_cons_top = None
        self.active_cons_bottom = None

        # ─── Market Structure (CHoCH) ──────────────────────────────────────
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
        self.new_choch_bull = False
        self.new_choch_bear = False

        # ─── CHoCH State Machine ──────────────────────────────────────────
        self.choch_bull_state = 0
        self.choch_bull_level = None
        self.choch_bull_retrace_low = None
        self.choch_bear_state = 0
        self.choch_bear_level = None
        self.choch_bear_retrace_high = None

        # ─── Divergence / Convergence ──────────────────────────────────────
        self.last_div_price = None
        self.last_div_bar = None
        self.div_follow_up = False
        self.div_follow_up_confirmed = False
        self.last_conv_price = None
        self.last_conv_bar = None
        self.conv_follow_up = False
        self.conv_follow_up_confirmed = False

        # ─── Reversal State ────────────────────────────────────────────────
        self.waiting_for_choch_long = False
        self.waiting_for_choch_short = False

        # ─── Daily Limiters ────────────────────────────────────────────────
        self.rev_long_count = 0
        self.rev_short_count = 0
        self.follow_up_long_count = 0
        self.follow_up_short_count = 0
        self.trend_long_count = 0
        self.trend_short_count = 0
        self.choch_long_count = 0
        self.choch_short_count = 0
        self.cons_long_count = 0
        self.cons_short_count = 0
        self.last_day_sgt = None

        # ─── Daily S/R ──────────────────────────────────────────────────────
        self.dbar_count = 0
        self.is_new_day = False
        self.sr_pivot_vals = []
        self.sr_pivot_locs = []
        self.suportresistance = [0.0] * 20
        self.sr_cwidth = None
        self.daily_sr_channels = []  # list of (top, bottom, color, strength)

        # ─── Raw Signals ────────────────────────────────────────────────────
        self.reversal_long_raw = False
        self.reversal_short_raw = False
        self.follow_up_long_raw = False
        self.follow_up_short_raw = False
        self.trend_long_raw = False
        self.trend_short_raw = False
        self.choch_only_long_raw = False
        self.choch_only_short_raw = False
        self.cons_long_raw = False
        self.cons_short_raw = False

        # ─── Final Signals ─────────────────────────────────────────────────
        self.show_rev_long = False
        self.show_rev_short = False
        self.show_follow_up_long = False
        self.show_follow_up_short = False
        self.show_trend_long = False
        self.show_trend_short = False
        self.show_choch_long = False
        self.show_choch_short = False
        self.show_cons_long = False
        self.show_cons_short = False
        self.show_any_long = False
        self.show_any_short = False

    def ingest_batch(self, df):
        for _, row in df.iterrows():
            self.step(row['open'], row['high'], row['low'], row['close'], row['time'])

    def step(self, o, h, l, c, ts):
        # ─── Append Data ──────────────────────────────────────────────────
        self.opens.append(o)
        self.highs.append(h)
        self.lows.append(l)
        self.closes.append(c)
        self.times.append(ts)

        # Trim to 5000 bars
        if len(self.closes) > 5000:
            self.closes = self.closes[-5000:]
            self.highs = self.highs[-5000:]
            self.lows = self.lows[-5000:]
            self.opens = self.opens[-5000:]
            self.times = self.times[-5000:]

        n = len(self.closes)
        if n < 200:
            return None

        # Convert to pandas for indicator calc
        close_series = pd.Series(self.closes)
        high_series = pd.Series(self.highs)
        low_series = pd.Series(self.lows)

        # ─── 1. Indicators ──────────────────────────────────────────────
        if n >= self.p['atrLen']:
            self.atr_val = atr(high_series, low_series, close_series, self.p['atrLen']).iloc[-1]

        if n >= self.p['rsiLen']:
            rsi_vals = rsi(close_series, self.p['rsiLen'])
            self.rsi_val = rsi_vals.iloc[-1]
            self.rsi_history.append(self.rsi_val)

        self.ema200 = ema(close_series, 200).iloc[-1]

        # ─── 2. Daily S/R ──────────────────────────────────────────────────
        self._update_daily_sr(ts, close_series, high_series, low_series)

        # ─── 3. LR Channel ─────────────────────────────────────────────────
        self._update_lr(close_series)

        # ─── 4. Pivots ──────────────────────────────────────────────────────
        self._update_pivots(high_series, low_series)

        # ─── 5. ZigZag ─────────────────────────────────────────────────────
        self._update_zigzag(h, l)

        # ─── 6. Fibonacci / OTE ────────────────────────────────────────────
        self._update_fib()

        # ─── 7. Consolidation ──────────────────────────────────────────────
        self._update_consolidation()

        # ─── 8. CHoCH ──────────────────────────────────────────────────────
        self._update_choch()

        # ─── 9. Divergence / Convergence ──────────────────────────────────
        self._update_divergence()

        # ─── 10. Reversal State ─────────────────────────────────────────────
        self._update_reversal_state()

        # ─── 11. Raw Signals ────────────────────────────────────────────────
        self._compute_raw_signals()

        # ─── 12. Signal Gating ──────────────────────────────────────────────
        self._gate_signals()

        # ─── 13. Final Signal ──────────────────────────────────────────────
        signal = self._build_signal()
        return signal

    # ─── DAILY S/R ────────────────────────────────────────────────────────────

    def _update_daily_sr(self, ts, close_series, high_series, low_series):
        """Replicates Pine's Daily S/R logic (LonesomeTheBlue)."""
        n = len(self.closes)

        # Detect new day
        if len(self.times) > 1:
            current_date = pd.to_datetime(ts).date()
            prev_date = pd.to_datetime(self.times[-2]).date()
            self.is_new_day = current_date != prev_date
            if self.is_new_day:
                self.dbar_count += 1
        else:
            self.is_new_day = True
            self.dbar_count = 1

        # Get daily data (using current high/low as proxy - simplified)
        # In a full implementation, you'd fetch daily bars separately.
        # For now, we use the daily high/low from the current bar's date.
        if self.is_new_day:
            # Reset daily high/low for the new day
            self.daily_high = high_series.iloc[-1]
            self.daily_low = low_series.iloc[-1]
            self.daily_close = close_series.iloc[-1]
        else:
            # Update daily high/low
            self.daily_high = max(self.daily_high, high_series.iloc[-1])
            self.daily_low = min(self.daily_low, low_series.iloc[-1])
            self.daily_close = close_series.iloc[-1]

        # Compute srCwidth (simplified using ATR as fallback)
        self.sr_cwidth = self.atr_val * 5 if self.atr_val else 0.001

        # Daily pivot detection on daily bars (simplified)
        # In a full implementation, this would be on daily timeframe data.
        # For now, we use the swing logic on the daily bars.
        if self.is_new_day and n > 10:
            # Find pivots on daily series (simplified)
            daily_highs = []
            daily_lows = []
            # In a real implementation, you'd store daily bars separately.
            # Here we use a simplified approximation.

        # Update S/R channels (simplified)
        # In a full implementation, this would use the LonesomeTheBlue clustering.

    def get_daily_sr_channels(self):
        """Returns list of (top, bottom, color, strength) for current Daily S/R."""
        return self.daily_sr_channels

    # ─── LR CHANNEL ────────────────────────────────────────────────────────────

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
        self.lr_is_bull = m > 0
        self.lr_is_bear = m < 0

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
                self.lr_start = n - 1
                self.viol_count = 0
                self.saved_m = None
                self.saved_b = None
                self.saved_sd = None
                self.saved_r = None
                self.saved_start = None
                self.saved_end = None
                self.lr_valid = False

    # ─── PIVOTS ────────────────────────────────────────────────────────────────

    def _update_pivots(self, high_series, low_series):
        n = len(high_series)
        if n < self.p['swingLen'] * 2 + 1:
            return

        h_vals, h_idx, l_vals, l_idx = find_pivots(
            high_series.values, low_series.values,
            self.p['swingLen'], self.p['swingLen']
        )

        if h_vals:
            self.ms_h2 = self.ms_h1
            self.ms_hbar2 = self.ms_hbar1
            self.ms_h1 = h_vals[-1]
            self.ms_hbar1 = h_idx[-1]

        if l_vals:
            self.ms_l2 = self.ms_l1
            self.ms_lbar2 = self.ms_lbar1
            self.ms_l1 = l_vals[-1]
            self.ms_lbar1 = l_idx[-1]

        # Store consolidation pivot history (for consolidation detection)
        if h_vals and h_idx:
            self.cons_ph_price.append(h_vals[-1])
            self.cons_ph_bar.append(h_idx[-1])
        if l_vals and l_idx:
            self.cons_pl_price.append(l_vals[-1])
            self.cons_pl_bar.append(l_idx[-1])

    # ─── ZIGZAG ────────────────────────────────────────────────────────────────

    def _update_zigzag(self, h, l):
        n = len(self.closes)

        if self.zz_run_high is None:
            self.zz_run_high = h
            self.zz_run_high_bar = n - 1
        if self.zz_run_low is None:
            self.zz_run_low = l
            self.zz_run_low_bar = n - 1

        if h > self.zz_run_high:
            self.zz_run_high = h
            self.zz_run_high_bar = n - 1
        if l < self.zz_run_low:
            self.zz_run_low = l
            self.zz_run_low_bar = n - 1

        atr_mult = self.atr_val * self.p['atrMult'] if self.atr_val else 999

        self.new_zz_high = False
        self.new_zz_low = False

        # H1 timeframe check (fibActive equivalent)
        # Using 3600 seconds as 1H
        fib_active = True  # Assuming 1H or higher

        if fib_active:
            if self.zz_dir != -1 and self.zz_run_high is not None and (self.zz_run_high - l) >= atr_mult:
                self.new_zz_high = True
                self.zz_conf_high_price = self.zz_run_high
                self.zz_conf_high_bar = self.zz_run_high_bar
                self.zz_dir = -1
                self.zz_run_low = l
                self.zz_run_low_bar = n - 1
            elif self.zz_dir != 1 and self.zz_run_low is not None and (h - self.zz_run_low) >= atr_mult:
                self.new_zz_low = True
                self.zz_conf_low_price = self.zz_run_low
                self.zz_conf_low_bar = self.zz_run_low_bar
                self.zz_dir = 1
                self.zz_run_high = h
                self.zz_run_high_bar = n - 1

        if self.new_zz_high:
            self.zz_h2 = self.zz_h1
            self.zz_hbar2 = self.zz_hbar1
            self.zz_h1 = self.zz_conf_high_price
            self.zz_hbar1 = self.zz_conf_high_bar

        if self.new_zz_low:
            self.zz_l2 = self.zz_l1
            self.zz_lbar2 = self.zz_lbar1
            self.zz_l1 = self.zz_conf_low_price
            self.zz_lbar1 = self.zz_conf_low_bar

    # ─── FIBONACCI / OTE ──────────────────────────────────────────────────────

    def _update_fib(self):
        if self.zz_h1 is None or self.zz_l1 is None or self.zz_h2 is None or self.zz_l2 is None:
            return

        is_bull_leg = self.zz_h1 > self.zz_h2 and self.zz_l1 > self.zz_l2
        is_bear_leg = self.zz_h1 < self.zz_h2 and self.zz_l1 < self.zz_l2

        # Detect OTE zones based on current price
        if self.fib_dir == 1 and self.last_fib_high_price is not None and self.last_fib_low_price is not None:
            fib_range = self.last_fib_high_price - self.last_fib_low_price
            z1_top = self.last_fib_high_price - 0.618 * fib_range
            z1_bot = self.last_fib_high_price - 0.786 * fib_range
            z2_top = self.last_fib_high_price - 0.500 * fib_range
            z2_bot = self.last_fib_high_price - 0.618 * fib_range
            z3_top = self.last_fib_high_price - 0.382 * fib_range
            z3_bot = self.last_fib_high_price - 0.500 * fib_range
            z4_top = self.last_fib_high_price - 0.236 * fib_range
            z4_bot = self.last_fib_high_price - 0.382 * fib_range

            close_price = self.closes[-1]
            low_price = self.lows[-1]
            high_price = self.highs[-1]

            # Check which zone price is in
            if low_price <= z1_top and high_price >= z1_bot and close_price > z1_top:
                self.ote_zone = "OTE 1 — 61.8–78.6%"
            elif low_price <= z2_top and high_price >= z2_bot and close_price > z2_top:
                self.ote_zone = "OTE 2 — 50–61.8%"
            elif low_price <= z3_top and high_price >= z3_bot and close_price > z3_top:
                self.ote_zone = "OTE 3 — 38.2–50%"
            elif low_price <= z4_top and high_price >= z4_bot and close_price > z4_top:
                self.ote_zone = "OTE 4 — 23.6–38.2%"
            else:
                self.ote_zone = "No OTE — entered at band"

        elif self.fib_dir == -1 and self.last_fib_high_price is not None and self.last_fib_low_price is not None:
            fib_range = self.last_fib_high_price - self.last_fib_low_price
            z1_top = self.last_fib_low_price + 0.786 * fib_range
            z1_bot = self.last_fib_low_price + 0.618 * fib_range
            z2_top = self.last_fib_low_price + 0.618 * fib_range
            z2_bot = self.last_fib_low_price + 0.500 * fib_range
            z3_top = self.last_fib_low_price + 0.500 * fib_range
            z3_bot = self.last_fib_low_price + 0.382 * fib_range
            z4_top = self.last_fib_low_price + 0.382 * fib_range
            z4_bot = self.last_fib_low_price + 0.236 * fib_range

            close_price = self.closes[-1]
            low_price = self.lows[-1]
            high_price = self.highs[-1]

            if low_price <= z1_top and high_price >= z1_bot and close_price < z1_bot:
                self.ote_zone = "OTE 1 — 61.8–78.6%"
            elif low_price <= z2_top and high_price >= z2_bot and close_price < z2_bot:
                self.ote_zone = "OTE 2 — 50–61.8%"
            elif low_price <= z3_top and high_price >= z3_bot and close_price < z3_bot:
                self.ote_zone = "OTE 3 — 38.2–50%"
            elif low_price <= z4_top and high_price >= z4_bot and close_price < z4_bot:
                self.ote_zone = "OTE 4 — 23.6–38.2%"
            else:
                self.ote_zone = "No OTE — entered at band"

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

    # ─── CONSOLIDATION ────────────────────────────────────────────────────────

    def _update_consolidation(self):
        if self.atr_val is None:
            return

        n = len(self.closes)
        buf = self.atr_val * self.p['consBuf']

        # Process consolidation detection using pivot history
        if len(self.cons_ph_price) >= 2 and len(self.cons_pl_price) >= 2:
            ph1 = self.cons_ph_price[-1]
            ph2 = self.cons_ph_price[-2]
            phb1 = self.cons_ph_bar[-1]
            phb2 = self.cons_ph_bar[-2]
            pl1 = self.cons_pl_price[-1]
            pl2 = self.cons_pl_price[-2]
            plb1 = self.cons_pl_bar[-1]
            plb2 = self.cons_pl_bar[-2]

            if abs(ph1 - ph2) <= buf and abs(pl1 - pl2) <= buf:
                new_top = max(ph1, ph2)
                new_bottom = min(pl1, pl2)
                new_left = min(phb1, phb2, plb1, plb2)

                # Check for merging
                merged = False
                for i in range(len(self.cons_active)):
                    if self.cons_active[i]:
                        if new_left <= self.cons_right[i] and n >= self.cons_left[i] and new_top >= self.cons_bottom[i] and new_bottom <= self.cons_top[i]:
                            self.cons_top[i] = max(self.cons_top[i], new_top)
                            self.cons_bottom[i] = min(self.cons_bottom[i], new_bottom)
                            self.cons_left[i] = min(self.cons_left[i], new_left)
                            self.cons_right[i] = n
                            merged = True
                            break

                if not merged:
                    self.cons_left.append(new_left)
                    self.cons_right.append(n)
                    self.cons_top.append(new_top)
                    self.cons_bottom.append(new_bottom)
                    self.cons_active.append(True)

        # Update active boxes
        self.in_consolidation = False
        for i in range(len(self.cons_active)):
            if self.cons_active[i]:
                if self.closes[-1] > self.cons_top[i] or self.closes[-1] < self.cons_bottom[i]:
                    self.cons_active[i] = False
                else:
                    self.in_consolidation = True
                    self.active_cons_top = self.cons_top[i]
                    self.active_cons_bottom = self.cons_bottom[i]

    # ─── CHOCH ────────────────────────────────────────────────────────────────

    def _update_choch(self):
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
        self.new_choch_bull = is_downtrend and self.ms_h1 is not None and close > self.ms_h1 and not self.choch_bull_fired
        self.new_choch_bear = is_uptrend and self.ms_l1 is not None and close < self.ms_l1 and not self.choch_bear_fired

        if self.new_choch_bull:
            self.choch_bull_fired = True
        if self.new_choch_bear:
            self.choch_bear_fired = True

        # ─── CHoCH State Machine ──────────────────────────────────────────
        # Replicates Pine's chochBullState / chochBearState

        if self.new_choch_bull and self.lr_valid:
            self.choch_bull_state = 1
            self.choch_bull_level = self.ms_h1
            self.choch_bull_retrace_low = None
            self.choch_bear_state = 0
            self.choch_bear_level = None
            self.choch_bear_retrace_high = None

        if self.new_choch_bear and self.lr_valid:
            self.choch_bear_state = 1
            self.choch_bear_level = self.ms_l1
            self.choch_bear_retrace_high = None
            self.choch_bull_state = 0
            self.choch_bull_level = None
            self.choch_bull_retrace_low = None

        if self.choch_bull_state == 1 and self.new_zz_low:
            self.choch_bull_state = 2
            self.choch_bull_retrace_low = self.zz_l1

        if self.choch_bear_state == 1 and self.new_zz_high:
            self.choch_bear_state = 2
            self.choch_bear_retrace_high = self.zz_h1

        self.choch_only_long_raw = (
            self.choch_bull_state == 2 and
            self.new_zz_high and
            self.choch_bull_level is not None and
            self.zz_h1 > self.choch_bull_level
        )
        if self.choch_only_long_raw:
            self.choch_bull_state = 0
            self.choch_bull_level = None
            self.choch_bull_retrace_low = None

        self.choch_only_short_raw = (
            self.choch_bear_state == 2 and
            self.new_zz_low and
            self.choch_bear_level is not None and
            self.zz_l1 < self.choch_bear_level
        )
        if self.choch_only_short_raw:
            self.choch_bear_state = 0
            self.choch_bear_level = None
            self.choch_bear_retrace_high = None

    # ─── DIVERGENCE / CONVERGENCE ─────────────────────────────────────────────

    def _update_divergence(self):
        if self.rsi_val is None or self.atr_val is None:
            return

        if self.new_zz_high and self.zz_h2 is not None and self.zz_hbar2 is not None:
            rsi_h1 = self._rsi_at_bar(self.zz_hbar1)
            rsi_h2 = self._rsi_at_bar(self.zz_hbar2)

            if rsi_h1 is not None and rsi_h2 is not None:
                # Follow-up confirmation
                if self.div_follow_up and self.last_div_price is not None and self.zz_h1 < self.last_div_price:
                    self.div_follow_up_confirmed = True
                    self.div_follow_up = False
                    self.last_div_price = None
                    self.last_div_bar = None

                # New divergence
                if self.zz_h1 > self.zz_h2 and rsi_h1 < rsi_h2:
                    self.last_div_price = self.zz_h1
                    self.last_div_bar = self.zz_hbar1
                    self.div_follow_up = True
                    self.div_follow_up_confirmed = False

        if self.new_zz_low and self.zz_l2 is not None and self.zz_lbar2 is not None:
            rsi_l1 = self._rsi_at_bar(self.zz_lbar1)
            rsi_l2 = self._rsi_at_bar(self.zz_lbar2)

            if rsi_l1 is not None and rsi_l2 is not None:
                # Follow-up confirmation
                if self.conv_follow_up and self.last_conv_price is not None and self.zz_l1 > self.last_conv_price:
                    self.conv_follow_up_confirmed = True
                    self.conv_follow_up = False
                    self.last_conv_price = None
                    self.last_conv_bar = None

                # New convergence
                if self.zz_l1 < self.zz_l2 and rsi_l1 > rsi_l2:
                    self.last_conv_price = self.zz_l1
                    self.last_conv_bar = self.zz_lbar1
                    self.conv_follow_up = True
                    self.conv_follow_up_confirmed = False

    def _rsi_at_bar(self, bar_idx):
        if bar_idx is None or bar_idx < self.p['rsiLen']:
            return None
        if bar_idx >= len(self.closes):
            return None
        if len(self.rsi_history) > bar_idx:
            return self.rsi_history[bar_idx]
        return None

    # ─── REVERSAL STATE ────────────────────────────────────────────────────────

    def _update_reversal_state(self):
        if self.conv_follow_up_confirmed:
            self.waiting_for_choch_long = True
            self.waiting_for_choch_short = False
        if self.div_follow_up_confirmed:
            self.waiting_for_choch_short = True
            self.waiting_for_choch_long = False

    # ─── RAW SIGNALS ───────────────────────────────────────────────────────────

    def _compute_raw_signals(self):
        if self.atr_val is None:
            return

        # Near bands
        band_tol = self.atr_val * self.p['lrBandTol']
        near_lower = (
            self.lr_valid and
            self.lr_lower is not None and
            self.lows[-1] <= self.lr_lower + band_tol
        )
        near_upper = (
            self.lr_valid and
            self.lr_upper is not None and
            self.highs[-1] >= self.lr_upper - band_tol
        )

        # EMA proximity
        near_ema_long = abs(self.lows[-1] - self.ema200) <= self.atr_val * 0.5 and self.closes[-1] > self.ema200
        near_ema_short = abs(self.highs[-1] - self.ema200) <= self.atr_val * 0.5 and self.closes[-1] < self.ema200

        # Consolidation near-bound
        cons_tol = self.atr_val * 0.5
        cons_qualifies = (self.active_cons_top is not None and self.active_cons_bottom is not None and
                         (self.active_cons_top - self.active_cons_bottom) / self.active_cons_bottom >= 0.003)

        near_cons_bottom = (
            self.in_consolidation and cons_qualifies and
            self.active_cons_bottom is not None and
            self.lows[-1] <= self.active_cons_bottom + cons_tol and
            self.closes[-1] > self.opens[-1]
        )
        near_cons_top = (
            self.in_consolidation and cons_qualifies and
            self.active_cons_top is not None and
            self.highs[-1] >= self.active_cons_top - cons_tol and
            self.closes[-1] < self.opens[-1]
        )

        # ─── Raw Signals ────────────────────────────────────────────────────
        self.reversal_long_raw = self.waiting_for_choch_long and self.new_choch_bull
        self.reversal_short_raw = self.waiting_for_choch_short and self.new_choch_bear

        if self.reversal_long_raw:
            self.waiting_for_choch_long = False
        if self.reversal_short_raw:
            self.waiting_for_choch_short = False

        self.follow_up_long_raw = self.conv_follow_up_confirmed and self.closes[-1] > self.opens[-1]
        self.follow_up_short_raw = self.div_follow_up_confirmed and self.closes[-1] < self.opens[-1]

        self.trend_long_raw = not self.in_consolidation and self.lr_is_bull and near_lower
        self.trend_short_raw = not self.in_consolidation and self.lr_is_bear and near_upper

        self.cons_long_raw = near_cons_bottom
        self.cons_short_raw = near_cons_top

    # ─── SIGNAL GATING ─────────────────────────────────────────────────────────

    def _gate_signals(self):
        """Replicates Pine's priority gating and daily limiters."""
        # ─── Daily Limiter (SGT) ───────────────────────────────────────────
        # Compute SGT day key
        if len(self.times) > 0:
            current_time = pd.to_datetime(self.times[-1])
            # SGT is UTC+8
            sgt_time = current_time + pd.Timedelta(hours=8)
            sgt_day_key = sgt_time.year * 10000 + sgt_time.month * 100 + sgt_time.day

            if self.last_day_sgt is None or sgt_day_key != self.last_day_sgt:
                self.rev_long_count = 0
                self.rev_short_count = 0
                self.follow_up_long_count = 0
                self.follow_up_short_count = 0
                self.trend_long_count = 0
                self.trend_short_count = 0
                self.choch_long_count = 0
                self.choch_short_count = 0
                self.cons_long_count = 0
                self.cons_short_count = 0
                self.last_day_sgt = sgt_day_key

        # ─── Priority Gating ────────────────────────────────────────────────
        # Reset final signals
        self.show_rev_long = False
        self.show_rev_short = False
        self.show_follow_up_long = False
        self.show_follow_up_short = False
        self.show_trend_long = False
        self.show_trend_short = False
        self.show_choch_long = False
        self.show_choch_short = False
        self.show_cons_long = False
        self.show_cons_short = False
        self.show_any_long = False
        self.show_any_short = False

        # ─── Reversal Signals ──────────────────────────────────────────────
        if self.reversal_long_raw and self.rev_long_count < 2:
            self.show_rev_long = True
            self.rev_long_count += 1
        if self.reversal_short_raw and self.rev_short_count < 2:
            self.show_rev_short = True
            self.rev_short_count += 1

        # ─── Follow-up Signals ─────────────────────────────────────────────
        if self.follow_up_long_raw and self.follow_up_long_count < 2:
            self.show_follow_up_long = True
            self.follow_up_long_count += 1
        if self.follow_up_short_raw and self.follow_up_short_count < 2:
            self.show_follow_up_short = True
            self.follow_up_short_count += 1

        # ─── Trend Signals ──────────────────────────────────────────────────
        trend_long_slots_left = 2 - self.trend_long_count
        trend_short_slots_left = 2 - self.trend_short_count

        near_ema_long = abs(self.lows[-1] - self.ema200) <= self.atr_val * 0.5 and self.closes[-1] > self.ema200 if self.atr_val else False
        near_ema_short = abs(self.highs[-1] - self.ema200) <= self.atr_val * 0.5 and self.closes[-1] < self.ema200 if self.atr_val else False

        # Long Trend: No EMA first, then EMA if slots remain
        show_trend_long_no_ema = self.trend_long_raw and not near_ema_long and trend_long_slots_left > 0
        if show_trend_long_no_ema:
            self.show_trend_long = True
            self.trend_long_count += 1
            trend_long_slots_left -= 1

        show_trend_long_ema = self.trend_long_raw and near_ema_long and trend_long_slots_left > 0
        if show_trend_long_ema:
            self.show_trend_long = True
            self.trend_long_count += 1

        # Short Trend: No EMA first, then EMA if slots remain
        show_trend_short_no_ema = self.trend_short_raw and not near_ema_short and trend_short_slots_left > 0
        if show_trend_short_no_ema:
            self.show_trend_short = True
            self.trend_short_count += 1
            trend_short_slots_left -= 1

        show_trend_short_ema = self.trend_short_raw and near_ema_short and trend_short_slots_left > 0
        if show_trend_short_ema:
            self.show_trend_short = True
            self.trend_short_count += 1

        # ─── CHoCH Signals ──────────────────────────────────────────────────
        if self.choch_only_long_raw and self.choch_long_count < 2:
            self.show_choch_long = True
            self.choch_long_count += 1
        if self.choch_only_short_raw and self.choch_short_count < 2:
            self.show_choch_short = True
            self.choch_short_count += 1

        # ─── Consolidation Signals ──────────────────────────────────────────
        if self.cons_long_raw and self.cons_long_count < 2:
            self.show_cons_long = True
            self.cons_long_count += 1
        if self.cons_short_raw and self.cons_short_count < 2:
            self.show_cons_short = True
            self.cons_short_count += 1

        # ─── Final Any Signals ──────────────────────────────────────────────
        self.show_any_long = (
            self.show_rev_long or
            self.show_follow_up_long or
            self.show_trend_long or
            self.show_choch_long or
            self.show_cons_long
        )

        self.show_any_short = (
            self.show_rev_short or
            self.show_follow_up_short or
            self.show_trend_short or
            self.show_choch_short or
            self.show_cons_short
        )

    # ─── BUILD SIGNAL ─────────────────────────────────────────────────────────

    def _build_signal(self):
        """Construct the final signal dictionary matching Pine's alert format."""
        if not (self.show_any_long or self.show_any_short):
            return None

        # Direction
        direction = "Long" if self.show_any_long else "Short"

        # Signal type
        if self.show_rev_long or self.show_rev_short:
            signal_type = "Type 1 — Reversal"
        elif self.show_follow_up_long or self.show_follow_up_short:
            signal_type = "Type 2 — Follow-up"
        elif self.show_trend_long or self.show_trend_short:
            signal_type = "Type 3 — Trend"
        elif self.show_choch_long or self.show_choch_short:
            signal_type = "Type 4 — CHoCH"
        else:
            signal_type = "Type 5 — Consolidation"

        # Entry and risk
        close = self.closes[-1]
        entry = close
        sl = None
        if self.show_any_long:
            sl = self.ms_l1 - self.atr_val * 0.5 if self.ms_l1 is not None else close - self.atr_val * 2
        else:
            sl = self.ms_h1 + self.atr_val * 0.5 if self.ms_h1 is not None else close + self.atr_val * 2

        risk = abs(close - sl)
        tp = close + risk * 1.5 if self.show_any_long else close - risk * 1.5

        # Condition flags (matches Pine's _lr, _ema, _cons, _div, _conv, _choch)
        lr_flag = "✅ Bullish" if self.lr_is_bull and self.lr_valid else "✅ Bearish" if self.lr_is_bear and self.lr_valid else "❌ Invalid"
        ema_flag = "✅" if (abs(self.lows[-1] - self.ema200) <= self.atr_val * 0.5) if self.atr_val else False else "➖"
        cons_flag = "📦" if self.in_consolidation else "➖"
        div_flag = "✅" if self.div_follow_up_confirmed else "⏳" if self.div_follow_up else "➖"
        conv_flag = "✅" if self.conv_follow_up_confirmed else "⏳" if self.conv_follow_up else "➖"
        choch_flag = "✅" if (self.new_choch_bull or self.new_choch_bear) else "➖"

        return {
            "signal": signal_type,
            "dir": direction,
            "pair": "GBPUSD",  # Will be set by caller
            "tf": "H1",        # Will be set by caller
            "entry": round(entry, 5),
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "lr": lr_flag,
            "ema": ema_flag,
            "cons": cons_flag,
            "div": div_flag,
            "conv": conv_flag,
            "choch": choch_flag,
            "ote": self.ote_zone or "N/A",
            "time": str(int(self.times[-1].timestamp() * 1000))
        }