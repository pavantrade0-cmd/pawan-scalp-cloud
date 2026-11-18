import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
DHAN_BASE_URL = "https://api.dhan.co/v2"

class DhanFeed:
    def __init__(self):
        self.client_id = os.getenv("DHAN_CLIENT_ID", "")
        self.access_token = os.getenv("DHAN_ACCESS_TOKEN", "")
        self.headers = {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        self._scrip_df = None
        self._last_scrip_fetch = None

    def _load_scrip_master(self):
        now = datetime.now(IST)
        if self._scrip_df is not None and self._last_scrip_fetch and (now - self._last_scrip_fetch).seconds < 21600:
            return self._scrip_df
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        nifty_opts = df[
            (df["SEM_EXM_EXCH_ID"] == "NSE") &
            (df["SEM_INSTRUMENT_NAME"] == "OPTIDX") &
            (df["SEM_TRADING_SYMBOL"].str.startswith("NIFTY-", na=False))
        ].copy()
        nifty_opts["SEM_EXPIRY_DATE"] = pd.to_datetime(nifty_opts["SEM_EXPIRY_DATE"])
        today = pd.Timestamp(now.date())
        nifty_opts = nifty_opts[nifty_opts["SEM_EXPIRY_DATE"] >= today]
        nearest_expiry = nifty_opts["SEM_EXPIRY_DATE"].min()
        self._scrip_df = nifty_opts[nifty_opts["SEM_EXPIRY_DATE"] == nearest_expiry].copy()
        self._last_scrip_fetch = now
        return self._scrip_df

    def get_intraday_candles(self, security_id="13", exchange_segment="IDX_I", instrument="INDEX", interval="5", days_back=5):
        now = datetime.now(IST)
        from_dt = (now - timedelta(days=days_back)).strftime("%Y-%m-%d 09:15:00")
        to_dt = now.strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "interval": str(interval),
            "oi": False,
            "fromDate": from_dt,
            "toDate": to_dt
        }
        resp = requests.post(f"{DHAN_BASE_URL}/charts/intraday", json=payload, headers=self.headers, timeout=10)
        data = resp.json()
        if "timestamp" not in data or not data["timestamp"]:
            return pd.DataFrame()
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(data["timestamp"], unit="s", utc=True).tz_convert(IST),
            "open": data["open"],
            "high": data["high"],
            "low": data["low"],
            "close": data["close"],
            "volume": data.get("volume", [0] * len(data["timestamp"]))
        })
        return df.sort_values("timestamp").reset_index(drop=True)

    def get_daily_prev_hl(self):
        now = datetime.now(IST)
        from_dt = (now - timedelta(days=10)).strftime("%Y-%m-%d")
        to_dt = now.strftime("%Y-%m-%d")
        payload = {
            "securityId": "13",
            "exchangeSegment": "IDX_I",
            "instrument": "INDEX",
            "expiryCode": 0,
            "oi": False,
            "fromDate": from_dt,
            "toDate": to_dt
        }
        resp = requests.post(f"{DHAN_BASE_URL}/charts/historical", json=payload, headers=self.headers, timeout=10)
        data = resp.json()
        if "timestamp" not in data or len(data["timestamp"]) < 2:
            return None, None
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(data["timestamp"], unit="s", utc=True).tz_convert(IST),
            "high": data["high"],
            "low": data["low"]
        })
        today_date = now.date()
        prev_days = df[df["timestamp"].dt.date < today_date]
        if prev_days.empty:
            return None, None
        last_day = prev_days.iloc[-1]
        return float(last_day["high"]), float(last_day["low"])

    def get_option_ltp_bulk(self, security_ids):
        payload = {"NSE_FNO": [int(sid) for sid in security_ids]}
        resp = requests.post(f"{DHAN_BASE_URL}/marketfeed/ltp", json=payload, headers=self.headers, timeout=10)
        data = resp.json().get("data", {}).get("NSE_FNO", {})
        return {str(k): float(v.get("last_price", 0.0)) for k, v in data.items()}

    def select_strike_above_180(self, spot_price, option_type="CE"):
        df = self._load_scrip_master()
        opt_df = df[df["SEM_OPTION_TYPE"] == option_type].copy()
        opt_df["SEM_STRIKE_PRICE"] = opt_df["SEM_STRIKE_PRICE"].astype(float)

        if option_type == "CE":
            candidates = opt_df[
                (opt_df["SEM_STRIKE_PRICE"] <= spot_price + 150) &
                (opt_df["SEM_STRIKE_PRICE"] >= spot_price - 500)
            ].sort_values("SEM_STRIKE_PRICE", ascending=False)
        else:
            candidates = opt_df[
                (opt_df["SEM_STRIKE_PRICE"] >= spot_price - 150) &
                (opt_df["SEM_STRIKE_PRICE"] <= spot_price + 500)
            ].sort_values("SEM_STRIKE_PRICE", ascending=True)

        if candidates.empty:
            return None

        sec_ids = candidates["SEM_SMST_SECURITY_ID"].astype(str).tolist()
        ltp_map = self.get_option_ltp_bulk(sec_ids)

        valid_strikes = []
        for _, row in candidates.iterrows():
            sid = str(row["SEM_SMST_SECURITY_ID"])
            ltp = ltp_map.get(sid, 0.0)
            if ltp >= 180.0:
                valid_strikes.append({
                    "security_id": sid,
                    "symbol": f"NIFTY {int(row['SEM_STRIKE_PRICE'])} {option_type}",
                    "strike": float(row["SEM_STRIKE_PRICE"]),
                    "option_type": option_type,
                    "ltp": ltp
                })

        if not valid_strikes:
            return None

        valid_strikes.sort(key=lambda x: x["ltp"])
        return valid_strikes[0]
