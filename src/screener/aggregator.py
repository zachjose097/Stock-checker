from datetime import datetime, timedelta
import json
import os
import yfinance as yf
from pathlib import Path

_CAP_CACHE_PATH = os.path.join(Path(__file__).parents[2], "json_files", "market_cap_cache.json")
_CAP_CACHE_TTL  = timedelta(days=7)

from .scrapers.substack import SubstackScraper
from .scrapers.twitter import TwitterScraper
from .scrapers.adanos import AdanosScraper
from .config import twitter_accounts, substack_feeds, post_timedelta

class Aggregator:

    def __init__(self, source):
        self.source = source

    def collect(self, scraper_fn, accounts):
        ''' Fetch the posts from an account depending on the source (X, reddit, substack)'''

        all_posts = []
        for account in accounts:
            account_posts = scraper_fn(account)
            for post in account_posts:
                all_posts.append(post)
        return all_posts

    def filter_posts(self, posts):
        '''Filter the posts that were created in the last x days'''
        
        cutoff = datetime.now() - timedelta(days = post_timedelta)
        filtered_posts = []
        for post in posts:
            if datetime.strptime(post["created_at"], "%Y/%m/%d") >= cutoff:
                filtered_posts.append(post)
        return filtered_posts

    def summarize_tickers(self, posts):
        ticker_summary = {}
        for post in posts:
            account = post["account"]
            for ticker in post.get("tickers", []):
                if ticker not in ticker_summary:
                    ticker_summary[ticker] = {"total": 0, "by_creator": {}}
                ticker_summary[ticker]["total"] += 1
                ticker_summary[ticker]["by_creator"][account] = ticker_summary[ticker]["by_creator"].get(account, 0) + 1
        return ticker_summary

    def score_adanos_tickers(self, top_tickers):
        scored = []
        for ticker, info in top_tickers.items():
            bullish = info.get("bullish_pct", 0)
            bearish = info.get("bearish_pct", 0)
            bull_bear_ratio = round(bullish / bearish, 2) if bearish > 0 else None

            history = info.get("trend_history", [])
            if len(history) >= 2:
                trend_direction = "uptrend" if history[-1] > history[0] else "downtrend"
            else:
                trend_direction = "unknown"

            scored.append({
                "ticker": ticker,
                "buzz_score": info.get("buzz_score"),
                "bull_bear_ratio": bull_bear_ratio,
                "trend_direction": trend_direction,
            })

        return sorted(scored, key=lambda x: x["buzz_score"] or 0, reverse=True)

    def combine_adanos_sources(self, reddit, x, news):
        combined = {}
        for source in [reddit, x, news]:
            for entry in source:
                ticker = entry["ticker"]
                if ticker not in combined:
                    combined[ticker] = {**entry, "source_count": 0, "buzz_scores": []}
                combined[ticker]["source_count"] += 1
                if entry.get("buzz_score") is not None:
                    combined[ticker]["buzz_scores"].append(entry["buzz_score"])

        result = []
        for ticker, info in combined.items():
            avg_buzz = round(sum(info["buzz_scores"]) / len(info["buzz_scores"]), 2) if info["buzz_scores"] else 0
            result.append({
                "ticker": ticker,
                "source_count": info["source_count"],
                "avg_buzz_score": avg_buzz,
                "bull_bear_ratio": info.get("bull_bear_ratio"),
                "trend_direction": info.get("trend_direction"),
            })

        return sorted(result, key=lambda x: (x["source_count"], x["avg_buzz_score"]), reverse=True)

    def get_market_cap_category(self, tickers):
        # Load persistent cache
        persistent = {}
        if os.path.exists(_CAP_CACHE_PATH):
            try:
                with open(_CAP_CACHE_PATH) as f:
                    persistent = json.load(f)
            except Exception:
                persistent = {}

        now = datetime.now()

        def _is_fresh(entry):
            try:
                return datetime.fromisoformat(entry["cached_at"]) >= now - _CAP_CACHE_TTL
            except Exception:
                return False

        # Only hit yfinance for tickers absent from or expired in the persistent cache
        uncached = [t for t in tickers if t not in persistent or not _is_fresh(persistent[t])]

        if uncached:
            data = yf.Tickers(" ".join(uncached))
            for ticker in uncached:
                try:
                    cap = data.tickers[ticker].info.get("marketCap")
                    try:
                        cap = float(cap) if cap is not None else None
                    except (TypeError, ValueError):
                        cap = None
                    if cap is None:
                        category = "unknown"
                    elif cap >= 200_000_000_000:
                        category = "mega"
                    elif cap >= 10_000_000_000:
                        category = "large"
                    elif cap >= 2_000_000_000:
                        category = "mid"
                    elif cap >= 300_000_000:
                        category = "small"
                    else:
                        category = "micro"
                    persistent[ticker] = {"market_cap": cap, "cap_category": category, "cached_at": now.isoformat()}
                except Exception:
                    persistent[ticker] = {"market_cap": None, "cap_category": "unknown", "cached_at": now.isoformat()}

            os.makedirs(os.path.dirname(_CAP_CACHE_PATH), exist_ok=True)
            with open(_CAP_CACHE_PATH, "w") as f:
                json.dump(persistent, f, indent=2)

        result = {}
        for ticker in tickers:
            entry = persistent.get(ticker, {"market_cap": None, "cap_category": "unknown"})
            result[ticker] = entry
        return result

    def merge_ticker_summaries(self, top_tickers, ticker_summary_x, ticker_summary_substack):
        by_ticker = {entry["ticker"]: entry for entry in top_tickers}
        accounts_seen = {}  # ticker -> set of distinct accounts across x + substack
        account_mentions = {}  # ticker -> {account: total mentions across x + substack}

        for source_summary in [ticker_summary_x, ticker_summary_substack]:
            for ticker, summary in source_summary.items():
                if ticker not in by_ticker:
                    by_ticker[ticker] = {
                        "ticker": ticker,
                        "source_count": 0,
                        "avg_buzz_score": 0,
                        "bull_bear_ratio": None,
                        "trend_direction": "unknown",
                    }
                by_ticker[ticker]["source_count"] += 1
                by_ticker[ticker]["mentions"] = by_ticker[ticker].get("mentions", 0) + summary["total"]
                accounts_seen.setdefault(ticker, set()).update(summary["by_creator"].keys())
                # Accumulate per-account counts so we can surface the single account that
                # mentioned this ticker most across X and Substack combined.
                per_account = account_mentions.setdefault(ticker, {})
                for account, count in summary["by_creator"].items():
                    per_account[account] = per_account.get(account, 0) + count

        for ticker, acct_set in accounts_seen.items():
            by_ticker[ticker]["unique_accounts"] = len(acct_set)

        for ticker, per_account in account_mentions.items():
            top_account, top_count = max(per_account.items(), key=lambda kv: kv[1])
            by_ticker[ticker]["top_account"] = top_account
            by_ticker[ticker]["top_account_mentions"] = top_count

        return sorted(by_ticker.values(), key=lambda x: (x["source_count"], x["avg_buzz_score"]), reverse=True)

    def recommend_top_tickers(self, top_tickers, n=15):
        def score(entry):
            buzz = entry.get("avg_buzz_score") or 0
            ratio = entry.get("bull_bear_ratio") or 1.0
            trend_bonus = 10 if entry.get("trend_direction") == "uptrend" else 0
            return buzz * ratio + trend_bonus

        grouped = {}
        for entry in top_tickers:
            cap = entry.get("cap_category", "unknown")
            grouped.setdefault(cap, []).append(entry)

        return {
            cap: [e["ticker"] for e in sorted(entries, key=score, reverse=True)[:n]]
            for cap, entries in grouped.items()
        }

    def aggregate(self):

        all_x_posts = self.collect(TwitterScraper().get_tweets, twitter_accounts)
        all_substack_posts = self.collect(SubstackScraper().scrape, substack_feeds)

        ticker_summary_x = self.summarize_tickers(self.filter_posts(all_x_posts))
        ticker_summary_substack = self.summarize_tickers(self.filter_posts(all_substack_posts))

        top_reddit_tickers = self.score_adanos_tickers(AdanosScraper("reddit").get_trending())
        top_x_tickers = self.score_adanos_tickers(AdanosScraper("x").get_trending())
        top_news_tickers = self.score_adanos_tickers(AdanosScraper("news").get_trending())

        top_tickers = self.combine_adanos_sources(top_reddit_tickers, top_x_tickers, top_news_tickers)
        top_tickers = self.merge_ticker_summaries(top_tickers, ticker_summary_x, ticker_summary_substack)

        return top_tickers

if __name__ == "__main__":
    top_tickers = Aggregator("combined").aggregate()
    print(top_tickers)
