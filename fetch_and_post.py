import feedparser
from datetime import datetime, timedelta, timezone
from dateutil import parser  # Import the parser module from dateutil
from lemmy import LemmyCommunicator
from db import RSSFeedDB

def fetch_and_post():
    db = RSSFeedDB('rss_feeds.db')
    lemmy_api = LemmyCommunicator()

    feeds = db.list_feeds()
    for feed in feeds:
        feed_id = feed[0]
        feed_url = feed[1]
        community_id = feed[3]

        print(feed_url)
        rss = feedparser.parse(feed_url)
        print('  done\n')
        current_time = datetime.now(timezone.utc)  # Make current_time offset-aware by specifying UTC

        time_limit = current_time - timedelta(days=2)  # This remains offset-aware

        for entry in rss.entries:
            if hasattr(entry, 'published'):
                try:
                    published_date = parser.parse(entry.published)
                    # Ensure the date is offset-aware
                    if published_date.tzinfo is None or published_date.tzinfo.utcoffset(published_date) is None:
                        published_date = published_date.replace(tzinfo=timezone.utc)
                except ValueError as e:
                    print(f"Date parsing error: {e} for date string: {entry.published}")
                    continue
            else:
                published_date = current_time

            article_url = entry.link
            headline = entry.title

            if db.get_article_by_url(article_url):
                continue # Article already exists

            if published_date < time_limit:
                print(f"  Time exceeded: {published_date} > {time_limit}")
                continue

            # Post the article to Lemmy
            post = lemmy_api.create_post(
                community_id=community_id,
                name=headline,
                url=article_url
            )
            lemmy_post_id = post['id'] if post else None

            # Add the article to the database
            if lemmy_post_id:
                db.add_article(feed_id, article_url, headline, current_time, lemmy_post_id)
                print(f"Posted: {headline} at {feed_url}")

    print('All done!')

def main():
    fetch_and_post()

if __name__ == "__main__":
    main()

