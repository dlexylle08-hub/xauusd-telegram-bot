import os
import time
from datetime import datetime, timezone, timedelta
import threading
from flask import Flask
import requests
import pandas as pd
import yfinance as yf

# --- CONFIGURATION FROM ENVIRONMENT VARIABLES ---
TELEGRAM_BOT_TOKEN = os.getenv(8971343489:AAGpdAS8e8X4WrWMSr0k4pnT_Kn9xJrzors)
TELEGRAM_CHAT_ID   = os.getenv(1654653371)

SYMBOL             = "GC=F"
SWEEP_LOOKBACK     = 20
RSI_PERIOD         = 14
RSI_OVERSOLD       = 35.0
RSI_OVERBOUGHT     = 65.0
ATR_PERIOD         = 14
ATR_SL_MULTIPLIER  = 1.5
ATR_TP_MULTIPLIER  = 3.0

MYT_TZ             = timezone(timedelta(hours=8))
SESSION_START_MYT  = 15
SESSION_END_MYT    = 2

# --- KEEP-ALIVE WEB SERVER FOR RENDER ---
app = Flask(__name__)

@app.route("/")
def index():
    return "XAUUSD Signal Bot is active and running 24/5!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- TELEGRAM SENDER ---
def send_telegram_alert(message_html: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

# --- INDICATORS & SCANNER ---
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    delta = df["Close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100.0 - (100.0 / (1.0 + rs))

    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift(1)).abs()
    low_close = (df["Low"] - df["Close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = true_range.ewm(alpha=1 / ATR_PERIOD, min_periods=ATR_PERIOD, adjust=False).mean()
    return df

def is_within_myt_session() -> bool:
    now_myt = datetime.now(MYT_TZ)
    if now_myt.weekday() == 5 and now_myt.hour >= 5:
        return False
    if now_myt.weekday() == 6:
        return False
    return (now_myt.hour >= SESSION_START_MYT) or (now_myt.hour < SESSION_END_MYT)

def run_bot_loop():
    print("XAUUSD Signal Bot background loop started...")
    send_telegram_alert("🤖 <b>XAUUSD Cloud Bot Online!</b>\nScanning M15 Liquidity Sweeps 24/5.")
    last_bar = None

    while True:
        try:
            if is_within_myt_session():
                df = yf.download(SYMBOL, period="5d", interval="15m", progress=False)
                if df is not None and len(df) >= SWEEP_LOOKBACK + 5:
                    df = compute_indicators(df)
                    closed_bar = df.iloc[-2]
                    prior_bar  = df.iloc[-3]
                    closed_bar_time = df.index[-2]

                    if last_bar != closed_bar_time:
                        lookback_slice = df.iloc[-(SWEEP_LOOKBACK + 2):-2]
                        swing_high = float(lookback_slice["High"].max())
                        swing_low  = float(lookback_slice["Low"].min())

                        high1  = float(closed_bar["High"])
                        low1   = float(closed_bar["Low"])
                        close1 = float(closed_bar["Close"])
                        rsi1   = float(closed_bar["RSI"])
                        rsi2   = float(prior_bar["RSI"])
                        atr1   = float(closed_bar["ATR"])
                        now_str = datetime.now(MYT_TZ).strftime("%d %b %Y, %I:%M %p MYT")

                        # Bullish Sweep
                        if (low1 < swing_low) and (close1 > swing_low) and (rsi1 <= RSI_OVERSOLD or (rsi2 <= RSI_OVERSOLD and rsi1 > rsi2)):
                            raw_sl = min(low1 - (atr1 * 0.5), close1 - (atr1 * ATR_SL_MULTIPLIER))
                            sl_dist = close1 - raw_sl
                            sl = round(close1 - sl_dist, 2)
                            tp = round(close1 + (atr1 * ATR_TP_MULTIPLIER), 2)
                            rr = round((tp - close1) / sl_dist, 2) if sl_dist > 0 else 2.0
                            
                            msg = (f"🟢 <b>XAUUSD M15 — BULLISH SWEEP</b>\n\n"
                                   f"<b>Action:</b> BUY MARKET\n"
                                   f"<b>Entry:</b> <code>{close1:.2f}</code>\n"
                                   f"<b>SL:</b> <code>{sl:.2f}</code> | <b>TP:</b> <code>{tp:.2f}</code>\n"
                                   f"<b>Risk:Reward:</b> 1:{rr}\n"
                                   f"<b>Time:</b> {now_str}")
                            send_telegram_alert(msg)

                        # Bearish Sweep
                        elif (high1 > swing_high) and (close1 < swing_high) and (rsi1 >= RSI_OVERBOUGHT or (rsi2 >= RSI_OVERBOUGHT and rsi1 < rsi2)):
                            raw_sl = max(high1 + (atr1 * 0.5), close1 + (atr1 * ATR_TP_MULTIPLIER))
                            sl_dist = raw_sl - close1
                            sl = round(close1 + sl_dist, 2)
                            tp = round(close1 - (atr1 * ATR_TP_MULTIPLIER), 2)
                            rr = round((close1 - tp) / sl_dist, 2) if sl_dist > 0 else 2.0

                            msg = (f"🔴 <b>XAUUSD M15 — BEARISH SWEEP</b>\n\n"
                                   f"<b>Action:</b> SELL MARKET\n"
                                   f"<b>Entry:</b> <code>{close1:.2f}</code>\n"
                                   f"<b>SL:</b> <code>{sl:.2f}</code> | <b>TP:</b> <code>{tp:.2f}</code>\n"
                                   f"<b>Risk:Reward:</b> 1:{rr}\n"
                                   f"<b>Time:</b> {now_str}")
                            send_telegram_alert(msg)

                        last_bar = closed_bar_time
        except Exception as e:
            print(f"Loop Error: {e}")
        
        time.sleep(30)

if __name__ == "__main__":
    # Start the background trading bot loop in a separate thread
    t = threading.Thread(target=run_bot_loop, daemon=True)
    t.start()
    # Start the Flask web server on main thread
    run_flask()
