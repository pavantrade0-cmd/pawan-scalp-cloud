import time
import datetime
import yfinance as yf
import pandas as pd
from smc_engine import SMCEngine
from telegram_bot import TelegramNotifier

tg = TelegramNotifier(
    bot_token="9227619823:AAEhVHQg7h2JqSu1zQgn2IRIwEMOapfqKSQ",
    chat_id="7107919128"
)
engine = SMCEngine()

ASSETS = [
    {"display": "BTC-USD", "symbol": "BTC-USD", "is_crypto": True},
    {"display": "NIFTY 50", "symbol": "^NSEI", "is_crypto": False}
]

# Track active state per symbol
active_trades = {a["display"]: None for a in ASSETS}
last_traded_candle = {a["display"]: None for a in ASSETS}

def is_market_open():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
    # Mon-Fri
    if now_ist.weekday() >= 5:
        return False
    market_start = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= now_ist <= market_end

def fetch_data(symbol):
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="3d", interval="5m")
        if df.empty:
            return pd.DataFrame()
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception as e:
        print(f"[FETCH ERROR {symbol}]: {e}")
        return pd.DataFrame()

print("🚀 PAWAN 24/7 CLOUD WORKER ACTIVE...")
tg.send_message("🌐 <b>PAWAN CLOUD SCALPER 24/7 ONLINE</b>\nBot monitoring BTC-USD & NIFTY 50 with Dual Targets (TP1: 1:1, TP2: 1:2).")

while True:
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
        
        # Current forming candle
        curr_bar = df.iloc[-1]
        live_price = float(curr_bar['close'])
        curr_high = float(curr_bar['high'])
        curr_low = float(curr_bar['low'])

        # ---------------- 1. MANAGE ACTIVE TRADE ----------------
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
                # Check TP1 using high of current candle (wick touch qualifies)
                if not tp1_hit and curr_high >= tp1:
                    trade["tp1_hit"] = True
                    tg.send_partial_tp_alert(
                        symbol=name,
                        direction=direction,
                        exit_price=tp1,
                        gain_pts=risk * 1.0
                    )

                # Check TP2 Full Target
                if curr_high >= tp2:
                    tg.send_exit_alert(
                        symbol=name,
                        direction=direction,
                        outcome=f"FULL TARGET HIT (1:2) (+{risk * 2:.0f} pts)",
                        exit_price=tp2
                    )
                    active_trades[name] = None
                    continue

                # Check Stop Loss
                if curr_low <= sl:
                    tg.send_exit_alert(
                        symbol=name,
                        direction=direction,
                        outcome=f"STOP LOSS HIT (-{risk:.0f} pts)",
                        exit_price=sl
                    )
                    active_trades[name] = None
                    continue

            elif direction == "BUY PE":
                # Check TP1 using low of current candle (wick touch qualifies)
                if not tp1_hit and curr_low <= tp1:
                    trade["tp1_hit"] = True
                    tg.send_partial_tp_alert(
                        symbol=name,
                        direction=direction,
                        exit_price=tp1,
                        gain_pts=risk * 1.0
                    )

                # Check TP2 Full Target
                if curr_low <= tp2:
                    tg.send_exit_alert(
                        symbol=name,
                        direction=direction,
                        outcome=f"FULL TARGET HIT (1:2) (+{risk * 2:.0f} pts)",
                        exit_price=tp2
                    )
                    active_trades[name] = None
                    continue

                # Check Stop Loss
                if curr_high >= sl:
                    tg.send_exit_alert(
                        symbol=name,
                        direction=direction,
                        outcome=f"STOP LOSS HIT (-{risk:.0f} pts)",
                        exit_price=sl
                    )
                    active_trades[name] = None
                    continue

            continue

        # ---------------- 2. SCAN FOR NEW SETUP IF FLAT ----------------
        setup = engine.scan_for_setups(df)
        if setup.get("signal") in ["BUY CE", "BUY PE"]:
            c_time = setup.get("candle_time")
            if last_traded_candle[name] != c_time:
                last_traded_candle[name] = c_time
                setup["tp1_hit"] = False  # Track TP1
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

    time.sleep(15)  # 15s scan loop for cloud responsiveness
