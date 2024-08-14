import argparse
import dateparser
from datetime import datetime, timedelta, timezone
import feedparser
import logging
import requests
from statistics import median
import time
from urllib.parse import urlparse

from db import RSSFeedDB
from lemmy import LemmyCommunicator

USER_AGENT = 'Lemmy RSSBot'
# USER_AGENT = 'Wget/1.20.3 (linux-gnu)'

MAX_FETCH_DELAY = 5*60  # Max time between hits to each RSS feed, in minutes
POST_DELAY = 5          # Min time between multiple posts from a single RSS feed, in minutes

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

def get_feed_update_period(entries):
    # Convert entries to timestamps and filter out None values
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
        if time_diff >= timedelta(minutes=POST_DELAY):
            logger.debug(f"  Adding {time_diff} to burst times")
            burst_times.append(time_diff)
            burst_begin = timestamp

    logger.debug(f"  Total of {len(burst_times)} burst times recorded")

    if burst_times:
        return median(burst_times)
    else:
        return timedelta(minutes=MAX_FETCH_DELAY)

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
    feed_id, feed_url, community_name, community_id, last_updated, next_check = feed

    # Update next_check time
    if last_updated:
        last_updated_dt = parse_date_with_timezone(last_updated)
        #next_check_dt = parse_date_with_timezone(next_check)
        update_period = min(datetime.now(timezone.utc) - last_updated_dt, timedelta(minutes=MAX_FETCH_DELAY))
        #update_period = min(next_check_dt - last_updated_dt, timedelta(minutes=MAX_FETCH_DELAY))
    else:
        update_period = timedelta(minutes=MAX_FETCH_DELAY)

    next_check_time = datetime.now(timezone.utc) + update_period
    db.update_feed_timestamps(feed_id, last_updated, next_check_time)
    
def fetch_and_post(community_filter=None):
    db = RSSFeedDB('rss_feeds.db')
    lemmy_api = LemmyCommunicator()

    delay = 0 # First time through, no delay
    
    while True:
        feeds = db.list_feeds()

        # Sleep until the nearest next_check time
        next_check_times = [parse_date_with_timezone(feed[5]) for feed in feeds if feed[5]]
        if next_check_times:
            next_check_time = min(next_check_times)
            delay = int(max(delay, (next_check_time - datetime.now(timezone.utc)).total_seconds()))

        logger.info(f"Sleeping for {delay} seconds")
        time.sleep(delay+1)
        delay = 60 # Next time through, sleep at least 1 minute
        
        hit_servers = set()

        for feed in feeds:
            feed_id, feed_url, community_name, community_id, last_updated, next_check = feed

            # Skip feeds not in the community filter
            if community_filter and community_name not in community_filter:
                continue

            # Check if next_check is in the future
            if next_check and parse_date_with_timezone(next_check) > datetime.now(timezone.utc):
                #logger.debug(f"Skipping {feed_url} as next_check is in the future")
                continue

            # Skip feeds we've already hit the server for this time around
            parsed_url = urlparse(feed_url)
            host = parsed_url.netloc
            if host in hit_servers:
                logger.debug(f"Skipping {feed_url}; already hit this iteration")
                continue
            else:
                hit_servers.add(host)

            # Prepare headers with If-Modified-Since
            request_headers = {'User-Agent': USER_AGENT}
            if last_updated is not None:
                logger.debug(f"IMS header: {last_updated}")
                request_headers['If-Modified-Since'] = last_updated

            logger.info(f"Processing feed: {feed_url}")
            try:
                response = requests.get(feed_url, headers=request_headers, timeout=30)

                if response.status_code == 304:
                    logger.info(f"  Not modified since last check")
                    set_backoff_next_check(db, feed)
                    continue

                response.raise_for_status()

                rss = feedparser.parse(response.content)
            except Exception as e:
                logger.error(f"Exception while fetching feed {feed_url}: {str(e)}")
                set_backoff_next_check(db, feed)
                continue
            
            logger.debug('  Feed fetched successfully')

            # Calculate update period
            update_period = get_feed_update_period(rss.entries)
            next_check_time = datetime.now(timezone.utc) + min(update_period, timedelta(minutes=MAX_FETCH_DELAY))

            # Update feed timestamps
            db.update_feed_timestamps(feed_id, last_updated, next_check_time)

            logger.debug(f"  Last updated: {last_updated}")
            logger.debug(f"  Update period: {update_period}")
            logger.debug(f"  Next check: {next_check_time}")

            time_limit = datetime.now(timezone.utc) - timedelta(days=3)
            hit_feed = False

            for entry in reversed(rss.entries):
                if hasattr(entry, 'published'):
                    try:
                        published_date = parse_date_with_timezone(entry.published)
                        #if published_date.tzinfo is None or published_date.tzinfo.utcoffset(published_date) is None:
                        #    published_date = published_date.replace(tzinfo=timezone.utc)
                    except ValueError as e:
                        logger.error(f"Date parsing error: {e} for date string: {entry.published}")
                        continue
                else:
                    published_date = datetime.now(timezone.utc)

                article_url = entry.link
                headline = entry.title

                if db.get_article_by_url(article_url):
                    #logger.debug(f"Article already exists: {article_url}")
                    continue

                if published_date < time_limit:
                    #logger.debug(f"Time exceeded: {published_date} > {time_limit}")
                    continue

                if hit_feed:
                    logger.debug("  Not posting -- multiple stories")
                    # Don't post multiple stories from a single feed without a delay
                    next_check = datetime.now(timezone.utc) + timedelta(minutes=POST_DELAY)
                    logger.debug(f"  next_check reset to {next_check}")
                    db.update_feed_timestamps(feed_id, None, next_check)
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
                    logger.error(f"Exception while posting to Lemmy: {str(e)}")
                    continue
                    
                if lemmy_post_id:
                    db.add_article(feed_id, article_url, headline, datetime.now(timezone.utc), lemmy_post_id)
                    logger.debug(f"  Posted successfully! Lemmy post ID: {lemmy_post_id}")
                else:
                    logger.warning("Could not post to Lemmy")

                hit_feed = True

def main():
    parser = argparse.ArgumentParser(description='Fetch and post RSS feeds to Lemmy.')
    parser.add_argument('-c', '--communities', type=str, help='Comma-separated list of community IDs to update')

    args = parser.parse_args()

    community_filter = args.communities.split(',') if args.communities else None

    fetch_and_post(community_filter)

if __name__ == "__main__":
    main()
