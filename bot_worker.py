import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta

from smc_engine import SMCEngine
from market_feed import DhanDataFeed
from telegram_bot import TelegramNotifier

BOT_TOKEN = "9227619823:AAEhVHQg7h2JqSu1zQgn2IRIwEMOapfqKSQ"
CHAT_ID = "7107919128"
POLL_INTERVAL = 5  # Seconds
IST = timezone(timedelta(hours=5, minutes=30))


# ==========================================
# RENDER WEB PORT BINDING
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"PAWAN NIFTY OPTION SCALPER CLOUD ACTIVE")

    def log_message(self, format, *args):
        pass


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"[Render Port] Bound to 0.0.0.0:{port}")
    server.serve_forever()


# ==========================================
# CLEAN BOLD TELEGRAM ALERTS (CLOUD SERVER)
# ==========================================
def format_cloud_entry_alert(trade: dict) -> str:
    opt_side = trade["chart_type"]  # "CE" or "PE"
    return (
        "<b>[ FROM CLOUD SERVER ]</b>\n\n"
        f"<b>Contract:</b> {trade['asset']}\n"
        f"<b>Action:</b> <b>{opt_side}</b>\n"
        f"<b>Entry:</b> <b>{trade['entry']:.2f}</b>\n"
        f"<b>Stop Loss:</b> <b>{trade['sl']:.2f}</b>\n"
        f"<b>Target 1:</b> <b>{trade['tp1']:.2f}</b>\n"
        f"<b>Target 2:</b> <b>{trade['tp2']:.2f}</b>"
    )


def format_cloud_tp1_alert(tr: dict, curr_price: float) -> str:
    return (
        "<b>[ FROM CLOUD SERVER ]</b>\n\n"
        f"<b>Contract:</b> {tr['asset']}\n"
        f"<b>Status:</b> Target 1 Reached (<b>{tr['tp1']:.2f}</b>)\n"
        f"<b>Current Price:</b> <b>{curr_price:.2f}</b>\n"
        f"<b>Action:</b> Book 50% and trail SL to <b>{tr['entry']:.2f}</b>"
    )


def format_cloud_tp2_alert(tr: dict) -> str:
    return (
        "<b>[ FROM CLOUD SERVER ]</b>\n\n"
        f"<b>Contract:</b> {tr['asset']}\n"
        f"<b>Status:</b> Target 2 Reached (<b>{tr['tp2']:.2f}</b>)\n"
        "<b>Action:</b> Trade Closed"
    )


def format_cloud_sl_alert(tr: dict) -> str:
    return (
        "<b>[ FROM CLOUD SERVER ]</b>\n\n"
        f"<b>Contract:</b> {tr['asset']}\n"
        f"<b>Status:</b> Stop Loss Hit (<b>{tr['sl']:.2f}</b>)\n"
        "<b>Action:</b> Position Closed"
    )


def is_market_open() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:  # Saturday / Sunday
        return False
    mins = now.hour * 60 + now.minute
    return (9 * 60 + 20) <= mins <= (15 * 60 + 15)


def run_bot():
    feed = DhanDataFeed()
    engine = SMCEngine(ema_fast=20, ema_slow=50)
    tg = TelegramNotifier(BOT_TOKEN, CHAT_ID)
    active_trade = None

    print("[Cloud Server] NIFTY Option Buying Scanner Started...")
    tg.send_message(
        "<b>[ FROM CLOUD SERVER ]</b>\n\n"
        "<b>Status:</b> Cloud Bot Connected (Option Buying Active)"
    )

    while True:
        try:
            if not is_market_open():
                time.sleep(30)
                continue

            bundle = feed.fetch_all_three_charts()
            if not bundle:
                time.sleep(POLL_INTERVAL)
                continue

            spot_df = engine.calculate_indicators(bundle["spot_df"])
            ce_df = engine.calculate_indicators(bundle["ce_df"])
            pe_df = engine.calculate_indicators(bundle["pe_df"])

            # Monitor active CE or PE trade
            if active_trade is not None:
                target_df = ce_df if active_trade["chart_type"] == "CE" else pe_df
                if not target_df.empty:
                    latest = target_df.iloc[-1]
                    curr_price = float(latest["close"])
                    curr_high = float(latest["high"])
                    curr_low = float(latest["low"])

                    if not active_trade["tp1_hit"] and curr_high >= active_trade["tp1"]:
                        active_trade["tp1_hit"] = True
                        tg.send_message(format_cloud_tp1_alert(active_trade, curr_price))

                    if curr_high >= active_trade["tp2"]:
                        tg.send_message(format_cloud_tp2_alert(active_trade))
                        active_trade = None
                    elif curr_low <= active_trade["sl"]:
                        tg.send_message(format_cloud_sl_alert(active_trade))
                        active_trade = None

            # Scan for new Option Buying setup
            else:
                trade = engine.scan_option_buying_setup(
                    spot_df=spot_df,
                    ce_df=ce_df,
                    pe_df=pe_df,
                    ce_info=bundle["ce_info"],
                    pe_info=bundle["pe_info"]
                )
                if trade:
                    active_trade = {
                        "chart_type": trade["chart_type"],
                        "asset": trade["asset"],
                        "entry": float(trade["entry"]),
                        "sl": float(trade["sl"]),
                        "tp1": float(trade["tp1"]),
                        "tp2": float(trade["tp2"]),
                        "tp1_hit": False
                    }
                    tg.send_message(format_cloud_entry_alert(trade))

        except Exception as e:
            print(f"[Cloud Worker Error]: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    run_bot()
