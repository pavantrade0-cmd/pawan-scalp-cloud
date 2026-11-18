import os
import time
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import pytz
from market_feed import DhanFeed
from smc_engine import InstitutionalLevelEngine

IST = pytz.timezone("Asia/Kolkata")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(msg)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=8)
    except Exception as e:
        print(f"Telegram error: {e}")

def run_bot():
    threading.Thread(target=start_health_server, daemon=True).start()
    feed = DhanFeed()
    engine = InstitutionalLevelEngine(zone_buffer=12.0, min_sl=10.0, max_sl=20.0)

    active_trade = None
    last_checked_candle = None
    trades_today = 0
    current_day = None

    send_telegram("🟢 Cloud Bot Active: 5-Min Institutional Levels & Strong S/R Engine")

    while True:
        try:
            now = datetime.now(IST)
            if current_day != now.date():
                current_day = now.date()
                trades_today = 0
                active_trade = None

            if now.weekday() >= 5 or not ((now.hour == 9 and now.minute >= 20) or (10 <= now.hour <= 14) or (now.hour == 15 and now.minute <= 15)):
                time.sleep(20)
                continue

            if active_trade:
                ltp_map = feed.get_option_ltp_bulk([active_trade["security_id"]])
                ltp = ltp_map.get(active_trade["security_id"], 0.0)

                if ltp > 0:
                    if not active_trade["tp1_hit"] and ltp >= active_trade["tp1"]:
                        active_trade["tp1_hit"] = True
                        active_trade["sl"] = active_trade["entry"]
                        send_telegram(
                            f"✅ TP1 HIT: {active_trade['symbol']} @ ₹{ltp:.2f} | 50% Booked | SL Trailed to ₹{active_trade['entry']:.2f}"
                        )
                    elif ltp >= active_trade["tp2"]:
                        pts = ltp - active_trade["entry"]
                        send_telegram(
                            f"🎯 TP2 HIT: {active_trade['symbol']} @ ₹{ltp:.2f} | Full Exit (+{pts:.1f} pts)"
                        )
                        active_trade = None
                    elif ltp <= active_trade["sl"]:
                        pts = ltp - active_trade["entry"]
                        status = "Cost-to-Cost Exit" if active_trade["tp1_hit"] else f"Closed ({pts:.1f} pts)"
                        send_telegram(
                            f"❌ SL HIT: {active_trade['symbol']} @ ₹{ltp:.2f} | {status}"
                        )
                        active_trade = None

                time.sleep(5)
                continue

            if trades_today >= 3 or (now.hour == 15 and now.minute >= 0):
                time.sleep(20)
                continue

            spot_df = feed.get_intraday_candles(security_id="13", exchange_segment="IDX_I", instrument="INDEX", interval="5", days_back=4)
            if len(spot_df) < 25:
                time.sleep(10)
                continue

            closed_df = spot_df.iloc[:-1]
            latest_candle_ts = closed_df.iloc[-1]["timestamp"]

            if last_checked_candle == latest_candle_ts:
                time.sleep(5)
                continue

            last_checked_candle = latest_candle_ts
            pdh, pdl = feed.get_daily_prev_hl()
            signal = engine.evaluate_spot_signal(closed_df, pdh, pdl)

            if signal:
                spot_close = float(closed_df.iloc[-1]["close"])
                strike_info = feed.select_strike_above_180(spot_close, option_type=signal["direction"])

                if strike_info:
                    opt_df = feed.get_intraday_candles(
                        security_id=strike_info["security_id"],
                        exchange_segment="NSE_FNO",
                        instrument="OPTIDX",
                        interval="5",
                        days_back=2
                    )
                    if len(opt_df) >= 12:
                        risk = engine.validate_option_entry(opt_df.iloc[:-1], strike_info["ltp"])
                        if risk:
                            trades_today += 1
                            active_trade = {
                                "security_id": strike_info["security_id"],
                                "symbol": strike_info["symbol"],
                                "entry": risk["entry"],
                                "sl": risk["sl"],
                                "tp1": risk["tp1"],
                                "tp2": risk["tp2"],
                                "tp1_hit": False
                            }
                            alert_msg = (
                                f"🚀 BUY {strike_info['symbol']} @ ₹{risk['entry']:.2f}\n"
                                f"Strategy: {signal['strategy']}\n"
                                f"SL: ₹{risk['sl']:.2f} (-{risk['sl_pts']:.0f} pts) | TP1: ₹{risk['tp1']:.2f} | TP2: ₹{risk['tp2']:.2f}"
                            )
                            send_telegram(alert_msg)

            time.sleep(5)

        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_bot()
                            
