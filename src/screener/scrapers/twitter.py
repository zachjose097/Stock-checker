import json
import os
from datetime import datetime
from pathlib import Path
from requests_cache import CachedSession
from dotenv import load_dotenv

from ..config import twitter_accounts, twitter_posts_limit
from ..ticker_extractor import extract_tickers_cashtag

load_dotenv()
api_key = os.getenv("x-rapidapi-key")
api_host = os.getenv("x-rapidapi-host")

user_ids_path = Path(__file__).parents[3] / "json_files" / "user_ids.json"
os.makedirs(user_ids_path.parent, exist_ok=True)

cache_dir = Path(__file__).parent.parent / "Cached_sessions"
os.makedirs(cache_dir, exist_ok = True)

class TwitterScraper:

    def __init__(self):
        self.base_url = "https://twitter241.p.rapidapi.com/"
        self.headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": api_host,
                        "Content-Type": "application/json"}
        self.session = CachedSession(cache_dir / "rapidapi_x_cache", expire_after=3600*24)
        self.user_ids = json.loads(user_ids_path.read_text()) if user_ids_path.exists() else {}

    def save_user_ids(self):
        ''' Save userids of usernames so those API calls can be avoided'''

        user_ids_path.write_text(json.dumps(self.user_ids, indent=2))

    def get_userid(self, username):
        '''Returns (account_name, user_id) for the given username, using the local cache to avoid redundant API calls.'''
        
        if username in self.user_ids:
            user = self.user_ids[username]
            return user["account_name"], user["user_id"]

        # endpoint to get user_ids
        url = self.base_url + "user"
        params = {"username": username}

        try:
            response = self.session.get(url, headers=self.headers, params=params)
            response.raise_for_status()

            # The structure of the output is convulated. user_id variable stores a single value
            data = response.json()["result"]["data"]["user"]["result"]
            account_name = data["core"]["name"]
            user_id = data["rest_id"]

        except Exception as e:
            print(f"Error fetching user id for {username}: {e}")
            return None

        self.user_ids[username] = {"account_name": account_name, "user_id": user_id}
        self.save_user_ids()
        return account_name, user_id

    def get_tweets(self, account):
        '''Returns a list of parsed tweets for the given account, each with account, link, content, tickers, created_at, and source fields.'''

        result = self.get_userid(account)
        if result is None:
            return []
        account_name, user_id = result
        url = self.base_url + "user-tweets"
        params = {"user": user_id, "count": twitter_posts_limit}

        tweets = []
        try:
            response = self.session.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            entries = []
            # In twitter, the main payload (tweets) lives in "TimelineAddEntries"
            # But this is not a standalone key, needs to be identified using "type" key
            for instr in data["result"]["timeline"]["instructions"]:
                if instr.get("type") == "TimelineAddEntries":
                    entries = instr["entries"]
                    break

            tweets = []
            # Iterate through each item in TimelineAddEntries and log tweets
            for entry in entries:
                content = entry["content"]
                entry_type = content["entryType"]

                # TimelineTimelineItem: A single tweet
                if entry_type == "TimelineTimelineItem":
                    tweet_results = content["itemContent"].get("tweet_results", {})
                    tweet = tweet_results.get("result")
                    if tweet and tweet.get("__typename") == "Tweet":
                        tweets.append(tweet)

                # TimelineTimelineModule catches tweets in a thread
                elif entry_type == "TimelineTimelineModule":
                    for item in content.get("items", []):
                        tweet_results = item["item"]["itemContent"].get("tweet_results", {})
                        tweet = tweet_results.get("result")
                        if tweet and tweet.get("__typename") == "Tweet":
                            tweets.append(tweet)

            results = []
            for tweet in tweets:
                legacy = tweet["legacy"]
                screen = tweet["core"]["user_results"]["result"]["core"]["screen_name"]
                tid = tweet["rest_id"]
                note = tweet.get("note_tweet")
                text = note["note_tweet_results"]["result"]["text"] if note else legacy["full_text"]
                # X returns e.g. "Wed Jun 10 20:19:24 +0000 2026"
                created_at = datetime.strptime(
                    legacy["created_at"], "%a %b %d %H:%M:%S %z %Y"
                )
                tickers = extract_tickers_cashtag(text)
                parsed = {"account": account_name,
                          "link": f"https://twitter.com/{screen}/status/{tid}",
                          "content": text,
                          "tickers": tickers,
                          "created_at": created_at.strftime("%Y/%m/%d"),
                          "source": "X"}
                results.append(parsed)

        except Exception as e:
            print(f"Error fetching tweets from {account_name}: {e}")

        return results

if __name__ == "__main__":
    obj = TwitterScraper()
    for account in twitter_accounts:
        results = obj.get_tweets(account)
        break
