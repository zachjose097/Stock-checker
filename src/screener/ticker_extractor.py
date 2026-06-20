import re
import finnhub
from dotenv import load_dotenv
import os
import json
from pathlib import Path
from datetime import datetime, timedelta

# Words that look like stock tickers but aren't (or are too ambiguous as bare
# uppercase words). Explicit $TICKER cashtags bypass this list entirely.

load_dotenv()
api_key = os.getenv("finhubb-api-key")

TICKER_BLOCKLIST = {
    # 2-letter noise
    "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "IF", "IN", "IS",
    "IT", "ME", "MY", "NO", "OF", "OK", "ON", "OR", "SO", "TO", "UP",
    "US", "WE", "AI", "FY", "UK", "CK", "ER", "VP", "OS", "PC", "CC",
    "AE", "IP", "II", "RL", "AX", "HS", "UN", "RF", "FD", "KV", "GB",
    "TB", "CW", "LD", "LS", "XL", "EU", "AB",
    # 3-letter common words / acronyms
    "ALL", "AND", "ANY", "ARE", "ATH", "ATL", "ATM", "AUG", "BUY",
    "BUT", "CAN", "CEO", "CFO", "COO", "CTO", "DEC", "DID", "DOW",
    "EUR", "FEB", "FED", "FRI", "FUD", "FOR", "GDP", "GET", "GOT",
    "GBP", "HAS", "HAD", "HIM", "HIS", "HER", "HOW", "IDK", "IMO",
    "IPO", "ITS", "JAN", "JPY", "JUL", "JUN", "LOL", "LOW", "MAR",
    "MAY", "MON", "NOT", "NOV", "NOW", "OCT", "OMG", "OTC", "OTM",
    "OUR", "OUT", "PUT", "SEC", "SEP", "SAT", "SUN", "THE", "THU",
    "TOO", "TUE", "TWO", "USD", "USE", "WAS", "WED", "WHO", "WHY",
    "WTF", "YET", "YOU","GPU","USA","NFA","OEM", "FAB","ARR", "DCF",
    "FCF","API", "SOC", "GPT",
    # 4-letter noise
    "ALSO", "BACK", "BEEN", "BOTH", "BULL", "BEAR", "BOND", "CALL",
    "CAME", "CASE", "CASH", "CNBC", "COME", "DATA", "DAYS", "DEAL",
    "DEBT", "DJIA", "DOES", "DONE", "EACH", "EDIT", "ELSE", "EVEN",
    "EVER", "FROM", "FOMO", "FUND", "GAIN", "GOOD", "HAVE", "HERE",
    "HIGH", "HODL", "HOLD", "HOUR", "JUST", "KEEP", "KNOW", "LAST",
    "LESS", "LIKE", "LONG", "LOOK", "LMAO", "MADE", "MAIN", "MAKE",
    "MANY", "MORE", "MOST", "MUCH", "MUST", "NEXT", "NYSE", "ONCE",
    "ONLY", "OPEN", "OVER", "POST", "PUTS", "RATE", "READ", "RISK",
    "SAID", "SAME", "SAYS", "SEES", "SEEM", "SELL", "SUCH", "TAKE",
    "THAN", "THAT", "THEM", "THEN", "THEY", "THIS", "TIME", "TLDR",
    "VERY", "WANT", "WAYS", "WEEK", "WELL", "WENT", "WERE", "WHAT",
    "WHEN", "YOUR", "YEAR", "YOLO", "APAC","DYOR","ASIC","MEMS","CAGR",
    # 5-letter noise
    "ABOUT", "AFTER", "AGAIN", "ASSET", "BELOW", "BONDS", "CALLS",
    "CLOSE", "COULD", "COVID", "DOING", "EVERY", "FDIC", "FIRST",
    "FOMC", "FUNDS", "GAINS", "GOING", "GREAT", "GROWTH", "HOURS",
    "INDEX", "KNOWN", "LARGE", "LATER", "LOWER", "MEANS", "MIGHT",
    "MONTH", "MOVED", "NEVER", "OFTEN", "OTHER", "PRICE", "PUTS",
    "RATES", "READS", "RIGHT", "RISKS", "SAYS", "SEEMS", "SEVEN",
    "SHALL", "SHARE", "SINCE", "SMALL", "STILL", "STOCK", "TAXES",
    "THEIR", "THERE", "THESE", "THOSE", "THREE", "TIRED", "TODAY",
    "TOTAL", "TRADE", "UNDER", "UNTIL", "USING", "VALUE", "VIEWS",
    "WHERE", "WHICH", "WHILE", "WITH", "WOULD", "WROTE", "YEARS",
    # Market indices / broad ETFs — not individual stocks
    "VIX", "SPX", "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT",
    # Crypto (separate asset class)
    "BTC", "ETH",
    # Reddit/social slang
    "DD", "TA", "WSB", "EOD", "EOM", "EOW",
    # Common finance acronyms that aren't tickers
    "ETF", "ROI", "ROE", "ROA", "EPS", "EV", "PE",
}

def get_us_tickers():

    client = finnhub.Client(api_key)
    json_path = Path(__file__).parent.parent.parent / "us_tickers.json"

    file_exists = os.path.exists(json_path)
    last_fetched = datetime.fromtimestamp(os.path.getmtime(json_path)) if file_exists else None

    if not file_exists or datetime.now() - last_fetched > timedelta(hours=24 * 7):
        us_stocks = client.stock_symbols("US")
        us_tickers = []
        for stock in us_stocks:
            us_tickers.append(stock["symbol"])

        with open(json_path, "w") as f:
            json.dump(sorted(us_tickers), f, indent=2)

    else:
        with open(json_path, "r") as f:
            us_tickers = json.load(f)

    return us_tickers

# Matches $TSLA-style cashtags; group(1) captures just the symbol without the $
cashtag_re = re.compile(r"\$([A-Z]{1,5})")
# Matches standalone all-caps words like AAPL; \b ensures we don't clip longer words
bare_re = re.compile(r"\b([A-Z]{2,5})\b")

def extract_tickers_cashtag(text):
    """Return ticker symbolfor all tickers found"""

    tickers = set()

    # Find text that matches cashtag regex
    for match in cashtag_re.finditer(text):
        # match.group(0) returns the full match of the regex
        # match.group(1) returns only the match inside the re parenthesis
        ticker = match.group(1)
        tickers.add(ticker)

    return tickers

def extract_tickers_base(text, tickers):

    us_tickers = get_us_tickers()
    # Catch bare uppercase words, skipping positions already caught by cashtags
    cleaned = cashtag_re.sub(" ", text)
    for m in bare_re.finditer(cleaned):
        ticker = m.group(1)
        if (ticker not in us_tickers) or (ticker in TICKER_BLOCKLIST):
            continue
        tickers.add(ticker)

    return tickers
