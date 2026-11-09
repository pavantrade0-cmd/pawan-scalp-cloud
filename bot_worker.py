import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pandas as pd
from market_feed import MarketFeed
from smc_engine import SMCEngine
from telegram_bot import TelegramNotifier

# 1. Render Web Service Healthy గా ఉండటానికి చిన్న HTTP సర్వర్
class SimpleHealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"PAWAN SCALPER CLOUD ENGINE ACTIVE")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHealthServer)
    print(f"HTTP Server listening on port {port}")
    server.serve_forever()

# 2. మెయిన్ స్కాల్పింగ్ స్కానర్
def run_cloud_scanner():
    print("🌐 Cloud Scalper Bot Started... Monitoring 24/7.")
    
    tg = TelegramNotifier(
        bot_token="9227619823:AAEhVHQg7h2JqSu1zQgn2IRIwEMOapfqKSQ",
        chat_id="7107919128"
    )
    smc = SMCEngine()
    
    symbols = [
        {"name": "BTC-USD", "feed": "BTC-USD"},
        {"name": "NIFTY 50", "feed": "^NSEI"}
    ]
    
    active_trades = {}
    last_candle_times = {}
    
    tg.send_message("🌐 <b>PAWAN CLOUD SCALPER 24/7 ONLINE</b>\nBot healthy and scanning BTC-USD & NIFTY with 1:2 RR.")

    while True:
        try:
            for item in symbols:
                sym_name = item["name"]
                sym_feed = item["feed"]

                df = MarketFeed.get_latest_candles(symbol=sym_feed, timeframe="5m")
                if df.empty or len(df) < 55:
                    continue

                live_price = float(df['close'].iloc[-1])

                # 1. IN-TRADE SL / TP CHECK (Single-Position Lock)
                if sym_name in active_trades:
                    trade = active_trades[sym_name]
                    direction = trade["signal"]
                    tp = trade["target_1"]
                    sl = trade["stop_loss"]

                    if direction == "BUY CE":
                        if live_price >= tp:
                            tg.send_exit_alert(sym_name, direction, f"TARGET HIT (+{trade.get('points', 0) * 2:.0f} pts) 🎯", live_price)
                            del active_trades[sym_name]
                        elif live_price <= sl:
                            tg.send_exit_alert(sym_name, direction, f"STOP LOSS HIT (-{trade.get('points', 0):.0f} pts) 🛑", live_price)
                            del active_trades[sym_name]

                    elif direction == "BUY PE":
                        if live_price <= tp:
                            tg.send_exit_alert(sym_name, direction, f"TARGET HIT (+{trade.get('points', 0) * 2:.0f} pts) 🎯", live_price)
                            del active_trades[sym_name]
                        elif live_price >= sl:
                            tg.send_exit_alert(sym_name, direction, f"STOP LOSS HIT (-{trade.get('points', 0):.0f} pts) 🛑", live_price)
                            del active_trades[sym_name]
                    continue

                # 2. SCAN FOR NEW 20/50 EMA PULLBACK SETUP
                setup = smc.scan_for_setups(df)
                if setup.get("signal") in ["BUY CE", "BUY PE"]:
                    c_time = setup.get("candle_time")
                    if last_candle_times.get(sym_name) != c_time:
                        last_candle_times[sym_name] = c_time
                        active_trades[sym_name] = setup
                        
                        tg.send_entry_alert(
                            symbol=sym_name,
                            direction=setup["signal"],
                            entry=setup["entry_price"],
                            sl=setup["stop_loss"],
                            tp=setup["target_1"],
                            reason=setup["reason"]
                        )
                        print(f"[{sym_name}] New Alert Sent to Telegram.")

        except Exception as e:
            print(f"[WORKER ERROR]: {e}")

        time.sleep(5)

if __name__ == "__main__":
    # బ్యాక్‌గ్రౌండ్ థ్రెడ్‌లో HTTP వెబ్ పోర్ట్ రన్ చేయడం
    web_thread = threading.Thread(target=run_http_server, daemon=True)
    web_thread.start()
    
    # స్కానర్ ప్రారంభం
    run_cloud_scanner()
