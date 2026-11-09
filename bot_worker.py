import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pandas as pd
from market_feed import MarketFeed
from smc_engine import SMCEngine
from telegram_bot import TelegramNotifier

# 1. Render Web Service Healthy గా ఉండటానికి HTTP సర్వర్
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
    
    tg.send_message("🌐 <b>PAWAN CLOUD SCALPER 24/7 ONLINE</b>\nMulti-Target Mode Active: Target 1 (1:1) & Full Target (1:2).")

    while True:
        try:
            for item in symbols:
                sym_name = item["name"]
                sym_feed = item["feed"]

                df = MarketFeed.get_latest_candles(symbol=sym_feed, timeframe="5m")
                if df.empty or len(df) < 55:
                    continue

                live_price = float(df['close'].iloc[-1])

                # 1. IN-TRADE SL / TP CHECK (Multi-Stage Target Tracking)
                if sym_name in active_trades:
                    trade = active_trades[sym_name]
                    direction = trade["signal"]
                    tp1 = trade["target_1"]
                    tp2 = trade["target_2"]
                    sl = trade["stop_loss"]
                    pts = trade.get("points", 0)

                    if direction == "BUY CE":
                        # Full Target 1:2 Hit
                        if live_price >= tp2:
                            tg.send_exit_alert(sym_name, direction, f"FULL TARGET HIT (1:2) (+{pts * 2:.0f} pts) 🎯🎯", live_price)
                            del active_trades[sym_name]
                        # Target 1 (1:1) Hit
                        elif live_price >= tp1 and not trade.get("tp1_hit", False):
                            trade["tp1_hit"] = True
                            tg.send_message(
                                f"🎯 <b>TARGET 1 HIT (1:1) — {sym_name}</b>\n"
                                f"⚡ <b>Trade:</b> {direction}\n"
                                f"💰 <b>LTP:</b> {live_price:,.2f} (+{pts:.0f} pts)\n"
                                f"🚀 <i>Holding runner position for Full Target (1:2): {tp2:,.2f}</i>"
                            )
                        # Stop Loss Hit
                        elif live_price <= sl:
                            tg.send_exit_alert(sym_name, direction, f"STOP LOSS HIT (-{pts:.0f} pts) 🛑", live_price)
                            del active_trades[sym_name]

                    elif direction == "BUY PE":
                        # Full Target 1:2 Hit
                        if live_price <= tp2:
                            tg.send_exit_alert(sym_name, direction, f"FULL TARGET HIT (1:2) (+{pts * 2:.0f} pts) 🎯🎯", live_price)
                            del active_trades[sym_name]
                        # Target 1 (1:1) Hit
                        elif live_price <= tp1 and not trade.get("tp1_hit", False):
                            trade["tp1_hit"] = True
                            tg.send_message(
                                f"🎯 <b>TARGET 1 HIT (1:1) — {sym_name}</b>\n"
                                f"⚡ <b>Trade:</b> {direction}\n"
                                f"💰 <b>LTP:</b> {live_price:,.2f} (+{pts:.0f} pts)\n"
                                f"🚀 <i>Holding runner position for Full Target (1:2): {tp2:,.2f}</i>"
                            )
                        # Stop Loss Hit
                        elif live_price >= sl:
                            tg.send_exit_alert(sym_name, direction, f"STOP LOSS HIT (-{pts:.0f} pts) 🛑", live_price)
                            del active_trades[sym_name]
                    continue

                # 2. SCAN FOR NEW 20/50 EMA PULLBACK SETUP
                setup = smc.scan_for_setups(df)
                if setup.get("signal") in ["BUY CE", "BUY PE"]:
                    c_time = setup.get("candle_time")
                    if last_candle_times.get(sym_name) != c_time:
                        last_candle_times[sym_name] = c_time
                        active_trades[sym_name] = setup
                        
                        tg.send_message(
                            f"🔔 <b>NEW SCALP SIGNAL: {setup['signal']}</b>\n\n"
                            f"📌 <b>Asset:</b> {sym_name}\n"
                            f"🔹 <b>Entry:</b> {setup['entry_price']:,.2f}\n"
                            f"🛑 <b>Stop Loss:</b> {setup['stop_loss']:,.2f} (-{setup['points']:.0f} pts)\n"
                            f"🎯 <b>Target 1 (1:1):</b> {setup['target_1']:,.2f} (+{setup['points']:.0f} pts)\n"
                            f"🏆 <b>Target 2 (1:2):</b> {setup['target_2']:,.2f} (+{setup['points'] * 2:.0f} pts)\n"
                            f"💡 <b>Reason:</b> {setup['reason']}"
                        )
                        print(f"[{sym_name}] New Alert Sent to Telegram.")

        except Exception as e:
            print(f"[WORKER ERROR]: {e}")

        time.sleep(5)

if __name__ == "__main__":
    web_thread = threading.Thread(target=run_http_server, daemon=True)
    web_thread.start()
    run_cloud_scanner()
