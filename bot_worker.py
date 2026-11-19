import os
import json
import time
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
import pytz
from market_feed import DhanFeed
from smc_engine import InstitutionalLevelEngine

IST = pytz.timezone("Asia/Kolkata")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_FILE = "bot_state.json"

HEADER = "<b><code>[From cloud server]</code></b>\n\n"

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

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
        requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=8
        )
    except Exception as e:
        print(f"Telegram error: {e}")

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"State save error: {e}")

def calculate_btc_levels(closed_df, side):
    entry = float(closed_df.iloc[-1]["close"])
    recent = closed_df.iloc[-6:]
    if side == "LONG":
        swing_low = float(recent["low"].min())
        raw_risk = entry - swing_low + 25.0
        risk = min(max(raw_risk, 150.0), 400.0)
        sl = round(entry - risk, 2)
        tp1 = round(entry + risk, 2)
        tp2 = round(entry + risk * 2, 2)
        tp3 = round(entry + risk * 3, 2)
    else:
        swing_high = float(recent["high"].max())
        raw_risk = swing_high - entry + 25.0
        risk = min(max(raw_risk, 150.0), 400.0)
        sl = round(entry + risk, 2)
        tp1 = round(entry - risk, 2)
        tp2 = round(entry - risk * 2, 2)
        tp3 = round(entry - risk * 3, 2)
    return round(entry, 2), sl, int(round(risk)), tp1, tp2, tp3

def run_bot():
    threading.Thread(target=start_health_server, daemon=True).start()
    feed = DhanFeed()
    nifty_engine = InstitutionalLevelEngine(zone_buffer=12.0, min_sl=10.0, max_sl=15.0)
    btc_engine = InstitutionalLevelEngine(zone_buffer=80.0, min_sl=150.0, max_sl=400.0)

    now_boot = datetime.now(IST)
    state = load_state()

    nifty_trade = state.get("nifty_trade")
    btc_trade = state.get("btc_trade")
    last_nifty_candle = state.get("last_nifty_candle")
    last_btc_candle = state.get("last_btc_candle")
    nifty_trades_today = state.get("nifty_trades_today", 0)
    btc_trades_today = state.get("btc_trades_today", 0)
    current_nifty_day = state.get("current_nifty_day")
    current_btc_session = state.get("current_btc_session")
    last_boot_day = state.get("last_boot_day")

    # Restore simulator anchor if Nifty trade is active across container restart
    if nifty_trade and "sim_meta" in nifty_trade:
        feed._active_sim[nifty_trade["security_id"]] = nifty_trade["sim_meta"]

    if last_boot_day != str(now_boot.date()):
        last_boot_day = str(now_boot.date())
        send_telegram(f"{HEADER}Cloud Bot Active\nMarkets : NIFTY 50 + BTC (6:30 PM IST)")
        save_state({
            "nifty_trade": nifty_trade,
            "btc_trade": btc_trade,
            "last_nifty_candle": last_nifty_candle,
            "last_btc_candle": last_btc_candle,
            "nifty_trades_today": nifty_trades_today,
            "btc_trades_today": btc_trades_today,
            "current_nifty_day": current_nifty_day,
            "current_btc_session": current_btc_session,
            "last_boot_day": last_boot_day
        })

    while True:
        try:
            now = datetime.now(IST)
            state_changed = False

            today_str = str(now.date())
            if current_nifty_day != today_str:
                current_nifty_day = today_str
                nifty_trades_today = 0
                nifty_trade = None
                state_changed = True

            today_630 = now.replace(hour=18, minute=30, second=0, microsecond=0)
            btc_session_str = str(now.date() if now >= today_630 else (now - timedelta(days=1)).date())
            if current_btc_session != btc_session_str:
                current_btc_session = btc_session_str
                btc_trades_today = 0
                state_changed = True

            # ==========================================
            # 1. NIFTY 50 ENGINE (Mon-Fri 9:25 - 15:15 IST)
            # ==========================================
            is_nifty_hours = (now.weekday() < 5) and (
                (now.hour == 9 and now.minute >= 25)
                or (10 <= now.hour <= 14)
                or (now.hour == 15 and now.minute <= 15)
            )

            if is_nifty_hours:
                if nifty_trade:
                    ltp, opt_high, opt_low = feed.get_option_live_ticks(nifty_trade["security_id"])
                    if ltp > 0:
                        if not nifty_trade["tp1_hit"] and opt_high >= nifty_trade["tp1"]:
                            nifty_trade["tp1_hit"] = True
                            state_changed = True
                            send_telegram(f"{HEADER}Trade : {nifty_trade['symbol']}\nTP-1 hit : {nifty_trade['tp1']:.2f}")
                        if not nifty_trade["tp2_hit"] and opt_high >= nifty_trade["tp2"]:
                            nifty_trade["tp2_hit"] = True
                            state_changed = True
                            send_telegram(f"{HEADER}Trade : {nifty_trade['symbol']}\nTP-2 hit : {nifty_trade['tp2']:.2f}")
                        if opt_high >= nifty_trade["tp3"]:
                            send_telegram(
                                f"{HEADER}Trade : {nifty_trade['symbol']}\n"
                                f"TP-3 hit : {nifty_trade['tp3']:.2f}\n"
                                f"Full target hit\n"
                                f"Trade close profitably"
                            )
                            nifty_trade = None
                            state_changed = True
                        elif opt_low <= nifty_trade["sl"] and not nifty_trade["tp1_hit"]:
                            send_telegram(
                                f"{HEADER}Trade : {nifty_trade['symbol']}\n"
                                f"SL hit : {nifty_trade['sl']:.2f}\n"
                                f"Trade loss"
                            )
                            nifty_trade = None
                            state_changed = True
                        elif ltp <= nifty_trade["sl"]:
                            send_telegram(
                                f"{HEADER}Trade : {nifty_trade['symbol']}\n"
                                f"SL hit : {nifty_trade['sl']:.2f}\n"
                                f"Trade loss"
                            )
                            nifty_trade = None
                            state_changed = True
                elif nifty_trades_today < 3 and not (now.hour == 15 and now.minute >= 0):
                    spot_df = feed.get_intraday_candles(security_id="13", interval="5", days_back=4)
                    if len(spot_df) >= 25:
                        closed_df = spot_df.iloc[:-1]
                        ts = closed_df.iloc[-1]["timestamp"]
                        ts_str = str(ts)
                        if ts.date() == now.date() and last_nifty_candle != ts_str:
                            last_nifty_candle = ts_str
                            state_changed = True
                            pdh, pdl = feed.get_daily_prev_hl("^NSEI")
                            signal = nifty_engine.evaluate_spot_signal(closed_df, pdh, pdl)
                            if signal:
                                spot_close = float(closed_df.iloc[-1]["close"])
                                strike_info = feed.select_strike_above_180(spot_close, option_type=signal["direction"])
                                if strike_info:
                                    opt_df = feed.get_intraday_candles(security_id=strike_info["security_id"], interval="5", days_back=2)
                                    if len(opt_df) >= 12:
                                        risk = nifty_engine.validate_option_entry(opt_df.iloc[:-1], strike_info["ltp"])
                                        if risk:
                                            nifty_trades_today += 1
                                            entry_val = risk["entry"]
                                            sl_val = risk["sl"]
                                            sl_pts = risk["sl_pts"]
                                            tp1_val = risk["tp1"]
                                            tp2_val = risk["tp2"]
                                            tp3_val = risk["tp3"]
                                            trade_label = f"{int(strike_info['strike'])} {strike_info['option_type']}"
                                            nifty_trade = {
                                                "security_id": strike_info["security_id"],
                                                "symbol": trade_label,
                                                "entry": entry_val,
                                                "sl": sl_val,
                                                "tp1": tp1_val,
                                                "tp2": tp2_val,
                                                "tp3": tp3_val,
                                                "tp1_hit": False,
                                                "tp2_hit": False,
                                                "sim_meta": feed._active_sim.get(strike_info["security_id"])
                                            }
                                            state_changed = True
                                            send_telegram(
                                                f"{HEADER}"
                                                f"Trade : {trade_label}\n"
                                                f"Entry : {entry_val:.2f}\n"
                                                f"SL    : {sl_val:.2f} ({sl_pts} pts)\n"
                                                f"TP-1  : {tp1_val:.2f}\n"
                                                f"TP-2  : {tp2_val:.2f}\n"
                                                f"TP-3  : {tp3_val:.2f}"
                                            )

            # ==========================================
            # 2. BTC-USD ENGINE (6:30 PM - 6:00 AM IST)
            # ==========================================
            is_btc_hours = (now.hour > 18) or (now.hour == 18 and now.minute >= 30) or (now.hour < 6)

            if btc_trade:
                btc_ltp = feed.get_btc_ltp()
                if btc_ltp > 0:
                    is_long = btc_trade["side"] == "LONG"
                    hit_tp1 = (btc_ltp >= btc_trade["tp1"]) if is_long else (btc_ltp <= btc_trade["tp1"])
                    hit_tp2 = (btc_ltp >= btc_trade["tp2"]) if is_long else (btc_ltp <= btc_trade["tp2"])
                    hit_tp3 = (btc_ltp >= btc_trade["tp3"]) if is_long else (btc_ltp <= btc_trade["tp3"])
                    hit_sl = (btc_ltp <= btc_trade["sl"]) if is_long else (btc_ltp >= btc_trade["sl"])

                    if not btc_trade["tp1_hit"] and hit_tp1:
                        btc_trade["tp1_hit"] = True
                        state_changed = True
                        send_telegram(f"{HEADER}Trade : {btc_trade['symbol']}\nTP-1 hit : {btc_trade['tp1']:.2f}")
                    elif not btc_trade["tp2_hit"] and hit_tp2:
                        btc_trade["tp2_hit"] = True
                        state_changed = True
                        send_telegram(f"{HEADER}Trade : {btc_trade['symbol']}\nTP-2 hit : {btc_trade['tp2']:.2f}")
                    elif hit_tp3:
                        send_telegram(
                            f"{HEADER}Trade : {btc_trade['symbol']}\n"
                            f"TP-3 hit : {btc_trade['tp3']:.2f}\n"
                            f"Full target hit\n"
                            f"Trade close profitably"
                        )
                        btc_trade = None
                        state_changed = True
                    elif hit_sl:
                        send_telegram(
                            f"{HEADER}Trade : {btc_trade['symbol']}\n"
                            f"SL hit : {btc_trade['sl']:.2f}\n"
                            f"Trade loss"
                        )
                        btc_trade = None
                        state_changed = True
            elif is_btc_hours and btc_trades_today < 4:
                btc_df = feed.get_intraday_candles(security_id="BTC-USD", interval="5", days_back=4)
                if len(btc_df) >= 25:
                    closed_btc = btc_df.iloc[:-1]
                    btc_ts_str = str(closed_btc.iloc[-1]["timestamp"])
                    if last_btc_candle != btc_ts_str:
                        last_btc_candle = btc_ts_str
                        state_changed = True
                        b_pdh, b_pdl = feed.get_daily_prev_hl("BTC-USD")
                        b_sig = btc_engine.evaluate_spot_signal(closed_btc, b_pdh, b_pdl)
                        if b_sig:
                            btc_trades_today += 1
                            side = "LONG" if b_sig["direction"] == "CE" else "SHORT"
                            entry_v, sl_v, sl_p, tp1_v, tp2_v, tp3_v = calculate_btc_levels(closed_btc, side)
                            trade_lbl = f"BTC {side}"
                            btc_trade = {
                                "symbol": trade_lbl,
                                "side": side,
                                "entry": entry_v,
                                "sl": sl_v,
                                "tp1": tp1_v,
                                "tp2": tp2_v,
                                "tp3": tp3_v,
                                "tp1_hit": False,
                                "tp2_hit": False
                            }
                            state_changed = True
                            send_telegram(
                                f"{HEADER}"
                                f"Trade : {trade_lbl}\n"
                                f"Entry : {entry_v:.2f}\n"
                                f"SL    : {sl_v:.2f} ({sl_p} pts)\n"
                                f"TP-1  : {tp1_v:.2f}\n"
                                f"TP-2  : {tp2_v:.2f}\n"
                                f"TP-3  : {tp3_v:.2f}"
                            )

            if state_changed:
                save_state({
                    "nifty_trade": nifty_trade,
                    "btc_trade": btc_trade,
                    "last_nifty_candle": last_nifty_candle,
                    "last_btc_candle": last_btc_candle,
                    "nifty_trades_today": nifty_trades_today,
                    "btc_trades_today": btc_trades_today,
                    "current_nifty_day": current_nifty_day,
                    "current_btc_session": current_btc_session,
                    "last_boot_day": last_boot_day
                })

            time.sleep(4)

        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(6)

if __name__ == "__main__":
    run_bot()
            
