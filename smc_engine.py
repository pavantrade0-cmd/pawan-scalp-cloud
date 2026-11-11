import pandas as pd
from typing import Optional, Dict

class SMCEngine:
    def __init__(self, ema_fast: int = 20, ema_slow: int = 50):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.last_traded_bar = None

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculates 20 EMA and 50 EMA"""
        if df.empty or len(df) < self.ema_slow:
            return df
        
        data = df.copy()
        data['ema_20'] = data['close'].ewm(span=self.ema_fast, adjust=False).mean()
        data['ema_50'] = data['close'].ewm(span=self.ema_slow, adjust=False).mean()
        return data

    def scan_for_setup(self, df: pd.DataFrame, asset_name: str) -> Optional[Dict]:
        if df.empty or len(df) < (self.ema_slow + 5):
            return None

        clean_df = df.copy()
        if hasattr(clean_df.columns, 'levels') and len(clean_df.columns.levels) > 1:
            clean_df.columns = [col[0].lower() for col in clean_df.columns]
        else:
            clean_df.columns = [str(c).lower() for c in clean_df.columns]

        clean_df = clean_df.dropna()
        if len(clean_df) < (self.ema_slow + 5):
            return None

        # Ensure EMAs are present
        if 'ema_20' not in clean_df.columns or 'ema_50' not in clean_df.columns:
            clean_df['ema_20'] = clean_df['close'].ewm(span=self.ema_fast, adjust=False).mean()
            clean_df['ema_50'] = clean_df['close'].ewm(span=self.ema_slow, adjust=False).mean()

        curr_time = clean_df.index[-1]
        if self.last_traded_bar == curr_time:
            return None

        curr = clean_df.iloc[-1]
        prev = clean_df.iloc[-2]

        ema20 = curr['ema_20']
        ema50 = curr['ema_50']

        # -------------------------------------------------------------
        # 1. BULLISH SCALP (BUY CE)
        # Condition: 20 EMA > 50 EMA, Low tapped/tested EMA 20, Close > Open & Close > EMA 20
        # -------------------------------------------------------------
        if ema20 > ema50:
            if curr['low'] <= (ema20 + 2.0) and curr['close'] > ema20 and curr['close'] > curr['open']:
                entry = round(float(curr['close']), 2)
                sl = round(float(min(curr['low'], ema50) - 4.0), 2)
                risk = max(10.0, entry - sl)

                self.last_traded_bar = curr_time
                return {
                    'direction': 'BUY_CE',
                    'asset': asset_name,
                    'entry': entry,
                    'sl': sl,
                    'tp1': round(entry + risk, 2),
                    'tp2': round(entry + (2 * risk), 2),
                    'ema_20': round(float(ema20), 2),
                    'ema_50': round(float(ema50), 2),
                    'time': curr_time
                }

        # -------------------------------------------------------------
        # 2. BEARISH SCALP (BUY PE)
        # Condition: 20 EMA < 50 EMA, High tapped/tested EMA 20, Close < Open & Close < EMA 20
        # -------------------------------------------------------------
        elif ema20 < ema50:
            if curr['high'] >= (ema20 - 2.0) and curr['close'] < ema20 and curr['close'] < curr['open']:
                entry = round(float(curr['close']), 2)
                sl = round(float(max(curr['high'], ema50) + 4.0), 2)
                risk = max(10.0, sl - entry)

                self.last_traded_bar = curr_time
                return {
                    'direction': 'BUY_PE',
                    'asset': asset_name,
                    'entry': entry,
                    'sl': sl,
                    'tp1': round(entry - risk, 2),
                    'tp2': round(entry - (2 * risk), 2),
                    'ema_20': round(float(ema20), 2),
                    'ema_50': round(float(ema50), 2),
                    'time': curr_time
                }

        return None
