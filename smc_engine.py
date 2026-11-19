import pandas as pd
import numpy as np

class InstitutionalLevelEngine:
    def __init__(self, zone_buffer=15.0, min_sl=10.0, max_sl=15.0):
        self.zone_buffer = zone_buffer
        self.min_sl = min_sl
        self.max_sl = max_sl

    def _calculate_indicators(self, df):
        df = df.copy()
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['body'] = np.abs(df['close'] - df['open'])
        df['range'] = (df['high'] - df['low']).replace(0, 0.01)
        df['avg_body'] = df['body'].rolling(10).mean()
        df['avg_vol'] = df['volume'].rolling(10).mean()
        return df

    def _find_key_levels(self, df):
        inner_swh, inner_swl = [], []
        outer_swh, outer_swl = [], []
        equal_highs, equal_lows = [], []

        for i in range(1, len(df) - 1):
            h = float(df['high'].iloc[i])
            l = float(df['low'].iloc[i])
            if h > df['high'].iloc[i-1] and h > df['high'].iloc[i+1]:
                inner_swh.append(h)
            if l < df['low'].iloc[i-1] and l < df['low'].iloc[i+1]:
                inner_swl.append(l)

        for i in range(2, len(df) - 2):
            h = float(df['high'].iloc[i])
            l = float(df['low'].iloc[i])
            if (h > df['high'].iloc[i-1] and h > df['high'].iloc[i-2] and
                h > df['high'].iloc[i+1] and h > df['high'].iloc[i+2]):
                outer_swh.append(h)
            if (l < df['low'].iloc[i-1] and l < df['low'].iloc[i-2] and
                l < df['low'].iloc[i+1] and l < df['low'].iloc[i+2]):
                outer_swl.append(l)

        recent_highs = outer_swh[-8:]
        for idx1 in range(len(recent_highs)):
            for idx2 in range(idx1 + 1, len(recent_highs)):
                h1, h2 = recent_highs[idx1], recent_highs[idx2]
                if abs(h1 - h2) <= max(5.0, h1 * 0.0012):
                    equal_highs.append((h1 + h2) / 2.0)

        recent_lows = outer_swl[-8:]
        for idx1 in range(len(recent_lows)):
            for idx2 in range(idx1 + 1, len(recent_lows)):
                l1, l2 = recent_lows[idx1], recent_lows[idx2]
                if abs(l1 - l2) <= max(5.0, l1 * 0.0012):
                    equal_lows.append((l1 + l2) / 2.0)

        all_highs = list(set(inner_swh[-4:] + outer_swh[-5:] + equal_highs))
        all_lows = list(set(inner_swl[-4:] + outer_swl[-5:] + equal_lows))
        return all_highs, all_lows

    def evaluate_spot_signal(self, df, pdh=None, pdl=None):
        if len(df) < 25:
            return None

        df = self._calculate_indicators(df)
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        recent_3 = df.iloc[-4:-1]

        curr_open = float(curr['open'])
        curr_high = float(curr['high'])
        curr_low = float(curr['low'])
        curr_close = float(curr['close'])
        prev_close = float(prev['close'])

        body = float(curr['body'])
        c_range = float(curr['range'])
        avg_body = float(curr['avg_body']) if not np.isnan(curr['avg_body']) else body
        curr_vol = float(curr['volume'])
        avg_vol = float(curr['avg_vol']) if not np.isnan(curr['avg_vol']) else curr_vol

        if body < (avg_body * 0.35):
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
            buf = max(self.zone_buffer, lvl * 0.0008)
            broke_earlier = (recent_3['close'] > lvl).any() and (recent_3['low'] <= lvl).any()
            if broke_earlier and curr_low <= (lvl + buf) and curr_close > lvl and curr_close > curr_open:
                return {"direction": "CE", "strategy": "Breakout Retest"}

            if prev_close <= lvl and curr_close > (lvl + buf * 0.2) and curr_close > curr_open:
                if body >= (avg_body * 0.95) and curr_vol >= (avg_vol * 0.95):
                    return {"direction": "CE", "strategy": "Volume Breakout"}

        for lvl in low_levels:
            buf = max(self.zone_buffer, lvl * 0.0008)
            if curr_low <= (lvl + buf) and curr_close > lvl and curr_close > curr_open:
                lower_wick = min(curr_open, curr_close) - curr_low
                if lower_wick >= (c_range * 0.35) and curr_vol >= (avg_vol * 0.8):
                    return {"direction": "CE", "strategy": "Level Rejection"}

        # =========================================================
        # 2. BEARISH SETUPS (PE / BTC SHORT)
        # =========================================================
        for lvl in low_levels:
            buf = max(self.zone_buffer, lvl * 0.0008)
            broke_earlier = (recent_3['close'] < lvl).any() and (recent_3['high'] >= lvl).any()
            if broke_earlier and curr_high >= (lvl - buf) and curr_close < lvl and curr_close < curr_open:
                return {"direction": "PE", "strategy": "Breakdown Retest"}

            if prev_close >= lvl and curr_close < (lvl - buf * 0.2) and curr_close < curr_open:
                if body >= (avg_body * 0.95) and curr_vol >= (avg_vol * 0.95):
                    return {"direction": "PE", "strategy": "Volume Breakdown"}

        for lvl in high_levels:
            buf = max(self.zone_buffer, lvl * 0.0008)
            if curr_high >= (lvl - buf) and curr_close < lvl and curr_close < curr_open:
                upper_wick = curr_high - max(curr_open, curr_close)
                if upper_wick >= (c_range * 0.35) and curr_vol >= (avg_vol * 0.8):
                    return {"direction": "PE", "strategy": "Level Rejection"}

        return None

    def validate_option_entry(self, opt_df, curr_ltp):
        if len(opt_df) < 5:
            return None

        recent_low = float(opt_df['low'].iloc[-5:].min())
        entry = float(curr_ltp)

        sl = recent_low - 1.0
        sl_pts = entry - sl

        # Strictly clamp dynamic swing SL between 10 and 15 points
        if sl_pts < self.min_sl:
            sl = entry - self.min_sl
            sl_pts = self.min_sl
        elif sl_pts > self.max_sl:
            sl = entry - self.max_sl
            sl_pts = self.max_sl

        sl_pts_rounded = round(sl_pts, 2)

        return {
            "entry": round(entry, 2),
            "sl": round(entry - sl_pts_rounded, 2),
            "sl_pts": int(round(sl_pts_rounded)),
            "tp1": round(entry + sl_pts_rounded, 2),        # 1:1 R:R
            "tp2": round(entry + (sl_pts_rounded * 2), 2),  # 1:2 R:R
            "tp3": round(entry + (sl_pts_rounded * 3), 2)   # 1:3 R:R
                }
        
