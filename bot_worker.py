import os
import time
import datetime
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import yfinance as yf
import pandas as pd
from smc_engine import SMCEngine
from telegram_bot import TelegramNotifier

# --- 1. DUMMY WEB SERVER FOR RENDER FREE WEB SERVICE HEALTH CHECK ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"PAWAN SCALPER BOT 24/7 ONLINE - OK")

    def log_message(self, format, *args):
        return  # Suppress HTTP access logs

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Start Web Server in background daemon thread (Keeps Render Free Service Alive)
threading.Thread(target=run_web_server, daemon=True).start()

# --- 2. TRADING BOT ENGINE ---
tg = TelegramNotifier(
    bot_token="9227619823:AAEhVHQg7h2JqSu1zQgn2IRIwEMOapfqKSQ",
    chat_id="7107919128"
)
engine = SMCEngine()

ASSETS = [
    {"display": "BTC-USD", "symbol": "BTC-USD", "is_crypto": True},
    {"display": "NIFTY 50", "symbol": "^NSEI", "is_crypto": False}
]

active_trades = {a["display"]: None for a in ASSETS}
last_alerted_candle = {a["display"]: None for a in ASSETS}

def is_market_open():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
    if now_ist.weekday() >= 5:
        return False
    market_start = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= now_ist <= market_end

def fetch_data(symbol):
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="2d", interval="5m")
        if df.empty or len(df) < 55:
            return pd.DataFrame()
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception as e:
        print(f"[FETCH ERROR {symbol}]: {e}")
        return pd.DataFrame()

print("🚀 PAWAN 24/7 CLOUD WORKER ACTIVE...")
tg.send_message("🌐 <b>PAWAN CLOUD SCALPER 24/7 ONLINE</b>\nBot monitoring BTC-USD & NIFTY 50 (Free Cloud Web Service Active).")

while True:
    try:
        for asset in ASSETS:
            name = asset["display"]
            sym = asset["symbol"]
            is_crypto = asset["is_crypto"]

            if not is_crypto and not is_market_open():
                continue

            df = fetch_data(sym)
            if df.empty or len(df) < 55:
                continue

            df = engine.calculate_indicators(df)
            
            curr_bar = df.iloc[-1]
            curr_high = float(curr_bar['high'])
            curr_low = float(curr_bar['low'])

            # Manage Active Trade
            trade = active_trades[name]
            if trade is not None:
                direction = trade["signal"]
                entry = trade["entry_price"]
                sl = trade["stop_loss"]
                tp1 = trade.get("target_partial")
                tp2 = trade.get("target_2", trade.get("target_1"))
                risk = trade.get("points", 0)
                tp1_hit = trade.get("tp1_hit", False)

                if direction == "BUY CE":
                    if not tp1_hit and curr_high >= tp1:
                        trade["tp1_hit"] = True
                        tg.send_partial_tp_alert(symbol=name, direction=direction, exit_price=tp1, gain_pts=risk * 1.0)

                    if curr_high >= tp2:
                        active_trades[name] = None
                        tg.send_exit_alert(symbol=name, direction=direction, outcome=f"FULL TARGET HIT (1:2) (+{risk * 2:.0f} pts)", exit_price=tp2)
                        continue

                    if curr_low <= sl:
                        active_trades[name] = None
                        tg.send_exit_alert(symbol=name, direction=direction, outcome=f"STOP LOSS HIT (-{risk:.0f} pts)", exit_price=sl)
                        continue

                elif direction == "BUY PE":
                    if not tp1_hit and curr_low <= tp1:
                        trade["tp1_hit"] = True
                        tg.send_partial_tp_alert(symbol=name, direction=direction, exit_price=tp1, gain_pts=risk * 1.0)

                    if curr_low <= tp2:
                        active_trades[name] = None
                        tg.send_exit_alert(symbol=name, direction=direction, outcome=f"FULL TARGET HIT (1:2) (+{risk * 2:.0f} pts)", exit_price=tp2)
                        continue

                    if curr_high >= sl:
                        active_trades[name] = None
                        tg.send_exit_alert(symbol=name, direction=direction, outcome=f"STOP LOSS HIT (-{risk:.0f} pts)", exit_price=sl)
                        continue

                continue

            # Scan New Setups
            setup = engine.scan_for_setups(df)
            if setup.get("signal") in ["BUY CE", "BUY PE"]:
                candle_timestamp = str(df.index[-2])
                if last_alerted_candle[name] != candle_timestamp:
                    last_alerted_candle[name] = candle_timestamp
                    setup["tp1_hit"] = False
                    active_trades[name] = setup

                    tg.send_entry_alert(
                        symbol=name,
                        direction=setup["signal"],
                        entry=setup["entry_price"],
                        sl=setup["stop_loss"],
                        tp1=setup["target_partial"],
                        tp2=setup["target_2"],
                        reason=setup["reason"]
                    )

    except Exception as e:
        print(f"[WORKER TICK ERROR]: {e}")

    time.sleep(15)
