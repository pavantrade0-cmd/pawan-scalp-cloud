import requests
import numpy as np
import pandas as pd
import yfinance as yf


class DhanDataFeed:
    def __init__(self, client_id: str = "", access_token: str = ""):
        self.groww_url = "https://groww.in/v1/api/option_chain_service/v1/option_chain/nifty"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        self.option_bars = {}

    def get_nifty_spot_5m(self) -> pd.DataFrame:
        try:
            df = yf.download("^NSEI", period="5d", interval="5m", progress=False)
            if df is None or df.empty:
                return pd.DataFrame()

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.rename(columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume"
            })
            df = df[["open", "high", "low", "close", "volume"]].dropna()
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
            else:
                df.index = df.index.tz_convert("Asia/Kolkata")
            return df
        except Exception as e:
            print(f"[Spot Feed Error]: {e}")
            return pd.DataFrame()

    def get_real_option_ltps(self, spot_price: float):
        try:
            res = requests.get(self.groww_url, headers=self.headers, timeout=8)
            if res.status_code != 200:
                return None

            data = res.json()
            chains = data.get("optionChain", {}).get("optionChains", [])
            if not chains:
                return None

            atm_strike = int(round(spot_price / 50) * 50)
            target_paise = atm_strike * 100

            for row in chains:
                ce_obj = row.get("callOption") or {}
                pe_obj = row.get("putOption") or {}
                strike_raw = int(ce_obj.get("strikePrice") or pe_obj.get("strikePrice") or 0)

                if strike_raw == target_paise or strike_raw == atm_strike:
                    ce_ltp = float(ce_obj.get("ltp", 0))
                    pe_ltp = float(pe_obj.get("ltp", 0))
                    ce_name = ce_obj.get("longDisplayName", f"NIFTY {atm_strike} CE").replace(" Call", " CE")
                    pe_name = pe_obj.get("longDisplayName", f"NIFTY {atm_strike} PE").replace(" Put", " PE")

                    if ce_ltp > 0 and pe_ltp > 0:
                        return {
                            "ce_symbol": ce_name,
                            "ce_ltp": ce_ltp,
                            "pe_symbol": pe_name,
                            "pe_ltp": pe_ltp
                        }
        except Exception as e:
            print(f"[Option Chain Error]: {e}")
        return None

    def _seed_option_history(self, spot_df: pd.DataFrame, live_ltp: float, is_call: bool) -> pd.DataFrame:
        delta = 0.52 if is_call else -0.52
        spot_closes = spot_df["close"].values
        spot_diff = spot_closes - spot_closes[-1]

        est_close = np.maximum(5.0, live_ltp + (spot_diff * delta))
        bar_range = np.abs(spot_df["high"].values - spot_df["low"].values) * 0.52

        est_open = np.roll(est_close, 1)
        est_open[0] = est_close[0]
        est_high = np.maximum(est_open, est_close) + (bar_range * 0.45)
        est_low = np.maximum(2.0, np.minimum(est_open, est_close) - (bar_range * 0.45))

        return pd.DataFrame({
            "open": np.round(est_open, 2),
            "high": np.round(est_high, 2),
            "low": np.round(est_low, 2),
            "close": np.round(est_close, 2),
            "volume": spot_df["volume"].values
        }, index=spot_df.index)

    def _update_live_option_bar(self, symbol: str, spot_df: pd.DataFrame, live_ltp: float, is_call: bool) -> pd.DataFrame:
        if symbol not in self.option_bars or self.option_bars[symbol].empty:
            self.option_bars[symbol] = self._seed_option_history(spot_df, live_ltp, is_call)
            return self.option_bars[symbol]

        df = self.option_bars[symbol]
        now_ist = pd.Timestamp.now(tz="Asia/Kolkata")
        current_bar_time = now_ist.floor("5min")

        if current_bar_time in df.index:
            df.loc[current_bar_time, "high"] = max(float(df.loc[current_bar_time, "high"]), live_ltp)
            df.loc[current_bar_time, "low"] = min(float(df.loc[current_bar_time, "low"]), live_ltp)
            df.loc[current_bar_time, "close"] = live_ltp
        else:
            new_row = pd.DataFrame({
                "open": [live_ltp],
                "high": [live_ltp],
                "low": [live_ltp],
                "close": [live_ltp],
                "volume": [1000]
            }, index=[current_bar_time])
            df = pd.concat([df, new_row]).iloc[-250:]
            self.option_bars[symbol] = df

        return df

    def fetch_all_three_charts(self):
        spot_df = self.get_nifty_spot_5m()
        if spot_df.empty:
            return None

        current_spot = float(spot_df["close"].iloc[-1])
        quotes = self.get_real_option_ltps(current_spot)
        if not quotes:
            return None

        ce_sym = quotes["ce_symbol"]
        pe_sym = quotes["pe_symbol"]
        ce_ltp = quotes["ce_ltp"]
        pe_ltp = quotes["pe_ltp"]

        ce_df = self._update_live_option_bar(ce_sym, spot_df, ce_ltp, is_call=True)
        pe_df = self._update_live_option_bar(pe_sym, spot_df, pe_ltp, is_call=False)

        return {
            "spot_price": current_spot,
            "spot_df": spot_df,
            "ce_info": {"symbol": ce_sym},
            "ce_df": ce_df,
            "pe_info": {"symbol": pe_sym},
            "pe_df": pe_df
        }
