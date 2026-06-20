from dotenv import load_dotenv
import os
from pathlib import Path
from datetime import date, timedelta
from requests_cache import CachedSession
from ..config import adanos_ticker_limit, adanos_timedelta

load_dotenv()
api_key = os.getenv("ADANOS_API_KEY")
if not api_key:
    raise RuntimeError("ADANOS_API_KEY not set in environment")

# Date range and number of trending tickers to fetch from each source
to_date = date.today()
from_date = to_date - timedelta(days = adanos_timedelta)
limit = adanos_ticker_limit

cache_dir = Path(__file__).parent.parent / "Cached_sessions"
os.makedirs(cache_dir, exist_ok = True)

class AdanosScraper:

    def __init__(self, source):
        self.base_url = f"https://api.adanos.org/{source}/stocks"
        self.headers = {"X-API-Key": api_key}
        self.params = {"type": "stock", "from": from_date, "to": to_date, "limit": limit}
        self.source = source
        self.session = CachedSession(cache_dir / f"adanos_{source}_cache", expire_after=3600*24)

    def get_trending(self):
        '''Get n trending tickers from reddit based on a date range.'''

        try:
            url = self.base_url + "/v1/trending"
            response = self.session.get(url, headers = self.headers, params = self.params)
            response.raise_for_status()
        
        except Exception as e:
            print(f"Provide valid source name out of (reddit/x/news): {e}")
            os.remove(os.path.join(cache_dir, f"adanos_{self.source}_cache.sqlite"))
            return

        data = response.json()

        stocks = self.format_json(data)

        return stocks

    def format_json(self, stocks):
        '''Returns a dict with the ticker as key, and each value being the remaining stock metadata from the API response.'''

        stocks_formatted = {}
        for stock in stocks:
            ticker = stock.get("ticker")
            stock.pop("ticker", None)

            stocks_formatted[ticker] = stock

        return stocks_formatted

if __name__ == "__main__":
    obj = AdanosScraper("substack")
    print(obj.get_trending())

