import time
import pandas as pd
from datetime import datetime

from smc_engine import SMCEngine
from market_feed import MarketFeed
from telegram_bot import TelegramNotifier

BOT_TOKEN = "9227619823:AAEhVHQg7h2JqSu1zQgn2IRIwEMOapfqKSQ"
CHAT_ID = "7107919128"
ASSETS = ["NIFTY 50", "BTC-USD"]
POLL_INTERVAL = 10  # Seconds

def main():
    notifier = TelegramNotifier(BOT_TOKEN, CHAT_ID)
    engine = SMCEngine(ema_fast=20, ema_slow=50)
    
    # Track positions per asset
    active_positions = {}  # { asset: trade_dict }

    print("=" * 50)
    print("🚀 PAWAN AI — SERVER WORKER RUNNING (20/50 EMA SCALPER)")
    print("=" * 50)
    notifier.send_message("🟢 *PAWAN AI Server Worker Started* (20/50 EMA Scalper Active)")

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
                            msg = (
                                f"🎯 *PAWAN AI — TARGET 1 HIT (1:1)* 🎯\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"Asset: {asset}\n"
                                f"Signal: {direction}\n"
                                f"Target 1: {pos['tp1']}\n"
                                f"Current Price: {curr_price:.2f}\n"
                                f"Action: Book 50% profit & Trail SL to Entry ({pos['entry']})\n"
                                f"━━━━━━━━━━━━━━━━━━━"
                            )
                            notifier.send_message(msg)

                    # Check Target 2 (Full Target)
                    tp2_hit = (curr_high >= pos['tp2']) if direction == 'BUY_CE' else (curr_low <= pos['tp2'])
                    if tp2_hit:
                        print(f"[{asset}] 🏁 TARGET 2 HIT @ {pos['tp2']}")
                        msg = (
                            f"🏁 *PAWAN AI — FULL TARGET 2 HIT (1:2)* 🏁\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"Asset: {asset}\n"
                            f"Signal: {direction}\n"
                            f"Target 2: {pos['tp2']}\n"
                            f"Trade Status: Fully Booked & Closed ✅\n"
                            f"━━━━━━━━━━━━━━━━━━━"
                        )
                        notifier.send_message(msg)
                        del active_positions[asset]
                        continue

                    # Check Stop Loss
                    sl_hit = (curr_low <= pos['sl']) if direction == 'BUY_CE' else (curr_high >= pos['sl'])
                    if sl_hit:
                        print(f"[{asset}] 🛑 STOP LOSS HIT @ {pos['sl']}")
                        msg = (
                            f"🛑 *PAWAN AI — STOP LOSS HIT* 🛑\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"Asset: {asset}\n"
                            f"Signal: {direction}\n"
                            f"Exit Price: {pos['sl']}\n"
                            f"Trade Status: Closed\n"
                            f"━━━━━━━━━━━━━━━━━━━"
                        )
                        notifier.send_message(msg)
                        del active_positions[asset]
                        continue

                # -------------------------------------------------------------
                # 2. SCAN NEW TRADE (If no trade active for this asset)
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

                        msg = (
                            f"🚀 *PAWAN AI — 20/50 EMA SCALPER*\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 *Asset:* {trade['asset']}\n"
                            f"⚡ *Signal:* {trade['direction']}\n"
                            f"📍 *Entry:* {trade['entry']}\n"
                            f"🛑 *Stop Loss:* {trade['sl']}\n"
                            f"🎯 *Target 1 (1:1):* {trade['tp1']}\n"
                            f"🏁 *Target 2 (1:2):* {trade['tp2']}\n"
                            f"📈 *EMA 20:* {trade.get('ema_20', 'N/A')} | *EMA 50:* {trade.get('ema_50', 'N/A')}\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"Status: Pullback Bounce Confirmed"
                        )
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
