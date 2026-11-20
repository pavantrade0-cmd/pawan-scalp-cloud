import os
import json
import time
import hashlib
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
FYERS_TOKEN_FILE = "fyers_token.json"

class DhanFeed:
    def __init__(self, skip_init=False):
        self.fyers_app_id = os.getenv("FYERS_APP_ID", "F2KFFQBXX0-100").strip()
        self.fyers_secret_id = os.getenv("FYERS_SECRET_ID", "VD18YIOWBS").strip()
        self.fyers_auth_code = os.getenv("FYERS_AUTH_CODE", "").strip()
        self.fyers_access_token = os.getenv("FYERS_ACCESS_TOKEN", "").strip()
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
        self._last_token_mtime = 0
        if not skip_init:
            self._init_fyers_token()

    def reload_token_if_updated(self):
        """Hot-reloads newly activated Fyers token from disk without restarting the worker."""
        if os.path.exists(FYERS_TOKEN_FILE):
            try:
                mtime = os.path.getmtime(FYERS_TOKEN_FILE)
                if mtime > self._last_token_mtime:
                    with open(FYERS_TOKEN_FILE, "r") as f:
                        saved = json.load(f)
                    if saved.get("access_token"):
                        self.fyers_access_token = saved["access_token"]
                        self._last_token_mtime = mtime
            except Exception:
                pass

    def _init_fyers_token(self, force_exchange=False):
        """Automatically exchanges auth_code for an access_token and caches it."""
        if not force_exchange:
            if self.fyers_access_token:
                print("Fyers Access Token loaded from ENV!", flush=True)
                return
            if os.path.exists(FYERS_TOKEN_FILE):
                try:
                    with open(FYERS_TOKEN_FILE, "r") as f:
                        saved = json.load(f)
                    if saved.get("access_token"):
                        self.fyers_access_token = saved["access_token"]
                        self._last_token_mtime = os.path.getmtime(FYERS_TOKEN_FILE)
                        print("Fyers Access Token loaded from cache!", flush=True)
                        return
                except Exception:
                    pass

        if self.fyers_app_id and self.fyers_secret_id and self.fyers_auth_code:
            try:
                raw_hash = f"{self.fyers_app_id}:{self.fyers_secret_id}".encode("utf-8")
                app_id_hash = hashlib.sha256(raw_hash).hexdigest()
                resp = requests.post(
                    "https://api-t1.fyers.in/api/v3/validate-authcode",
                    json={
                        "grant_type": "authorization_code",
                        "appIdHash": app_id_hash,
                        "code": self.fyers_auth_code
                    },
                    timeout=8
                )
                data = resp.json()
                tok = data.get("access_token", "")
                if tok:
                    self.fyers_access_token = tok
                    with open(FYERS_TOKEN_FILE, "w") as f:
                        json.dump({"auth_code": self.fyers_auth_code, "access_token": tok}, f)
                    self._last_token_mtime = os.path.getmtime(FYERS_TOKEN_FILE)
                    print("Fyers Access Token activated successfully!", flush=True)
                else:
                    print(f"Fyers token failed: {data}", flush=True)
            except Exception as e:
                print(f"Fyers token exchange error: {e}", flush=True)

    def _fetch_delta_btc_candles(self, resolution="5m", days_back=4):
        """Fetch live BTCUSD Perpetual candles directly from Delta Exchange India."""
        end_ts = int(time.time())
        start_ts = end_ts - int(days_back * 86400)
        urls = [
            f"https://api.india.delta.exchange/v2/history/candles?resolution={resolution}&symbol=BTCUSD&start={start_ts}&end={end_ts}",
            f"https://api.delta.exchange/v2/history/candles?resolution={resolution}&symbol=BTCUSD&start={start_ts}&end={end_ts}"
        ]
        for url in urls:
            try:
                resp = requests.get(url, headers={"User-Agent": self.headers["User-Agent"]}, timeout=8)
                if resp.status_code == 200:
                    rows = resp.json().get("result", [])
                    if rows:
                        df = pd.DataFrame(rows)
                        df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_convert(IST)
                        for col in ["open", "high", "low", "close"]:
                            df[col] = df[col].astype(float)
                        df["volume"] = df["volume"].astype(float).replace(0, 1000.0)
                        return df[["timestamp", "open", "high", "low", "close", "volume"]].sort_values("timestamp").reset_index(drop=True)
            except Exception:
                continue
        return self._fetch_yahoo_candles("BTC-USD", interval=resolution.replace("m", ""), days_back=days_back)

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
        if self.fyers_app_id and self.fyers_access_token:
            try:
                resp = requests.get(
                    "https://api-t1.fyers.in/data/quotes?symbols=NSE:NIFTY50-INDEX",
                    headers={"Authorization": f"{self.fyers_app_id}:{self.fyers_access_token}"},
                    timeout=5
                )
                if resp.status_code == 200:
                    d = resp.json().get("d", [])
                    if d and "v" in d[0]:
                        lp = float(d[0]["v"].get("lp", 0.0))
                        if lp > 0:
                            return lp, lp, lp
            except Exception:
                pass

        encoded = requests.utils.quote("^NSEI")
        cb = int(time.time() * 1000)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1m&range=1d&_t={cb}"
        try:
            resp = requests.get(url, headers={"User-Agent": self.headers["User-Agent"], "Cache-Control": "no-cache"}, timeout=6)
            res = resp.json().get("chart", {}).get("result", [])
            if not res:
                return None, None, None
            meta_price = float(res[0].get("meta", {}).get("regularMarketPrice", 0.0))
            q = res[0]["indicators"]["quote"][0]
            valid_closes = [float(c) for c in q["close"] if c is not None]
            valid_highs = [float(h) for h in q["high"] if h is not None]
            valid_lows = [float(l) for l in q["low"] if l is not None]

            curr = meta_price if meta_price > 0 else (valid_closes[-1] if valid_closes else None)
            safe_h = max(curr, valid_highs[-2]) if (curr and len(valid_highs) >= 2) else curr
            safe_l = min(curr, valid_lows[-2]) if (curr and len(valid_lows) >= 2) else curr
            return curr, safe_h, safe_l
        except Exception:
            return None, None, None

    def _fetch_fyers_option_chain(self):
        """Fetch real-time NIFTY 50 option chain directly from Fyers API v3."""
        if not self.fyers_app_id or not self.fyers_access_token:
            return []
        try:
            resp = requests.get(
                "https://api-t1.fyers.in/data/options-chain-v3?symbol=NSE:NIFTY50-INDEX&strikecount=12&timestamp=",
                headers={"Authorization": f"{self.fyers_app_id}:{self.fyers_access_token}"},
                timeout=6
            )
            if resp.status_code == 200:
                options_list = resp.json().get("data", {}).get("optionsChain", [])
                strike_map = {}
                for item in options_list:
                    sp = float(item.get("strike_price", 0))
                    otype = item.get("option_type", "")
                    ltp = float(item.get("ltp", 0))
                    if sp > 0 and otype in ("CE", "PE") and ltp > 0:
                        strike_map.setdefault(sp, {"strikePrice": sp})[otype] = {
                            "lastPrice": ltp,
                            "fyers_symbol": item.get("symbol", "")
                        }
                return list(strike_map.values())
        except Exception:
            pass
        return []

    def _fetch_nse_option_chain(self):
        fyers_rows = self._fetch_fyers_option_chain()
        if fyers_rows:
            return fyers_rows
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

    def _estimate_option_premium(self, spot_val, strike, option_type):
        if option_type == "CE":
            intrinsic = max(0.0, spot_val - strike)
            return round(115.5 + 0.56 * intrinsic, 2)
        else:
            intrinsic = max(0.0, strike - spot_val)
            return round(148.0 + 0.58 * intrinsic, 2)

    def _calc_dynamic_option_price(self, meta, spot_val):
        entry_ts = meta.get("entry_ts", time.time())
        mins_held = max(0.0, (time.time() - entry_ts) / 60.0)
        theta_decay = min(mins_held * 0.15, 12.0)

        if "strike" in meta:
            base_est = self._estimate_option_premium(spot_val, meta["strike"], meta["option_type"])
            ref_est = self._estimate_option_premium(meta["ref_spot"], meta["strike"], meta["option_type"])
            return max(1.0, round(meta["ref_ltp"] + (base_est - ref_est) - theta_decay, 2))

        move = spot_val - meta["ref_spot"] if meta["option_type"] == "CE" else meta["ref_spot"] - spot_val
        eff_delta = 0.78 if move > 35.0 else (0.66 if move > 15.0 else 0.60)
        return max(1.0, round(meta["ref_ltp"] + move * eff_delta - theta_decay, 2))

    def get_intraday_candles(self, security_id="13", exchange_segment="IDX_I", instrument="INDEX", interval="5", days_back=5):
        sid = str(security_id)
        if sid == "13":
            return self._fetch_yahoo_candles("^NSEI", interval=interval, days_back=days_back)
        if sid == "BTC-USD":
            return self._fetch_delta_btc_candles(resolution=f"{interval}m", days_back=days_back)

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
        if ticker == "BTC-USD":
            df = self._fetch_delta_btc_candles(resolution="15m", days_back=4)
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

    def get_btc_live_ticks(self):
        for url in (
            "https://api.india.delta.exchange/v2/tickers/BTCUSD",
            "https://api.delta.exchange/v2/tickers/BTCUSD"
        ):
            try:
                resp = requests.get(url, headers={"User-Agent": self.headers["User-Agent"]}, timeout=6)
                if resp.status_code == 200:
                    res = resp.json().get("result", {})
                    ltp = float(res.get("close") or res.get("mark_price") or 0.0)
                    if ltp > 0:
                        df_1m = self._fetch_delta_btc_candles(resolution="1m", days_back=1)
                        if len(df_1m) >= 2:
                            c_high = max(ltp, float(df_1m.iloc[-2]["high"]))
                            c_low = min(ltp, float(df_1m.iloc[-2]["low"]))
                            return round(ltp, 2), round(c_high, 2), round(c_low, 2)
                        return round(ltp, 2), round(ltp, 2), round(ltp, 2)
            except Exception:
                continue

        df = self._fetch_yahoo_candles("BTC-USD", interval="1", days_back=1)
        if df.empty:
            return 0.0, 0.0, 0.0
        val = round(float(df.iloc[-1]["close"]), 2)
        return val, val, val

    def get_option_live_ticks(self, security_id):
        sid_str = str(security_id)
        strike_str, opt_type = sid_str.split("_")
        strike_val = float(strike_str)

        if sid_str in self._active_sim and self._active_sim[sid_str].get("fyers_symbol") and self.fyers_access_token:
            fsym = self._active_sim[sid_str]["fyers_symbol"]
            try:
                resp = requests.get(
                    f"https://api-t1.fyers.in/data/quotes?symbols={fsym}",
                    headers={"Authorization": f"{self.fyers_app_id}:{self.fyers_access_token}"},
                    timeout=5
                )
                if resp.status_code == 200:
                    d = resp.json().get("d", [])
                    if d and "v" in d[0]:
                        lp = float(d[0]["v"].get("lp", 0.0))
                        if lp > 0:
                            val = round(lp, 2)
                            return val, val, val
            except Exception:
                pass

        oc_data = self._fetch_nse_option_chain()
        for row in oc_data:
            if float(row.get("strikePrice", 0)) == strike_val and opt_type in row:
                ltp = float(row[opt_type].get("lastPrice", 0))
                if ltp > 0:
                    val = round(ltp, 2)
                    return val, val, val

        if sid_str in self._active_sim:
            curr_spot, spot_h, spot_l = self._get_live_nifty_spot()
            if curr_spot:
                meta = self._active_sim[sid_str]
                ltp = self._calc_dynamic_option_price(meta, curr_spot)
                if meta["option_type"] == "CE":
                    opt_h = max(ltp, self._calc_dynamic_option_price(meta, spot_h))
                    opt_l = min(ltp, self._calc_dynamic_option_price(meta, spot_l))
                else:
                    opt_h = max(ltp, self._calc_dynamic_option_price(meta, spot_l))
                    opt_l = min(ltp, self._calc_dynamic_option_price(meta, spot_h))
                return ltp, opt_h, opt_l

        return 0.0, 0.0, 0.0

    def select_strike_above_150(self, spot_price, option_type="CE"):
        """Selects the first strike strictly above ₹150 separately for CE side or PE side."""
        live_spot, _, _ = self._get_live_nifty_spot()
        ref_spot = live_spot if live_spot else spot_price
        atm = round(ref_spot / 50.0) * 50
        oc_data = self._fetch_nse_option_chain()

        # 1. Live Fyers / NSE Option Chain: separate lookup for CE vs PE strike > ₹150
        candidates = []
        for row in oc_data:
            sp = float(row.get("strikePrice", 0))
            if option_type in row:
                ltp = float(row[option_type].get("lastPrice", 0))
                fsym = row[option_type].get("fyers_symbol", "")
                if 152.0 <= ltp <= 230.0:
                    candidates.append((ltp, sp, fsym))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            real_ltp, sp, fsym = candidates[0]
            strike = int(sp)
            sec_id = f"{strike}_{option_type}"
            self._active_sim[sec_id] = {
                "strike": float(strike),
                "ref_spot": ref_spot,
                "ref_ltp": round(real_ltp, 2),
                "option_type": option_type,
                "fyers_symbol": fsym,
                "entry_ts": time.time()
            }
            return {
                "security_id": sec_id,
                "symbol": f"NIFTY {strike} {option_type}",
                "strike": float(strike),
                "option_type": option_type,
                "ltp": round(real_ltp, 2)
            }

        # 2. Fallback: scan CE side or PE side for first strike > ₹150
        for offset in (0, 50, 100, 150, 200, 250):
            strike = int(atm - offset) if option_type == "CE" else int(atm + offset)
            est_ltp = self._estimate_option_premium(ref_spot, strike, option_type)
            if est_ltp > 150.0:
                sec_id = f"{strike}_{option_type}"
                self._active_sim[sec_id] = {
                    "strike": float(strike),
                    "ref_spot": ref_spot,
                    "ref_ltp": est_ltp,
                    "option_type": option_type,
                    "entry_ts": time.time()
                }
                return {
                    "security_id": sec_id,
                    "symbol": f"NIFTY {strike} {option_type}",
                    "strike": f
