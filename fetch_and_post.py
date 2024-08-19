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

SHORT_FETCH_DELAY = timedelta(minutes=60)   # Max delay from exponential backoff
LONG_FETCH_DELAY = timedelta(minutes=5*60)  # Max delay from feed estimated pace
POST_DELAY = timedelta(minutes=5)           # Delay introduced between multiple posts from a single RSS feed

BLACKLIST_RE = r'Shop our top 5 deals of the week|Amazon deal of the day.*|Today.s Wordle.*|.*NYT Connections.*'

POST_WINDOW = timedelta(days=3) # Max age of articles to post

# New global variables to keep track of median times and last fetch times
median_times = {}
last_article_times = {}

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

def determine_next_check_time(median_time, time_since_last):
    # Don't ever check slower than LONG_FETCH_DELAY
    if median_time > LONG_FETCH_DELAY:
        return LONG_FETCH_DELAY

    # If it's been longer than normal, do an exponential backoff, but only go
    # slower than SHORT_FETCH_DELAY if the median is also slower than that
    if time_since_last > median_time:
        return min(time_since_last, max(median_time, SHORT_FETCH_DELAY))

    # Or, if everything's normal, just do median time
    return median_time

def get_feed_update_period(feed_id, entries):
    global median_times, last_article_times

    timestamps = sorted([
        parse_date_with_timezone(entry.get('published') or entry.get('updated'))
        for entry in entries
        if entry.get('published') or entry.get('updated')
    ])

    burst_times = []
    burst_begin = None

    for timestamp in timestamps:
        if burst_begin is None:
            burst_begin = timestamp
            continue

        time_diff = timestamp - burst_begin
        if time_diff >= POST_DELAY:
            burst_times.append(time_diff)
            burst_begin = timestamp

    logger.debug(f"  Total of {len(burst_times)} burst times recorded")

    if not burst_times:
        return SHORT_FETCH_DELAY

    median_time = median(burst_times)
    logger.debug(f"  Median: {median_time}")

    # Update the median time for this feed
    median_times[feed_id] = median_time
    last_article_times[feed_id] = timestamps[-1]

    time_since_last = datetime.now(timezone.utc) - timestamps[-1]
    logger.debug(f"  Time since last: {time_since_last}")

    return determine_next_check_time(median_time, time_since_last)

def parse_date_with_timezone(date_str):
    parsed_date = dateparser.parse(date_str, settings={
        'TIMEZONE': 'UTC',  # Assume UTC if no timezone is specified
        'RETURN_AS_TIMEZONE_AWARE': True,  # Always return timezone-aware datetime
    })
    
    if parsed_date is None:
        raise ValueError(f"Unable to parse date: {date_str}")
    
    # Convert to UTC
    return parsed_date.astimezone(timezone.utc)

def set_backoff_next_check(db, feed):
    global median_times, last_article_times

    feed_id, feed_url, community_name, community_id, last_updated, next_check, etag, is_paywall = feed

    median_time = median_times.get(feed_id)
    last_article_time = last_article_times.get(feed_id)

    if median_time and last_article_time:
        update_period = determine_next_check_time(median_time, datetime.now(timezone.utc) - last_article_time)
        logger.debug(f"  Normal backoff {update_period}")
    elif last_article_time:
        update_period = min(datetime.now(timezone.utc) - last_article_time, LONG_FETCH_DELAY)
        logger.debug(f"  No-median backoff {update_period}")
    else:
        last_article_times[feed_id] = datetime.now(timezone.utc)
        update_period = SHORT_FETCH_DELAY
        logger.debug(f"  Init backoff {update_period}")

    next_check_time = datetime.now(timezone.utc) + update_period
    db.update_feed_timestamps(feed_id, last_updated, etag, next_check_time)

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
                    set_backoff_next_check(db, feed)
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
                set_backoff_next_check(db, feed)
                continue
            
            logger.debug('  Feed fetched successfully')

            # Calculate update period
            update_period = get_feed_update_period(feed_id, rss.entries)
            next_check_time = datetime.now(timezone.utc) + update_period

            # Update feed timestamps
            db.update_feed_timestamps(feed_id, last_updated, etag, next_check_time)

            logger.debug(f"  Last updated: {last_updated}")
            logger.debug(f"  Update period: {update_period}")
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