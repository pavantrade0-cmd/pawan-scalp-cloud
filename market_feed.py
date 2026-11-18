import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")

class DhanFeed:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        self._active_sim = {}

    def _fetch_yahoo_candles(self, ticker, interval="5", days_back=5):
        encoded = requests.utils.quote(ticker)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval={interval}m&range={days_back}d"
        resp = requests.get(url, headers=self.headers, timeout=10)
        res = resp.json().get("chart", {}).get("result", [])
        if not res:
            return pd.DataFrame()
        q = res[0]["indicators"]["quote"][0]
        ts = res[0]["timestamp"]
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(ts, unit="s", utc=True).tz_convert(IST),
            "open": q["open"],
            "high": q["high"],
            "low": q["low"],
            "close": q["close"],
            "volume": [v if v is not None and v > 0 else 1000 for v in q["volume"]]
        }).dropna(subset=["open", "high", "low", "close"])
        return df.sort_values("timestamp").reset_index(drop=True)

    def get_intraday_candles(self, security_id="13", exchange_segment="IDX_I", instrument="INDEX", interval="5", days_back=5):
        sid = str(security_id)
        if sid == "13":
            return self._fetch_yahoo_candles("^NSEI", interval=interval, days_back=days_back)
        if sid == "BTC-USD":
            return self._fetch_yahoo_candles("BTC-USD", interval=interval, days_back=days_back)

        spot_df = self._fetch_yahoo_candles("^NSEI", interval=interval, days_back=days_back)
        if spot_df.empty or sid not in self._active_sim:
            return pd.DataFrame()

        meta = self._active_sim[sid]
        delta = 0.58 if meta["option_type"] == "CE" else -0.58
        ref_spot = meta["ref_spot"]
        ref_ltp = meta["ref_ltp"]

        opt_df = spot_df.copy()
        for col in ["open", "high", "low", "close"]:
            opt_df[col] = (ref_ltp + (spot_df[col] - ref_spot) * delta).clip(lower=1.0)
        if delta < 0:
            opt_df["high"], opt_df["low"] = opt_df["low"].copy(), opt_df["high"].copy()
        opt_df["volume"] = 2000
        return opt_df

    def get_daily_prev_hl(self, ticker="^NSEI"):
        # For BTC-USD, compute Previous Session High/Low anchored at 6:30 PM IST
        if ticker == "BTC-USD":
            df = self._fetch_yahoo_candles("BTC-USD", interval="15", days_back=4)
            if df.empty:
                return None, None
            now_ist = datetime.now(IST)
            today_630 = now_ist.replace(hour=18, minute=30, second=0, microsecond=0)
            curr_session_start = today_630 if now_ist >= today_630 else (today_630 - timedelta(days=1))
            prev_session_start = curr_session_start - timedelta(days=1)

            prev_sess = df[(df["timestamp"] >= prev_session_start) & (df["timestamp"] < curr_session_start)]
            if prev_sess.empty:
                return None, None
            return float(prev_sess["high"].max()), float(prev_sess["low"].min())

        # Standard Indian Market daily candle for ^NSEI
        encoded = requests.utils.quote(ticker)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=10d"
        resp = requests.get(url, headers=self.headers, timeout=10)
        res = resp.json().get("chart", {}).get("result", [])
        if not res:
            return None, None
        q = res[0]["indicators"]["quote"][0]
        ts = res[0]["timestamp"]
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(ts, unit="s", utc=True).tz_convert(IST),
            "high": q["high"],
            "low": q["low"]
        }).dropna()
        today_date = datetime.now(IST).date()
        prev_days = df[df["timestamp"].dt.date < today_date]
        if prev_days.empty:
            return None, None
        last_day = prev_days.iloc[-1]
        return float(last_day["high"]), float(last_day["low"])

    def get_btc_ltp(self):
        df = self._fetch_yahoo_candles("BTC-USD", interval="1", days_back=1)
        if df.empty:
            return 0.0
        return round(float(df.iloc[-1]["close"]), 2)

    def get_option_ltp_bulk(self, security_ids):
        spot_df = self._fetch_yahoo_candles("^NSEI", interval="5", days_back=1)
        if spot_df.empty:
            return {}
        curr_spot = float(spot_df.iloc[-1]["close"])
        out = {}
        for sid in security_ids:
            sid_str = str(sid)
            if sid_str in self._active_sim:
                meta = self._active_sim[sid_str]
                delta = 0.58 if meta["option_type"] == "CE" else -0.58
                est_ltp = max(1.0, round(meta["ref_ltp"] + (curr_spot - meta["ref_spot"]) * delta, 2))
                out[sid_str] = est_ltp
        return out

    def select_strike_above_180(self, spot_price, option_type="CE"):
        atm = round(spot_price / 50.0) * 50
        if option_type == "CE":
            strike = int(atm - 150)
            intrinsic = max(0.0, spot_price - strike)
        else:
            strike = int(atm + 150)
            intrinsic = max(0.0, strike - spot_price)

        est_ltp = round(max(185.0, intrinsic + 55.0), 2)
        sec_id = f"{strike}_{option_type}"
        self._active_sim[sec_id] = {
            "ref_spot": spot_price,
            "ref_ltp": est_ltp,
            "option_type": option_type
        }
        return {
            "security_id": sec_id,
            "symbol": f"NIFTY {strike} {option_type}",
            "strike": float(strike),
            "option_type": option_type,
            "ltp": est_ltp
            }
        
