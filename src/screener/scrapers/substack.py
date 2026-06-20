import re
import time
import feedparser
from ..config import substack_article_limit
from ..ticker_extractor import extract_tickers_cashtag

class SubstackScraper:

    def scrape(self, feed_url):
        '''Scrapes recent posts from a single substack feed URL and
        returns posts as dictionaries'''

        posts = []

        try:
            parsed = feedparser.parse(feed_url)
            substack_name = parsed.feed.title

            for article in parsed.entries[:substack_article_limit]:
                title = article.get("title", "")
                summary = article.get("summary", "")
                link = article.get("link", feed_url)
                content = article.get("content")[0].get("value", "")
                date_published = article.get("published_parsed", "")
                if date_published:
                    date_published = time.strftime("%Y/%m/%d", date_published)

                text = self.strip_tags(content).strip()
                tickers = extract_tickers_cashtag(text)
                # tickers = extract_tickers_base(text, tickers)

                post = {"title": title,
                        "account": substack_name,
                        "link": link,
                        "summary": summary,
                        "content": f"{title}: {summary}\n{text}",
                        "tickers": tickers,
                        "created_at": date_published,
                        "source": "substack"
                        }

                posts.append(post)

        except Exception as e:
            print(f"Substack: error on {feed_url} — {e}")

        return posts

    def strip_tags(self, content):
        '''Removes html/xml tags'''

        return re.sub(r"<[^>]+>", " ", content)

if __name__ == "__main__":
    obj = SubstackScraper()
    results = obj.scrape("https://asymmetricalbets.substack.com/feed")
    for result in results:
        print(result)
