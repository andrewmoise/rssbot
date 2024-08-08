import argparse
import feedparser
from datetime import datetime, timedelta, timezone
from dateutil import parser
import email.utils
import requests
import logging

from db import RSSFeedDB
from lemmy import LemmyCommunicator

ORIG_HEADERS = {'User-Agent': 'Pondercat RSSBot (https://rss.ponder.cat/post/1454)'}
MAX_DELAY = 90

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

def get_feed_update_period(entries, current_time):
    if not entries:
        return timedelta(minutes=MAX_DELAY)
    
    dates = [parser.parse(entry.get('published', entry.get('updated'))) for entry in entries if entry.get('published') or entry.get('updated')]
    
    if not dates:
        return timedelta(minutes=MAX_DELAY)
    
    dates = [d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d for d in dates]
    
    latest = current_time
    earliest = min(dates)
    
    update_period = (latest - earliest) / len(dates)
    return min(update_period, timedelta(minutes=MAX_DELAY))

def fetch_and_post(community_filter=None):
    db = RSSFeedDB('rss_feeds.db')
    lemmy_api = LemmyCommunicator()

    feeds = db.list_feeds()
    current_time = datetime.now(timezone.utc)

    for feed in feeds:
        feed_id, feed_url, community_name, community_id, last_updated, next_check = feed

        # Skip feeds not in the community filter
        if community_filter and community_name not in community_filter:
            continue

        # Check if next_check is in the future
        if next_check and parser.parse(next_check).replace(tzinfo=timezone.utc) > current_time:
            logger.debug(f"Skipping feed {feed_url} as next_check is in the future")
            continue

        # Prepare headers with If-Modified-Since
        request_headers = ORIG_HEADERS.copy()
        if last_updated:
            last_updated_dt = parser.parse(last_updated).replace(tzinfo=timezone.utc)
            last_updated_str = email.utils.format_datetime(last_updated_dt)
            request_headers['If-Modified-Since'] = last_updated_str

        logger.info(f"Processing feed: {feed_url}")
        try:
            response = requests.get(feed_url, headers=request_headers, timeout=30)

            if response.status_code == 304:
                logger.info(f"Feed not modified since last check: {feed_url}")
                # Update next_check time
                if last_updated and next_check:
                    next_check_dt = parser.parse(next_check).replace(tzinfo=timezone.utc)
                    update_period = min(next_check_dt - last_updated_dt, timedelta(minutes=MAX_DELAY))
                else:
                    update_period = timedelta(minutes=MAX_DELAY)
                next_check_time = current_time + update_period
                db.update_feed_timestamps(feed_id, last_updated_dt, next_check_time)
                continue

            response.raise_for_status()

            rss = feedparser.parse(response.content)
        except Exception as e:
            logger.error(f"Exception while fetching feed {feed_url}: {str(e)}")
            continue
        
        logger.info('Feed fetched successfully')

        # Get feed update timestamp
        feed_updated = rss.feed.get('updated_parsed') or rss.feed.get('published_parsed')
        if feed_updated:
            feed_last_updated = datetime(*feed_updated[:6], tzinfo=timezone.utc)
        else:
            feed_last_updated = current_time

        # Calculate update period
        update_period = get_feed_update_period(rss.entries, current_time)
        next_check_time = current_time + update_period

        # Update feed timestamps
        db.update_feed_timestamps(feed_id, feed_last_updated, next_check_time)

        logger.info(f"Feed: {feed_url}")
        logger.info(f"Last updated: {feed_last_updated}")
        logger.info(f"Update period: {update_period}")
        logger.info(f"Next check: {next_check_time}")

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

            logger.info(f"Posting: {headline} link {article_url} to {community_name}")

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
