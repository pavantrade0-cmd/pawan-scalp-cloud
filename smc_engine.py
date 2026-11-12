# engine/smc_engine.py
import pandas as pd

class SMCEngine:
    def __init__(self, ema_fast: int = 20, ema_slow: int = 50):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.last_traded_bar = None

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculates 20 EMA and 50 EMA on any 5M DataFrame (Spot, CE, or PE)."""
        if df is None or df.empty:
            return df
        df = df.copy()
        df["ema_fast"] = df["close"].ewm(span=self.ema_fast, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.ema_slow, adjust=False).mean()
        return df

    def _check_option_bounce(self, opt_df: pd.DataFrame) -> dict | None:
        """Checks 20/50 EMA bullish pullback bounce on the last closed 5M option candle."""
        if opt_df is None or len(opt_df) < 55:
            return None

        c_prev = opt_df.iloc[-2]   # Last closed 5M candle
        c_before = opt_df.iloc[-3]

        ema20 = float(c_prev["ema_fast"])
        ema50 = float(c_prev["ema_slow"])
        c_open = float(c_prev["open"])
        c_high = float(c_prev["high"])
        c_low = float(c_prev["low"])
        c_close = float(c_prev["close"])

        # 1. Option trend must be bullish (20 EMA > 50 EMA)
        if ema20 <= ema50:
            return None

        # 2. Pullback touch to 20 EMA zone & Bullish close above 20 EMA
        touched_20ema = (c_low <= ema20 * 1.005) or (float(c_before["low"]) <= float(c_before["ema_fast"]) * 1.005)
        bullish_close = (c_close > c_open) and (c_close > ema20)

        if not (touched_20ema and bullish_close):
            return None

        # 3. Entry, SL, TP1 (1:1), TP2 (1:2) directly on Option Premium
        entry = round(c_close, 2)
        raw_sl = min(c_low, float(c_before["low"])) - 1.5
        risk = entry - raw_sl

        # Enforce clean option buying risk boundaries (min 6 pts, max 25 pts)
        if risk < 6.0:
            risk = 6.0
            raw_sl = entry - risk
        elif risk > 25.0:
            risk = 25.0
            raw_sl = entry - risk

        sl = round(raw_sl, 2)
        tp1 = round(entry + risk, 2)
        tp2 = round(entry + (risk * 2.0), 2)

        return {
            "bar_time": opt_df.index[-2],
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2
        }

    def scan_option_buying_setup(
        self,
        spot_df: pd.DataFrame,
        ce_df: pd.DataFrame,
        pe_df: pd.DataFrame,
        ce_info: dict,
        pe_info: dict
    ) -> dict | None:
        """Dual-Confirmation Scanner: Index Trend + Option Premium 20 EMA Bounce."""
        if spot_df is None or len(spot_df) < 55:
            return None

        spot_prev = spot_df.iloc[-2]
        spot_ema20 = float(spot_prev["ema_fast"])
        spot_ema50 = float(spot_prev["ema_slow"])
        spot_close = float(spot_prev["close"])

        # CASE 1: NIFTY INDEX BULLISH -> CHECK CALL (CE) CHART ONLY
        if spot_ema20 > spot_ema50 and spot_close > spot_ema20:
            ce_signal = self._check_option_bounce(ce_df)
            if ce_signal and ce_signal["bar_time"] != self.last_traded_bar:
                self.last_traded_bar = ce_signal["bar_time"]
                return {
                    "chart_type": "CE",
                    "asset": ce_info["symbol"],
                    "spot_price": spot_close,
                    "direction": "BUY_CE",
                    "entry": ce_signal["entry"],
                    "sl": ce_signal["sl"],
                    "tp1": ce_signal["tp1"],
                    "tp2": ce_signal["tp2"]
                }

        # CASE 2: NIFTY INDEX BEARISH -> CHECK PUT (PE) CHART ONLY
        elif spot_ema20 < spot_ema50 and spot_close < spot_ema20:
            pe_signal = self._check_option_bounce(pe_df)
            if pe_signal and pe_signal["bar_time"] != self.last_traded_bar:
                self.last_traded_bar = pe_signal["bar_time"]
                return {
                    "chart_type": "PE",
                    "asset": pe_info["symbol"],
                    "spot_price": spot_close,
                    "direction": "BUY_PE",
                    "entry": pe_signal["entry"],
                    "sl": pe_signal["sl"],
                    "tp1": pe_signal["tp1"],
                    "tp2": pe_signal["tp2"]
                }

        return None
