import requests
import threading

class TelegramNotifier:
    def __init__(self, bot_token: str = "9227619823:AAEhVHQg7h2JqSu1zQgn2IRIwEMOapfqKSQ", chat_id: str = "7107919128"):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send_message(self, text: str):
        def _send():
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            try:
                r = requests.post(self.base_url, json=payload, timeout=5)
                if r.status_code != 200:
                    payload.pop("parse_mode", None)
                    payload["text"] = (
                        text.replace("<b>", "")
                            .replace("</b>", "")
                            .replace("<i>", "")
                            .replace("</i>", "")
                            .replace("<code>", "")
                            .replace("</code>", "")
                    )
                    r = requests.post(self.base_url, json=payload, timeout=5)

                if r.status_code == 200:
                    print("[TELEGRAM ALERT SENT SUCCESSFULLY]")
                else:
                    print(f"[TELEGRAM API ERROR]: {r.text}")
            except Exception as e:
                print(f"[TELEGRAM NETWORK ERROR]: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def send_entry_alert(self, symbol: str, direction: str, entry: float, sl: float, tp1: float, tp2: float, reason: str):
        icon = "🟢" if "CE" in direction else "🔴"
        safe_reason = str(reason).replace("<", "&lt;").replace(">", "&gt;")

        msg = (
            f"⚡ <b>PAWAN SCALPER — NEW ENTRY</b> ⚡\n\n"
            f"📌 <b>Asset:</b> {symbol}\n"
            f"{icon} <b>Action:</b> {direction}\n"
            f"🎯 <b>Entry Price:</b> <code>{entry:,.2f}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>{sl:,.2f}</code>\n"
            f"🎯 <b>Target 1 (1:1):</b> <code>{tp1:,.2f}</code>\n"
            f"🏁 <b>Target 2 (1:2):</b> <code>{tp2:,.2f}</code>\n\n"
            f"📊 <b>Reason:</b> <i>{safe_reason}</i>\n"
            f"🔒 <i>Position locked until SL or Full Target hit.</i>"
        )
        self.send_message(msg)

    def send_partial_tp_alert(self, symbol: str, direction: str, exit_price: float, gain_pts: float):
        msg = (
            f"🎯 <b>TARGET 1 HIT (1:1) (+{gain_pts:.0f} pts)</b> 🎯\n\n"
            f"📌 <b>Asset:</b> {symbol}\n"
            f"⚡ <b>Trade Type:</b> {direction}\n"
            f"💰 <b>Trigger Price:</b> <code>{exit_price:,.2f}</code>\n\n"
            f"💡 <i>Book 50% profits or trail SL to Cost! Runner holding for Target 2...</i>"
        )
        self.send_message(msg)

    def send_exit_alert(self, symbol: str, direction: str, outcome: str, exit_price: float):
        icon = "🏁" if "FULL" in outcome or "TARGET" in outcome else "🛑"
        msg = (
            f"{icon} <b>TRADE CLOSED — {outcome}</b> {icon}\n\n"
            f"📌 <b>Asset:</b> {symbol}\n"
            f"⚡ <b>Trade Type:</b> {direction}\n"
            f"💰 <b>Exit Price:</b> <code>{exit_price:,.2f}</code>\n\n"
            f"🔄 <i>Auto-Scalper is now scanning for the next A+ setup...</i>"
        )
        self.send_message(msg)
