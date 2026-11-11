import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import pandas as pd
from datetime import datetime

from smc_engine import SMCEngine
from market_feed import MarketFeed
from telegram_bot import TelegramNotifier

BOT_TOKEN = "9227619823:AAEhVHQg7h2JqSu1zQgn2IRIwEMOapfqKSQ"
CHAT_ID = "7107919128"
ASSETS = ["NIFTY 50", "BTC-USD"]
POLL_INTERVAL = 10  # Seconds

# ==========================================
# RENDER WEB PORT BINDING (Fixes Deploy Failed)
# ==========================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"PAWAN AI Scalper Bot is Healthy & Running!")

    def log_message(self, format, *args):
        pass  # Suppress HTTP access logging

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# ==========================================
# CLEAN FORMATTED TELEGRAM ALERTS (SERVER)
# ==========================================
def format_server_entry_alert(trade: dict) -> str:
    is_ce = "CE" in trade['direction']
    action_color = "🟢" if is_ce else "🔴"
    
    return (
        "🌐 <b>[ FROM CLOUD SERVER ]</b>\n\n"
        f"<b>Asset :</b> {trade['asset']}\n"
        f"<b>Action :</b> {action_color} <b>{trade['direction']}</b>\n"
        f"<b>Entry Price :</b> ⚪ {trade['entry']:.2f}\n"
        f"<b>Stop Loss :</b> 🔴 {trade['sl']:.2f}\n"
        f"<b>Target 1 (1:1) :</b> 🟢 {trade['tp1']:.2f}\n"
        f"<b>Target 2 (1:2) :</b> 🟢 {trade['tp2']:.2f}"
    )

def format_server_tp1_alert(pos: dict, curr_price: float) -> str:
    return (
        "🌐 <b>[ FROM CLOUD SERVER ]</b>\n\n"
        f"<b>Asset :</b> {pos['asset']}\n"
        f"<b>Status :</b> 🟢 <b>TARGET 1 REACHED (1:1)</b>\n"
        f"<b>Target 1 :</b> 🟢 {pos['tp1']:.2f}\n"
        f"<b>Current Price :</b> ⚪ {curr_price:.2f}\n"
        f"<b>Action :</b> 🟡 Book 50% & Trail SL to Entry ({pos['entry']:.2f})"
    )

def format_server_tp2_alert(pos: dict) -> str:
    return (
        "🌐 <b>[ FROM CLOUD SERVER ]</b>\n\n"
        f"<b>Asset :</b> {pos['asset']}\n"
        f"<b>Status :</b> 🏁 <b>TARGET 2 REACHED (1:2)</b>\n"
        f"<b>Target 2 :</b> 🟢 {pos['tp2']:.2f}\n"
        "<b>Action :</b> 🟢 Trade Successfully Closed"
    )

def format_server_sl_alert(pos: dict) -> str:
    return (
        "🌐 <b>[ FROM CLOUD SERVER ]</b>\n\n"
        f"<b>Asset :</b> {pos['asset']}\n"
        f"<b>Status :</b> 🔴 <b>STOP LOSS HIT</b>\n"
        f"<b>Exit Price :</b> 🔴 {pos['sl']:.2f}\n"
        "<b>Action :</b> 🔴 Position Closed"
    )

def main():
    # Start web port listener in background for Render
    web_thread = threading.Thread(target=run_health_server, daemon=True)
    web_thread.start()

    notifier = TelegramNotifier(BOT_TOKEN, CHAT_ID)
    engine = SMCEngine(ema_fast=20, ema_slow=50)
    
    # Active trade state per asset
    active_positions = {}

    print("=" * 50)
    print("🚀 PAWAN AI — SERVER WORKER RUNNING (20/50 EMA SCALPER)")
    print("=" * 50)
    notifier.send_message("🌐 <b>[ FROM CLOUD SERVER ]</b>\n\n🟢 <b>Server Worker Online & Monitoring 5M Candles</b>")

    while True:
        try:
            for asset in ASSETS:
                df = MarketFeed.get_latest_candles(asset, timeframe="5m")
                if df.empty or len(df) < 55:
                    continue

                df = engine.calculate_indicators(df)
                latest = df.iloc[-1]
                curr_price = float(latest['close'])
                curr_high = float(latest['high'])
                curr_low = float(latest['low'])

                # -------------------------------------------------------------
                # 1. MONITOR ACTIVE POSITION (TP1, TP2, SL)
                # -------------------------------------------------------------
                if asset in active_positions:
                    pos = active_positions[asset]
                    direction = pos['direction']

                    # Check Target 1
                    if not pos['tp1_hit']:
                        tp1_hit = (curr_high >= pos['tp1']) if direction == 'BUY_CE' else (curr_low <= pos['tp1'])
                        if tp1_hit:
                            pos['tp1_hit'] = True
                            print(f"[{asset}] 🎯 TARGET 1 HIT @ {pos['tp1']}")
                            msg = format_server_tp1_alert(pos, curr_price)
                            notifier.send_message(msg)

                    # Check Target 2 (Full Target)
                    tp2_hit = (curr_high >= pos['tp2']) if direction == 'BUY_CE' else (curr_low <= pos['tp2'])
                    if tp2_hit:
                        print(f"[{asset}] 🏁 TARGET 2 HIT @ {pos['tp2']}")
                        msg = format_server_tp2_alert(pos)
                        notifier.send_message(msg)
                        del active_positions[asset]
                        continue

                    # Check Stop Loss
                    sl_hit = (curr_low <= pos['sl']) if direction == 'BUY_CE' else (curr_high >= pos['sl'])
                    if sl_hit:
                        print(f"[{asset}] 🛑 STOP LOSS HIT @ {pos['sl']}")
                        msg = format_server_sl_alert(pos)
                        notifier.send_message(msg)
                        del active_positions[asset]
                        continue

                # -------------------------------------------------------------
                # 2. SCAN NEW TRADE (Closed-candle confirmed setup)
                # -------------------------------------------------------------
                else:
                    trade = engine.scan_for_setup(df, asset)
                    if trade:
                        print(f"[{asset}] 🔥 NEW ENTRY: {trade['direction']} @ {trade['entry']}")
                        active_positions[asset] = {
                            'asset': trade['asset'],
                            'direction': trade['direction'],
                            'entry': float(trade['entry']),
                            'sl': float(trade['sl']),
                            'tp1': float(trade['tp1']),
                            'tp2': float(trade['tp2']),
                            'tp1_hit': False
                        }

                        msg = format_server_entry_alert(trade)
                        notifier.send_message(msg)

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\nWorker stopped by user.")
            break
        except Exception as e:
            print(f"[Worker Exception]: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
