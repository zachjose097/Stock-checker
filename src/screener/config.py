# Substack accounts to scrape
substack_feeds = [
    "https://asymmetricalbets.substack.com/feed",
    "https://kumquatresearch.substack.com/feed",
    "https://cruxcapitalgroup.substack.com/feed",
    "https://shawarmacapital.substack.com/feed"
]

# Twitter accounts to scrape
twitter_accounts = [
    "aleabitoreddit",
    "ParadisLabs",
    "insiderwave_",
    "capitol2iq",
    "PepInvestStocks",
    "spacanpanman",
    "wliang",
    "charaninvests"
]

# Per-source fetch limits
adanos_timedelta = 1
adanos_ticker_limit = 100

post_timedelta = 7
twitter_posts_limit = 50.   # Number of tweets to fetch for each account
substack_article_limit = 20  # Number of articles to fetch per feed

# Tickers with fewer mentions are almost certainly noise.
MIN_MENTIONS = 3

OUTPUT_PATH = "trending_stocks.json"
