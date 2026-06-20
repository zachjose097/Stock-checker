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

    def evaluate_rules(self, df):

        close_latest = df.iloc[-1]["Close"]
        ema_20_latest = df.iloc[-1]["ema_20"]
        date_latest = df.iloc[-1]["Date"]

        # Track if price has ever traded above the 20EMA since entry
        if close_latest > ema_20_latest:
            self.ever_above_ema20 = True

        # Rule 3 - full exit if price breaks below 20EMA after being above it
        if close_latest < ema_20_latest and self.ever_above_ema20:
            return "Sell all shares"

        # Rule 1 - round number trim
        if self.exit_price is not None:
            if close_latest >= self.exit_price:
                return f"Trim 20% - Rule 1 target {self.exit_price} hit"

        # Not enough bars since entry for Rule 2 to be meaningful
        bars_since_entry = len(df[df["Date"] >= self.entry_date])
        if bars_since_entry < 3:
            return "No action"

        # Rule 2 - trim if 3+ closes above 4EMA-high, now closing below it
        ema_4_latest = df.iloc[-1]["ema_4"]
        df["above_ema4"] = df["Close"] > df["ema_4"]

        if close_latest < ema_4_latest:
            if df.iloc[-4:-1]["above_ema4"].all():
                if self.last_trim is None or (date_latest - self.last_trim).days >= 2:
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
    exit_price = entry_price * 1.3
    ladder = [2, 5, 10, 20, 50, 100, 150, 200, 300, 500, 1000, 1500, 2000, 2500]

    for i in range(len(ladder)):
        if ladder[i] >= exit_price:
            return ladder[i]

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

if __name__ == "__main__":

    path = os.path.join(os.path.dirname(__file__), "..", "..", "json_files", "positions.json")

    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump({}, f)

    with open(path) as f:
        positions = json.load(f)

    # Only prompt for new position when run manually with --add flag
    # GitHub Actions runs without --add so this block is skipped automatically
    if "--add" in sys.argv:
        if input("Do you want to enter a new position?(y/n) ") == "y":
            ticker, position = add_position()
            positions[ticker] = position

    for key, value_dict in positions.items():
        sl = Sell_decision(key, value_dict)
        action = sl.main()
        positions[key]["last_trim"] = sl.last_trim.strftime("%Y-%m-%d") if sl.last_trim else None
        positions[key]["ever_above_ema20"] = sl.ever_above_ema20

    with open(path, "w") as f:
        json.dump(positions, f)
