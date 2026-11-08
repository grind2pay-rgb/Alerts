"""Wickless candle alerts -> Telegram. Runs once per call (for GitHub Actions)."""
import json
import os
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

# ---------- settings ----------
SYMBOLS = {                   # name -> Yahoo Finance ticker
    "AUDJPY": "AUDJPY=X",
    # "EURUSD": "EURUSD=X",
    # "GBPUSD": "GBPUSD=X",
}
TIMEFRAMES = ["15m"]          # any of: 5m, 15m, 30m, 1h, 4h
# "open_side": bull candle has no lower wick (open = low), bear candle has no upper wick (open = high)
# "both":      no wick on either side
WICKLESS_MODE = "open_side"
LOOKBACK = 2                  # check the last N closed candles (covers delayed runs)
# ------------------------------

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
TOL = float(os.environ.get("TOL", "0"))   # price tolerance; 0 = exact match
STATE = Path("state.json")

SOURCES = {  # timeframe -> (yahoo interval, history period, resample rule)
    "5m": ("5m", "5d", None),
    "15m": ("15m", "30d", None),
    "30m": ("30m", "30d", None),
    "1h": ("1h", "60d", None),
    "4h": ("1h", "60d", "4h"),
}


def send(msg):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg},
        timeout=15,
    )
    r.raise_for_status()


def get_candles(ticker, tf):
    interval, period, rule = SOURCES[tf]
    df = yf.download(ticker, period=period, interval=interval,
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = df.index.tz_convert("UTC")
    if rule:
        df = df.resample(rule).agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
        ).dropna()
    length = pd.Timedelta(tf)
    now = pd.Timestamp.now(tz="UTC")
    return df[df.index + length <= now]   # closed candles only


def classify(o, h, l, c):
    if c > o:
        ok = (o - l) <= TOL
        if WICKLESS_MODE == "both":
            ok = ok and (h - c) <= TOL
        return "Bullish" if ok else None
    if c < o:
        ok = (h - o) <= TOL
        if WICKLESS_MODE == "both":
            ok = ok and (c - l) <= TOL
        return "Bearish" if ok else None
    return None


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    for name, ticker in SYMBOLS.items():
        for tf in TIMEFRAMES:
            key = f"{name}|{tf}"
            try:
                df = get_candles(ticker, tf).tail(LOOKBACK)
                done = state.get(key, "")
                for t, row in df.iterrows():
                    stamp = t.isoformat()
                    if done and stamp <= done:
                        continue
                    kind = classify(row["Open"], row["High"], row["Low"], row["Close"])
                    if kind:
                        send(f"{name} {tf}: {kind} wickless candle\n"
                             f"O {row['Open']:.5g}  H {row['High']:.5g}  "
                             f"L {row['Low']:.5g}  C {row['Close']:.5g}\n"
                             f"Candle {t:%Y-%m-%d %H:%M} UTC")
                        done = stamp
                state[key] = done
            except Exception as e:
                print(f"{key}: {e}")
    STATE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
