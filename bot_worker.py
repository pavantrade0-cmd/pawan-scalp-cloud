import os
import time
import threading
from datetime import datetime
import pytz
from flask import Flask

from market_feed import DhanDataFeed
from smc_engine import SMCEngine
from telegram_bot import TelegramNotifier

app = Flask(__name__)
IST = pytz.timezone("Asia/Kolkata")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

feed = DhanDataFeed()
engine = SMCEngine(ema_fast=20, ema_slow=50)
tg = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

active_trade = None


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
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return (9 * 60 + 20) <= mins <= (15 * 60 + 15)


def scanner_loop():
    global active_trade
    print("[Cloud Server] Option Buying Scanner Started...")

    while True:
        try:
            if not is_market_open():
                time.sleep(30)
                continue

            bundle = feed.fetch_all_three_charts()
            if not bundle:
                time.sleep(5)
                continue

            spot_df = engine.calculate_indicators(bundle["spot_df"])
            ce_df = engine.calculate_indicators(bundle["ce_df"])
            pe_df = engine.calculate_indicators(bundle["pe_df"])

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
            print(f"[Cloud Loop Error]: {e}")

        time.sleep(5)


@app.route("/")
def health_check():
    return {"status": "running", "service": "pawan-scalp-bot-options-only"}


threading.Thread(target=scanner_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
