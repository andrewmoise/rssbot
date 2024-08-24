import argparse
import dateparser
from datetime import datetime, timedelta, timezone
import feedparser
import logging
import re
import requests
from statistics import median
import time
from urllib.parse import urlparse

from config import Config
from db import RSSFeedDB
from lemmy import LemmyCommunicator

USER_AGENT = 'Lemmy RSSBot'
# USER_AGENT = 'Wget/1.20.3 (linux-gnu)'

POST_DELAY = timedelta(minutes=5)

FETCH_DELAYS = tuple(timedelta(minutes=delay) for delay in (5, 10, 20, 40, 60, 60*2, 60*4, 60*6, 60*8, 60*10, 60*12, 60*14, 60*16, 60*18, 60*20, 60*22, 60*24, 60*26))
MAX_DELAY = timedelta(days=1)
DEFAULT_DELAY = timedelta(minutes=60)

BLACKLIST_RE = r'Shop our top 5 deals of the week|Amazon deal of the day.*|Today.s Wordle.*|.*NYT Connections.*'

POST_WINDOW = timedelta(days=3) # Max age of articles to post

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

def trim_headline(headline, max_bytes = 200):
    if len(headline.encode('utf-8')) <= max_bytes:
        return headline

    trimmed = ''
    byte_count = 0
    for char in headline:
        char_bytes = len(char.encode('utf-8'))
        if byte_count + char_bytes > max_bytes - 3:  # -3 for "..."
            break
        trimmed += char
        byte_count += char_bytes

    # Trim to last whitespace
    trimmed = trimmed.rsplit(None, 1)[0] + "..."
     
    logger.debug(f"  Trimmed headline:")
    logger.debug(f"    {headline}")
    logger.debug(f"  To:")
    logger.debug(f"    {trimmed}")

    return trimmed

def parse_date_with_timezone(date_str):
    parsed_date = dateparser.parse(date_str, settings={
        'TIMEZONE': 'UTC',
        'RETURN_AS_TIMEZONE_AWARE': True,
    })
    
    if parsed_date is None:
        raise ValueError(f"Unable to parse date: {date_str}")
    
    return parsed_date.astimezone(timezone.utc)

def get_article_timestamps(db, feed_id, entries=None):
    if entries is not None:
        return [
            parse_date_with_timezone(entry.get('published') or entry.get('updated'))
            for entry in entries
            if entry.get('published') or entry.get('updated')
        ]
    else:
        articles = db.get_articles_by_feed(feed_id, limit=20)
        return [
            parse_date_with_timezone(article[4])  # Assuming fetched_timestamp is at index 4
            for article in articles
        ]

def get_median_update_period(timestamps):
    if not timestamps:
        return DEFAULT_DELAY

    sorted_timestamps = sorted(timestamps)
    burst_times = []
    burst_begin = None

    for timestamp in sorted_timestamps:
        if burst_begin is None:
            burst_begin = timestamp
            continue

        time_diff = timestamp - burst_begin
        if time_diff >= POST_DELAY:
            burst_times.append(time_diff)
            burst_begin = timestamp

    logger.debug(f"  Total of {len(burst_times)} burst times recorded")

    if not burst_times:
        return DEFAULT_DELAY

    median_time = median(burst_times)
    logger.debug(f"  Median: {median_time}")

    return median_time

def set_backoff_next_check(db, feed, entries=None):
    feed_id = feed[0]

    timestamps = get_article_timestamps(db, feed_id, entries)
    update_period = get_median_update_period(timestamps)
    logger.debug(f"  Median update period: {update_period}")

    now = datetime.now(timezone.utc)
    logger.debug(f"  Now: {now}")

    if not timestamps:
        next_check_time = now + DEFAULT_DELAY
    else:
        most_recent_article = max(timestamps)
        time_since_last_article = now - most_recent_article

        try:
            suitable_delay = next(
                (delay for delay in FETCH_DELAYS if delay > time_since_last_article),
            )
            logger.debug(f"  Suitable delay: {suitable_delay}")

            next_check_time = max(most_recent_article + suitable_delay, now + update_period)
            next_check_time = min(next_check_time, now + MAX_DELAY)

        except StopIteration:
            next_check_time = most_recent_article + FETCH_DELAYS[-1]
            next_check_time = next_check_time.replace(year=now.year, month=now.month, day=now.day)

            # If it's in the past, add 1 day
            if next_check_time <= now + DEFAULT_DELAY:
                next_check_time += timedelta(days=1)

    logger.debug(f"  Next check time: {next_check_time}")

    return next_check_time

def fetch_and_post(community_filter=None):
    db = RSSFeedDB('rss_feeds.db')

    #lemmy_api = LemmyCommunicator()
    lemmy_api_free = LemmyCommunicator(username=Config.LEMMY_FREE_USERNAME)
    lemmy_api_paywall = LemmyCommunicator(username=Config.LEMMY_PAYWALL_USERNAME)

    delay = 0 # First time through, no delay
    
    while True:
        feeds = db.list_feeds()

        # Sleep until the nearest next_check time
        next_check_times = [parse_date_with_timezone(feed[5]) for feed in feeds if feed[5]]
        if next_check_times:
            next_check_time = min(next_check_times)
            delay = int(max(delay, (next_check_time - datetime.now(timezone.utc)).total_seconds()))

        logger.info(f"  Sleeping for {delay} seconds")
        time.sleep(delay+1)
        delay = 60 # Next time through, sleep at least 1 minute
        
        hit_servers = set()

        for feed in feeds:
            feed_id, feed_url, community_name, community_id, last_updated, next_check, etag, is_paywall = feed

            if is_paywall:
                lemmy_api = lemmy_api_paywall
            else:
                lemmy_api = lemmy_api_free

            # Skip feeds not in the community filter
            if community_filter and community_name not in community_filter:
                continue

            # Check if next_check is in the future
            if next_check and parse_date_with_timezone(next_check) > datetime.now(timezone.utc):
                continue

            # Skip feeds we've already hit the server for this time around
            parsed_url = urlparse(feed_url)
            host = parsed_url.netloc
            if host in hit_servers:
                logger.debug(f"Skipping {feed_url}; already hit this iteration")
                continue
            else:
                hit_servers.add(host)

            logger.info(f"Processing feed: {feed_url}")

            # Prepare headers with If-Modified-Since
            request_headers = {'User-Agent': USER_AGENT}
            if last_updated is not None:
                logger.debug(f"  IMS header: {last_updated}")
                request_headers['If-Modified-Since'] = last_updated
            if etag is not None:
                logger.debug(f"  ETag header: {etag}")
                request_headers['If-None-Match'] = etag

            try:
                response = requests.get(feed_url, headers=request_headers, timeout=30)

                if response.status_code == 304:
                    logger.info(f"  Not modified since last check")

                    next_check_time = set_backoff_next_check(db, feed)
                    db.update_feed_timestamps(feed_id, last_updated, etag, next_check_time)
                    
                    continue

                response.raise_for_status()

                # Retrieve the last-modified and ETag headers
                last_updated = response.headers.get('Last-Modified')
                if last_updated:
                    logger.debug(f"  Last-Modified: {last_updated}")

                etag = response.headers.get('ETag')
                if etag:
                    logger.debug(f"  ETag: {etag}")

                rss = feedparser.parse(response.content)

            except Exception as e:
                logger.error(f"Exception while fetching feed {feed_url}: {str(e)}")
                
                next_check_time = set_backoff_next_check(db, feed)
                db.update_feed_timestamps(feed_id, last_updated, etag, next_check_time)

                continue
            
            logger.debug('  Feed fetched successfully')

            # Calculate update period
            next_check_time = set_backoff_next_check(db, feed, rss.entries)
            db.update_feed_timestamps(feed_id, last_updated, etag, next_check_time)

            logger.debug(f"  Last updated: {last_updated}")
            logger.debug(f"  Next check: {next_check_time}")

            time_limit = datetime.now(timezone.utc) - POST_WINDOW
            hit_feed = False

            for entry in reversed(rss.entries):
                if hasattr(entry, 'published'):
                    try:
                        published_date = parse_date_with_timezone(entry.published)
                    except ValueError as e:
                        logger.error(f"Date parsing error: {e} for date string: {entry.published}")
                        continue
                else:
                    published_date = datetime.now(timezone.utc)

                article_url = entry.link
                headline = entry.title

                if db.get_article_by_url(article_url):
                    continue

                if published_date < time_limit:
                    continue

                if re.match(BLACKLIST_RE, headline):
                    logger.debug(f"  Not posting {headline}, blacklisted")
                    continue

                headline = trim_headline(headline)

                if hit_feed:
                    logger.info("  More articles in feed, requeueing with delay")
                    # Don't post multiple stories from a single feed without a delay
                    next_check = datetime.now(timezone.utc) + POST_DELAY
                    logger.debug(f"    next_check reset to {next_check}")
                    db.update_feed_timestamps(feed_id, None, None, next_check)
                    break

                logger.info(f"  Posting: {headline}")
                logger.debug(f"    to {community_name}")

                try:
                    post = lemmy_api.create_post(
                        community_id=community_id,
                        name=headline,
                        url=article_url
                    )
                    lemmy_post_id = post['id'] if post else None
                except Exception as e:
                    logger.error(f"    Exception while posting to Lemmy: {str(e)}")
                    continue
                    
                if lemmy_post_id:
                    db.add_article(feed_id, article_url, headline, datetime.now(timezone.utc), lemmy_post_id)
                    logger.debug(f"    Posted successfully! Lemmy post ID: {lemmy_post_id}")
                else:
                    logger.warning("    Could not post to Lemmy")

                hit_feed = True

def main():
    parser = argparse.ArgumentParser(description='Fetch and post RSS feeds to Lemmy.')
    parser.add_argument('-c', '--communities', type=str, help='Comma-separated list of community IDs to update')

    args = parser.parse_args()

    community_filter = args.communities.split(',') if args.communities else None

    fetch_and_post(community_filter)

if __name__ == "__main__":
    main()