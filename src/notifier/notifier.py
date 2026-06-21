import pandas as pd
import yfinance as yf
import os
import json
import requests
import sys

ntfy_url = "https://ntfy.sh/zach-sell-notifier"

class Sell_decision:
    

    def __init__(self, key, value_dict):
        self.ticker = key
        self.last_trim = pd.to_datetime(value_dict["last_trim"]) if value_dict["last_trim"] else None
        self.entry_price = value_dict["entry_price"]
        self.ever_above_ema20 = value_dict["ever_above_ema20"]
        self.entry_date = pd.to_datetime(value_dict["entry_date"])
        self.exit_price = value_dict["exit_price"]

    def get_charts(self, timeframe = "1d"):
        df = yf.download(self.ticker, period = "6mo", interval = timeframe)
        return df

    def get_ema(self, df, span, source):

        values = df[source].tolist()
        k = 2 / (span + 1)

        ema_values = [values[0]]

        for i in range(1, len(values)):
            ema_current = values[i] * k + ema_values[i - 1] * (1 - k)
            ema_values.append(ema_current)

        return pd.Series(ema_values, index = df.index)

    def _can_trim(self, date_latest):
        # Shared 2-day cooldown so a held condition trims once, not on every run.
        return self.last_trim is None or (date_latest - self.last_trim).days >= 2

    def evaluate_rules(self, df):

        # Normalise to tz-naive timestamps so comparisons with entry_date (always tz-naive)
        # don't raise when an intraday timeframe returns tz-aware bars.
        if getattr(df["Date"].dt, "tz", None) is not None:
            df = df.copy()
            df["Date"] = df["Date"].dt.tz_localize(None)

        close_latest = df.iloc[-1]["Close"]
        ema_20_latest = df.iloc[-1]["ema_20"]
        ema_4_latest = df.iloc[-1]["ema_4"]
        date_latest = df.iloc[-1]["Date"]

        # Everything is measured from entry; the post-entry bars are contiguous at the tail.
        since_entry = df[df["Date"] >= self.entry_date]

        # Track if price has ever traded above the 20EMA since entry. Scan every bar
        # since entry so this is correct on the first evaluation, not just across runs.
        if (since_entry["Close"] > since_entry["ema_20"]).any():
            self.ever_above_ema20 = True

        # Rule 3 - full exit if price breaks below 20EMA after being above it. Checked
        # first on purpose: a trend break is a stronger signal than a profit-target trim.
        if close_latest < ema_20_latest and self.ever_above_ema20:
            return "Sell all shares"

        # Rule 1 - round number trim once the target is reached.
        if self.exit_price is not None and close_latest >= self.exit_price:
            if self._can_trim(date_latest):
                self.last_trim = date_latest
                return f"Trim 20% - Rule 1 target {self.exit_price} hit"

        # Not enough bars since entry for Rule 2 to be meaningful.
        if len(since_entry) < 4:
            return "No action"

        # Rule 2 - trim if the 3 prior bars closed above the 4EMA(high) and we now close
        # below it. Slice the post-entry window so pre-entry bars never leak in.
        if close_latest < ema_4_latest:
            prior3 = since_entry.iloc[-4:-1]
            if (prior3["Close"] > prior3["ema_4"]).all() and self._can_trim(date_latest):
                self.last_trim = date_latest
                return "Trim 20% of shares - Rule 2"

        return "No action"

    def notify(self, message):
        response = requests.post(ntfy_url, data = message)
        response.raise_for_status()

        return

    def main(self):
        df = self.get_charts().reset_index()
        df.columns = df.columns.get_level_values(0)
        df = df.sort_values(by = "Date", ascending = True)
        df["ema_4"] = self.get_ema(df, 4, "High")
        df["ema_20"] = self.get_ema(df, 20, "Close")

        try:
            action = self.evaluate_rules(df)
            self.notify(f"Action for ticker {self.ticker} is: {action}")
        except Exception as e:
            self.notify(f"Error processig ticker {self.ticker}: {e}")
            action = "Error"

        return action

def get_exit_price(entry_price):
    # First round-number rung at or above a 30% gain. Canonical for both the CLI and the
    # Streamlit app — app.py imports this rather than keeping its own copy. None above the
    # top rung simply disables Rule 1 for that position.
    exit_price = entry_price * 1.3
    ladder = [2, 5, 10, 20, 50, 100, 150, 200, 300, 500, 1000, 1500, 2000, 2500, 3000, 4000, 5000]

    for rung in ladder:
        if rung >= exit_price:
            return rung

    return None

def add_position():

    ticker = input("Ticker symbol: ")
    entry_price = input("Entry price: ")
    entry_date = input("Entry date: ")
    number_of_shares = input("Number of shares: ")
    position = {"entry_price": float(entry_price),
                "entry_date": entry_date,
                "number_of_shares": float(number_of_shares),
                "last_trim": None,
                "ever_above_ema20": False,
                "exit_price": get_exit_price(float(entry_price))}

    return ticker, position
