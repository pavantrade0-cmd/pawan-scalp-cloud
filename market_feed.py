import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")

class DhanFeed:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://www.nseindia.com/option-chain"
        }
        self._session = requests.Session()
        self._active_sim = {}

    def _fetch_yahoo_candles(self, ticker, interval="5", days_back=5):
        encoded = requests.utils.quote(ticker)
        cb = int(time.time() * 1000)
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
            f"?interval={interval}m&range={days_back}d&includePrePost=false&_t={cb}"
        )
        resp = requests.get(url, headers={"User-Agent": self.headers["User-Agent"], "Cache-Control": "no-cache"}, timeout=8)
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

    def _get_live_nifty_spot(self):
        encoded = requests.utils.quote("^NSEI")
        cb = int(time.time() * 1000)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1m&range=1d&_t={cb}"
        try:
            resp = requests.get(url, headers={"User-Agent": self.headers["User-Agent"], "Cache-Control": "no-cache"}, timeout=6)
            res = resp.json().get("chart", {}).get("result", [])
            if not res:
                return None
            meta_price = float(res[0].get("meta", {}).get("regularMarketPrice", 0.0))
            if meta_price > 0:
                return meta_price
            q = res[0]["indicators"]["quote"][0]
            valid_closes = [c for c in q["close"] if c is not None]
            return float(valid_closes[-1]) if valid_closes else None
        except Exception:
            return None

    def _fetch_nse_option_chain(self):
        try:
            self._session.get("https://www.nseindia.com", headers=self.headers, timeout=4)
            resp = self._session.get(
                "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",
                headers=self.headers,
                timeout=6
            )
            if resp.status_code == 200:
                return resp.json().get("records", {}).get("data", [])
        except Exception:
            pass
        return []

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
        delta = 0.55 if meta["option_type"] == "CE" else -0.55
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

        encoded = requests.utils.quote(ticker)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=10d"
        resp = requests.get(url, headers={"User-Agent": self.headers["User-Agent"]}, timeout=8)
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

    def get_option_live_ticks(self, security_id):
        """Uses clean regularMarketPrice tick to prevent false 1m wick SL triggers."""
        sid_str = str(security_id)
        strike_str, opt_type = sid_str.split("_")
        strike_val = float(strike_str)

        oc_data = self._fetch_nse_option_chain()
        for row in oc_data:
            if float(row.get("strikePrice", 0)) == strike_val and opt_type in row:
                ltp = float(row[opt_type].get("lastPrice", 0))
                if ltp > 0:
                    val = round(ltp, 2)
                    return val, val, val

        if sid_str in self._active_sim:
            curr_spot = self._get_live_nifty_spot()
            if curr_spot:
                meta = self._active_sim[sid_str]
                if meta["option_type"] == "CE":
                    ltp = max(1.0, round(meta["ref_ltp"] + (curr_spot - meta["ref_spot"]) * 0.55, 2))
                else:
                    ltp = max(1.0, round(meta["ref_ltp"] + (meta["ref_spot"] - curr_spot) * 0.55, 2))
                return ltp, ltp, ltp

        return 0.0, 0.0, 0.0

    def select_strike_above_180(self, spot_price, option_type="CE"):
        live_spot = self._get_live_nifty_spot()
        ref_spot = live_spot if live_spot else spot_price
        atm = round(ref_spot / 50.0) * 50
        oc_data = self._fetch_nse_option_chain()

        candidates = []
        for row in oc_data:
            sp = float(row.get("strikePrice", 0))
            if opt_type in row:
                ltp = float(row[opt_type].get("lastPrice", 0))
                if 185.0 <= ltp <= 320.0:
                    candidates.append((abs(sp - atm), sp, ltp))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            _, strike, real_ltp = candidates[0]
            strike = int(strike)
            sec_id = f"{strike}_{option_type}"
            self._active_sim[sec_id] = {
                "ref_spot": ref_spot,
                "ref_ltp": real_ltp,
                "option_type": option_type
            }
            return {
                "security_id": sec_id,
                "symbol": f"NIFTY {strike} {option_type}",
                "strike": float(strike),
                "option_type": option_type,
                "ltp": round(real_ltp, 2)
            }

        # Calibrated ITM pricing (matches Sahi/TradingView ~205-225 premium range)
        if option_type == "CE":
            strike = int(atm - 100)
            intrinsic = max(0.0, ref_spot - strike)
        else:
            strike = int(atm + 100)
            intrinsic = max(0.0, strike - ref_spot)

        est_ltp = round(max(190.0, intrinsic + 105.0), 2)
        sec_id = f"{strike}_{option_type}"
        self._active_sim[sec_id] = {
            "ref_spot": ref_spot,
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
            
