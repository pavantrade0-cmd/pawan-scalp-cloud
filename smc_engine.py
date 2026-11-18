import pandas as pd
import numpy as np

class InstitutionalLevelEngine:
    def __init__(self, zone_buffer=12.0, min_sl=10.0, max_sl=20.0):
        self.zone_buffer = zone_buffer
        self.min_sl = min_sl
        self.max_sl = max_sl

    def detect_levels(self, df_5m, pdh, pdl):
        levels = []
        if pdh:
            levels.append({"name": "PDH", "price": pdh, "type": "RESISTANCE", "priority": 1})
        if pdl:
            levels.append({"name": "PDL", "price": pdl, "type": "SUPPORT", "priority": 1})

        # 1. Swing High (SWH) & Swing Low (SWL) — 5-candle fractal on each side
        highs = df_5m["high"].values
        lows = df_5m["low"].values
        n = len(df_5m)
        swh_candidates = []
        swl_candidates = []

        for i in range(5, n - 5):
            if highs[i] == max(highs[i - 5 : i + 6]):
                swh_candidates.append(float(highs[i]))
            if lows[i] == min(lows[i - 5 : i + 6]):
                swl_candidates.append(float(lows[i]))

        if swh_candidates:
            levels.append({"name": "SWH", "price": swh_candidates[-1], "type": "RESISTANCE", "priority": 2})
        if swl_candidates:
            levels.append({"name": "SWL", "price": swl_candidates[-1], "type": "SUPPORT", "priority": 2})

        # 2. Strong Support & Resistance (Multi-touch clusters >= 2 rejections within zone_buffer)
        for p in swh_candidates:
            touches = sum(1 for x in swh_candidates if abs(x - p) <= self.zone_buffer)
            if touches >= 2 and not any(abs(l["price"] - p) <= self.zone_buffer for l in levels):
                levels.append({"name": "Strong Resistance", "price": p, "type": "RESISTANCE", "priority": 3})

        for p in swl_candidates:
            touches = sum(1 for x in swl_candidates if abs(x - p) <= self.zone_buffer)
            if touches >= 2 and not any(abs(l["price"] - p) <= self.zone_buffer for l in levels):
                levels.append({"name": "Strong Support", "price": p, "type": "SUPPORT", "priority": 3})

        return levels

    def _body_ratio(self, row):
        total_range = row["high"] - row["low"]
        if total_range <= 0:
            return 0.0
        return abs(row["close"] - row["open"]) / total_range

    def evaluate_spot_signal(self, df_5m, pdh, pdl):
        if len(df_5m) < 25:
            return None

        levels = self.detect_levels(df_5m.iloc[:-1], pdh, pdl)
        curr = df_5m.iloc[-1]
        prev = df_5m.iloc[-2]
        buildup_window = df_5m.iloc[-5:-1]  # Prior 3-4 candles before breakout/breakdown

        body_pct = self._body_ratio(curr)
        is_green = curr["close"] > curr["open"]
        is_red = curr["close"] < curr["open"]

        for lvl in levels:
            price = lvl["price"]
            name = lvl["name"]
            ltype = lvl["type"]

            # --- 1. SUPPORT REVERSAL (Sweep or Rejection Bounce -> BUY CE) ---
            if ltype == "SUPPORT":
                swept = (curr["low"] <= price + 3.0) or (prev["low"] <= price + 3.0)
                if swept and is_green and curr["close"] > price and body_pct >= 0.55:
                    return {
                        "direction": "CE",
                        "strategy": f"Support Reversal ({name})",
                        "level_price": price
                    }

            # --- 2. RESISTANCE REVERSAL (Sweep or Rejection Drop -> BUY PE) ---
            if ltype == "RESISTANCE":
                swept = (curr["high"] >= price - 3.0) or (prev["high"] >= price - 3.0)
                if swept and is_red and curr["close"] < price and body_pct >= 0.55:
                    return {
                        "direction": "PE",
                        "strategy": f"Resistance Reversal ({name})",
                        "level_price": price
                    }

            # --- 3. RESISTANCE BREAKOUT (3+ Candles Buildup + Strong Body Close Above -> BUY CE) ---
            if ltype == "RESISTANCE":
                held_below = all(buildup_window["close"] <= price + 2.0) and (buildup_window["high"].max() >= price - 15.0)
                if held_below and is_green and prev["close"] <= price and curr["close"] > price and body_pct >= 0.62:
                    return {
                        "direction": "CE",
                        "strategy": f"Resistance Breakout ({name})",
                        "level_price": price
                    }

            # --- 4. SUPPORT BREAKDOWN (3+ Candles Buildup + Strong Body Close Below -> BUY PE) ---
            if ltype == "SUPPORT":
                held_above = all(buildup_window["close"] >= price - 2.0) and (buildup_window["low"].min() <= price + 15.0)
                if held_above and is_red and prev["close"] >= price and curr["close"] < price and body_pct >= 0.62:
                    return {
                        "direction": "PE",
                        "strategy": f"Support Breakdown ({name})",
                        "level_price": price
                    }

        return None

    def validate_option_entry(self, opt_df_5m, current_ltp):
        if len(opt_df_5m) < 12:
            return None

        curr = opt_df_5m.iloc[-1]
        avg_vol = opt_df_5m["volume"].iloc[-11:-1].mean()

        # Option volume confirmation (>1.5x average volume if volume data available)
        if avg_vol > 0 and curr["volume"] < (1.5 * avg_vol):
            return None

        entry = round(current_ltp, 2)
        raw_sl_points = entry - float(curr["low"])

        # Reject trade if candle risk exceeds 20 pts max
        if raw_sl_points > self.max_sl:
            return None

        # Enforce 10 to 20 pts SL window
        sl_points = round(max(self.min_sl, min(self.max_sl, raw_sl_points)), 2)
        sl_price = round(entry - sl_points, 2)
        tp1_price = round(entry + (sl_points * 1.5), 2)
        tp2_price = round(entry + (sl_points * 2.5), 2)

        return {
            "entry": entry,
            "sl": sl_price,
            "sl_pts": sl_points,
            "tp1": tp1_price,
            "tp2": tp2_price
        }
        
