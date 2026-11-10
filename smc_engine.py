import pandas as pd
import numpy as np

class SMCEngine:
    def __init__(self):
        pass

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates EMA 20, EMA 50, and RSI 14 according to Scalping Pulse settings.
        """
        if len(df) < 50:
            return df

        # EMA 20 & EMA 50
        df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()

        # RSI 14
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

        rs = avg_gain / (avg_loss + 1e-9)
        df['rsi'] = 100 - (100 / (1 + rs))

        return df

    def scan_for_setups(self, df: pd.DataFrame) -> dict:
        """
        Original Pure Scalping Pulse:
        - Timeframe: 5m
        - EMA 20 > EMA 50 for BUY, EMA 20 < EMA 50 for SELL
        - Pullback: Candle wicks touch/pierce EMA 20
        - Confirmation: Candle closes in trend direction
        - Momentum: RSI >= 50.0 for BUY, RSI <= 50.0 for SELL
        - Dual Targets: 1:1 Partial and 1:2 Full Target
        """
        default_res = {
            "signal": "WAIT",
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "target_1": 0.0,
            "target_2": 0.0,
            "target_partial": 0.0,
            "points": 0.0,
            "reason": "Scanning 5m EMA 20/50 pullback...",
            "candle_time": None
        }

        if df.empty or len(df) < 55:
            return default_res

        # Indicators Calculation
        df = self.calculate_indicators(df)

        # Trigger Candle (Previous Closed 5m Candle: index -2)
        c = df.iloc[-2]
        c_prev = df.iloc[-3]
        candle_time = df.index[-2]

        ema20 = float(c['ema_20'])
        ema50 = float(c['ema_50'])
        rsi = float(c['rsi']) if not np.isnan(c['rsi']) else 50.0

        c_open = float(c['open'])
        c_high = float(c['high'])
        c_low = float(c['low'])
        c_close = float(c['close'])

        # Asset detection for risk sizing
        is_crypto = c_close > 35000.0
        min_gap = 2.0
        min_risk = 10.0
        max_risk = 850.0 if is_crypto else 75.0

        ema_separation = abs(ema20 - ema50)

        # ---------------- 1. BUY (CE) SETUP ----------------
        if (ema20 > ema50 and ema_separation >= min_gap):
            if rsi >= 50.0:
                wick_touched = c_low <= (ema20 * 1.0008)
                closed_above = c_close > ema20
                is_green = c_close >= c_open

                if wick_touched and closed_above and is_green:
                    entry = round(c_close, 2)
                    recent_low = min(c_low, float(c_prev['low']))
                    sl = round(recent_low - 1.0, 2)
                    
                    risk_pts = round(entry - sl, 2)
                    if min_risk <= risk_pts <= max_risk:
                        t1_partial = round(entry + (risk_pts * 1.0), 2)  # 1:1 Partial Level
                        t2_full = round(entry + (risk_pts * 2.0), 2)     # 1:2 Full Level
                        return {
                            "signal": "BUY CE",
                            "entry_price": entry,
                            "stop_loss": sl,
                            "target_1": t2_full,    # UI & Alerts draw 1:2 target directly
                            "target_2": t2_full,
                            "target_partial": t1_partial,
                            "points": risk_pts,
                            "reason": f"20 EMA Pullback + RSI {rsi:.1f} (&gt;50)",
                            "candle_time": str(candle_time)
                        }

        # ---------------- 2. SELL (PE) SETUP ----------------
        if (ema20 < ema50 and ema_separation >= min_gap):
            if rsi <= 50.0:
                wick_touched = c_high >= (ema20 * 0.9992)
                closed_below = c_close < ema20
                is_red = c_close <= c_open

                if wick_touched and closed_below and is_red:
                    entry = round(c_close, 2)
                    recent_high = max(c_high, float(c_prev['high']))
                    sl = round(recent_high + 1.0, 2)
                    
                    risk_pts = round(sl - entry, 2)
                    if min_risk <= risk_pts <= max_risk:
                        t1_partial = round(entry - (risk_pts * 1.0), 2)  # 1:1 Partial Level
                        t2_full = round(entry - (risk_pts * 2.0), 2)     # 1:2 Full Level
                        return {
                            "signal": "BUY PE",
                            "entry_price": entry,
                            "stop_loss": sl,
                            "target_1": t2_full,    # UI & Alerts draw 1:2 target directly
                            "target_2": t2_full,
                            "target_partial": t1_partial,
                            "points": risk_pts,
                            "reason": f"20 EMA Pullback + RSI {rsi:.1f} (&lt;50)",
                            "candle_time": str(candle_time)
                        }

        return default_res
