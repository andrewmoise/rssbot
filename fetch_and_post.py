import argparse
import feedparser
from datetime import datetime, timedelta, timezone
from dateutil import parser
import requests
import logging

from db import RSSFeedDB
from lemmy import LemmyCommunicator

headers = {'User-Agent': 'Pondercat RSSBot (https://rss.ponder.cat/post/1454)'}

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # File handlers
    file_handler = logging.FileHandler('rssbot.log')
    file_handler.setLevel(logging.DEBUG)
    error_handler = logging.FileHandler('error.log')
    error_handler.setLevel(logging.ERROR)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    error_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)

    return logger

logger = setup_logging()

def fetch_and_post(community_filter=None):
    db = RSSFeedDB('rss_feeds.db')
    lemmy_api = LemmyCommunicator()

    feeds = db.list_feeds()
    for feed in feeds:
        feed_id, feed_url, community_name, community_id, _, _ = feed

        # Skip feeds not in the community filter
        if community_filter and community_name not in community_filter:
            continue

        logger.info(feed_url)
        try:
            response = requests.get(feed_url, headers=headers, timeout=30)
            rss = feedparser.parse(response.content)
        except Exception as e:
            logger.error(f"Exception while fetching feed {feed_url}: {str(e)}")
            continue
        
        logger.info('Feed fetched successfully')
        current_time = datetime.now(timezone.utc)
        time_limit = current_time - timedelta(days=3)

        for entry in rss.entries:
            if hasattr(entry, 'published'):
                try:
                    published_date = parser.parse(entry.published)
                    if published_date.tzinfo is None or published_date.tzinfo.utcoffset(published_date) is None:
                        published_date = published_date.replace(tzinfo=timezone.utc)
                except ValueError as e:
                    logger.error(f"Date parsing error: {e} for date string: {entry.published}")
                    continue
            else:
                published_date = current_time

            article_url = entry.link
            headline = entry.title

            if db.get_article_by_url(article_url):
                logger.debug(f"Article already exists: {article_url}")
                continue

            if published_date < time_limit:
                logger.debug(f"Time exceeded: {published_date} > {time_limit}")
                continue

            logger.info(f"Posting: {headline} link {article_url} to {feed_url}")

            try:
                post = lemmy_api.create_post(
                    community_id=community_id,
                    name=headline,
                    url=article_url
                )
                lemmy_post_id = post['id'] if post else None
            except Exception as e:
                logger.error(f"Exception while posting to Lemmy: {str(e)}")
                continue
                
            if lemmy_post_id:
                db.add_article(feed_id, article_url, headline, current_time, lemmy_post_id)
                logger.info(f"Posted successfully! Lemmy post ID: {lemmy_post_id}")
            else:
                logger.warning("Could not post to Lemmy")

    logger.info('All done!')

def main():
    parser = argparse.ArgumentParser(description='Fetch and post RSS feeds to Lemmy.')
    parser.add_argument('-c', '--communities', type=str, help='Comma-separated list of community IDs to update')

    args = parser.parse_args()

    community_filter = args.communities.split(',') if args.communities else None

    fetch_and_post(community_filter)

if __name__ == "__main__":
    main()