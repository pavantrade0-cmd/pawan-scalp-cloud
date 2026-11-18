import pandas as pd
import numpy as np

class InstitutionalLevelEngine:
    def __init__(self, zone_buffer=15.0, min_sl=10.0, max_sl=20.0):
        self.zone_buffer = zone_buffer
        self.min_sl = min_sl
        self.max_sl = max_sl

    def _calculate_indicators(self, df):
        df = df.copy()
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df['atr'] = true_range.rolling(14).mean()
        
        df['body'] = np.abs(df['close'] - df['open'])
        df['avg_body'] = df['body'].rolling(10).mean()
        df['avg_vol'] = df['volume'].rolling(10).mean()
        return df

    def _find_key_levels(self, df):
        inner_swh, inner_swl = [], []
        outer_swh, outer_swl = [], []
        equal_highs, equal_lows = [], []

        # Inner (Small) Swing Highs/Lows (3-candle fractal)
        for i in range(1, len(df) - 1):
            h = float(df['high'].iloc[i])
            l = float(df['low'].iloc[i])
            if h > df['high'].iloc[i-1] and h > df['high'].iloc[i+1]:
                inner_swh.append(h)
            if l < df['low'].iloc[i-1] and l < df['low'].iloc[i+1]:
                inner_swl.append(l)

        # Outer (Major/Long) Swing Highs/Lows (5-candle fractal)
        for i in range(2, len(df) - 2):
            h = float(df['high'].iloc[i])
            l = float(df['low'].iloc[i])
            if (h > df['high'].iloc[i-1] and h > df['high'].iloc[i-2] and
                h > df['high'].iloc[i+1] and h > df['high'].iloc[i+2]):
                outer_swh.append(h)
            if (l < df['low'].iloc[i-1] and l < df['low'].iloc[i-2] and
                l < df['low'].iloc[i+1] and l < df['low'].iloc[i+2]):
                outer_swl.append(l)

        # Equal Highs & Equal Lows (EQH / EQL)
        recent_highs = outer_swh[-8:]
        for idx1 in range(len(recent_highs)):
            for idx2 in range(idx1 + 1, len(recent_highs)):
                h1, h2 = recent_highs[idx1], recent_highs[idx2]
                if abs(h1 - h2) <= max(5.0, h1 * 0.001):
                    equal_highs.append((h1 + h2) / 2.0)

        recent_lows = outer_swl[-8:]
        for idx1 in range(len(recent_lows)):
            for idx2 in range(idx1 + 1, len(recent_lows)):
                l1, l2 = recent_lows[idx1], recent_lows[idx2]
                if abs(l1 - l2) <= max(5.0, l1 * 0.001):
                    equal_lows.append((l1 + l2) / 2.0)

        all_highs = list(set(inner_swh[-4:] + outer_swh[-5:] + equal_highs))
        all_lows = list(set(inner_swl[-4:] + outer_swl[-5:] + equal_lows))
        return all_highs, all_lows

    def evaluate_spot_signal(self, df, pdh=None, pdl=None):
        if len(df) < 30:
            return None

        df = self._calculate_indicators(df)
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]

        curr_open = float(curr['open'])
        curr_high = float(curr['high'])
        curr_low = float(curr['low'])
        curr_close = float(curr['close'])

        prev_open = float(prev['open'])
        prev_high = float(prev['high'])
        prev_low = float(prev['low'])
        prev_close = float(prev['close'])
        prev2_close = float(prev2['close'])

        ema9 = float(curr['ema9'])
        ema21 = float(curr['ema21'])
        atr = float(curr['atr']) if not np.isnan(curr['atr']) else 10.0
        body = float(curr['body'])
        avg_body = float(curr['avg_body']) if not np.isnan(curr['avg_body']) else body
        curr_vol = float(curr['volume'])
        avg_vol = float(curr['avg_vol']) if not np.isnan(curr['avg_vol']) else curr_vol

        # Skip dead/choppy candles
        if body < (atr * 0.2):
            return None

        high_levels, low_levels = self._find_key_levels(df.iloc[:-2])
        if pdh:
            high_levels.append(float(pdh))
        if pdl:
            low_levels.append(float(pdl))

        # =========================================================
        # 1. BULLISH SETUPS (CE / BTC LONG)
        # =========================================================
        for lvl in high_levels:
            buf = max(self.zone_buffer, lvl * 0.0006)
            # A. Breakout + Retrace Confirmation (Broke above earlier, retested level, bounced green)
            if prev2_close <= lvl and prev_close > lvl and curr_low <= (lvl + buf) and curr_close > lvl and curr_close > curr_open:
                if curr_vol >= (avg_vol * 0.9):
                    return {"direction": "CE", "strategy": "Breakout Retest"}

            # B. High-Volume Direct Breakout
            if prev_close <= lvl and curr_close > lvl and curr_close > curr_open:
                if body >= (avg_body * 1.1) and curr_vol >= (avg_vol * 1.2) and ema9 >= ema21:
                    return {"direction": "CE", "strategy": "Volume Breakout"}

        for lvl in low_levels:
            buf = max(self.zone_buffer, lvl * 0.0006)
            # C. Support / SWL / PDL / EQL Rejection or Liquidity Sweep
            if curr_low <= (lvl + buf) and curr_close > lvl and curr_close > curr_open:
                lower_wick = min(curr_open, curr_close) - curr_low
                if lower_wick >= (body * 0.5) and curr_vol >= (avg_vol * 0.85):
                    return {"direction": "CE", "strategy": "Level Rejection"}

        # =========================================================
        # 2. BEARISH SETUPS (PE / BTC SHORT)
        # =========================================================
        for lvl in low_levels:
            buf = max(self.zone_buffer, lvl * 0.0006)
            # A. Breakdown + Retrace Confirmation (Broke below earlier, retested level, rejected red)
            if prev2_close >= lvl and prev_close < lvl and curr_high >= (lvl - buf) and curr_close < lvl and curr_close < curr_open:
                if curr_vol >= (avg_vol * 0.9):
                    return {"direction": "PE", "strategy": "Breakdown Retest"}

            # B. High-Volume Direct Breakdown
            if prev_close >= lvl and curr_close < lvl and curr_close < curr_open:
                if body >= (avg_body * 1.1) and curr_vol >= (avg_vol * 1.2) and ema9 <= ema21:
                    return {"direction": "PE", "strategy": "Volume Breakdown"}

        for lvl in high_levels:
            buf = max(self.zone_buffer, lvl * 0.0006)
            # C. Resistance / SWH / PDH / EQH Rejection or Liquidity Sweep
            if curr_high >= (lvl - buf) and curr_close < lvl and curr_close < curr_open:
                upper_wick = curr_high - max(curr_open, curr_close)
                if upper_wick >= (body * 0.5) and curr_vol >= (avg_vol * 0.85):
                    return {"direction": "PE", "strategy": "Level Rejection"}

        return None

    def validate_option_entry(self, opt_df, curr_ltp):
        if len(opt_df) < 5:
            return None

        recent_low = float(opt_df['low'].iloc[-5:].min())
        entry = float(curr_ltp)

        sl = recent_low - 1.0
        sl_pts = entry - sl

        if sl_pts < self.min_sl:
            sl = entry - self.min_sl
            sl_pts = self.min_sl
        elif sl_pts > self.max_sl:
            sl = entry - self.max_sl
            sl_pts = self.max_sl

        return {
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "sl_pts": int(round(sl_pts)),
            "tp1": round(entry + 10.0, 2),
            "tp2": round(entry + 20.0, 2),
            "tp3": round(entry + 30.0, 2)
                      }
        
