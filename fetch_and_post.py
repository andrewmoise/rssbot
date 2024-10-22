import argparse
import dateparser
from datetime import datetime, timedelta, timezone
import feedparser
import html
import logging
import re
import requests
from statistics import median
import time
import traceback
from urllib.parse import urlparse

from config import Config
from db import RSSFeedDB
from lemmy import LemmyCommunicator

USER_AGENT = 'Lemmy RSSBot'

MIN_BACKOFF = timedelta(minutes=5)
SHORT_BACKOFF = timedelta(hours=2)
LONG_BACKOFF = timedelta(hours=24)
MAX_BACKOFF = timedelta(days=4)

MESSAGE_POLL_INTERVAL = timedelta(seconds=60)

BLACKLIST_REGEXES = [
    r'Shop our top 5 deals of the week',
    r'Amazon deal of the day.*',
    r'Today.s Wordle.*',
    r'Wordle today:.*',
    r'.*NYT Connections.*',
    r'.*[A-Z][A-Z][A-Z][A-Z][A-Z].*[A-Z][A-Z][A-Z][A-Z][A-Z].*[A-Z][A-Z][A-Z][A-Z][A-Z].*',
    r'Daily Deal:.*',
    r'Shop our .*',
    r'.*\(on sale now.*',
    r'.*Big Deal Days.*',
    r'.*Way Day Sale.*',
    r'.*(★★|☆☆).*',
    r'Last chance:.*',
]

def compile_blacklist():
    return re.compile('|'.join(BLACKLIST_REGEXES))

BLACKLIST_RE = compile_blacklist()

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
        return SHORT_BACKOFF

    sorted_timestamps = sorted(timestamps)
    burst_times = []
    burst_begin = None

    for timestamp in sorted_timestamps:
        if burst_begin is None:
            burst_begin = timestamp
            continue

        time_diff = timestamp - burst_begin
        if time_diff >= MIN_BACKOFF:
            burst_times.append(time_diff)
            burst_begin = timestamp

    logger.debug(f"  Total of {len(burst_times)} burst times recorded")

    if not burst_times:
        return SHORT_BACKOFF

    median_time = median(burst_times)
    logger.debug(f"  Median: {median_time}")

    return median_time

def get_backoff_next_check(db, feed, entries=None):
    feed_id = feed[0]

    timestamps = get_article_timestamps(db, feed_id, entries)

    now = datetime.now(timezone.utc)
    logger.debug(f"  Now: {now}")

    if not timestamps:
        next_check_time = now + LONG_BACKOFF
    else:
        most_recent_article = max(timestamps)
        time_since_last_article = now - most_recent_article

        logger.debug(f"  Most recent: {most_recent_article}")
        logger.debug(f"  Time since last: {time_since_last_article}")

        update_period = get_median_update_period(timestamps)
        logger.debug(f"  Median update period: {update_period}")

        if time_since_last_article > MAX_BACKOFF:
            # Do the slow feed strategy; just poll once per 24 hours
            next_check_time = most_recent_article + SHORT_BACKOFF
            next_check_time = next_check_time.replace(year=now.year, month=now.month, day=now.day)
            if next_check_time < now:
                next_check_time += timedelta(hours=24)
            logger.debug(f"  Slow strategy")

        elif time_since_last_article < SHORT_BACKOFF:
            # Active period; wait the median time, capped to reasonable values
            suitable_delay = max(MIN_BACKOFF, update_period)
            suitable_delay = min(suitable_delay, LONG_BACKOFF)

            next_check_time = now + suitable_delay
            logger.debug(f"  Active strategy; delay {suitable_delay}")

        else:
            # Inactive period; wait max(SHORT_BACKOFF, median time), capped to reasonable values
            suitable_delay = max(SHORT_BACKOFF, update_period)
            suitable_delay = min(suitable_delay, LONG_BACKOFF)

            next_check_time = now + suitable_delay
            logger.debug(f"  Inactive strategy; delay {suitable_delay}")

    logger.debug(f"  Next check time: {next_check_time}")

    return next_check_time

def network_fetch(feed_url, last_updated, etag):
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
            return None, last_updated, etag

        response.raise_for_status()

        # Retrieve the last-modified and ETag headers
        new_last_updated = response.headers.get('Last-Modified', last_updated)
        new_etag = response.headers.get('ETag', etag)

        if new_last_updated:
            logger.debug(f"  Last-Modified: {new_last_updated}")
        if new_etag:
            logger.debug(f"  ETag: {new_etag}")

        rss = feedparser.parse(response.content)
        return rss, new_last_updated, new_etag

    except Exception as e:
        logger.error(f"Exception while fetching feed {feed_url}: {str(e)}")
        return None, last_updated, etag

def process_feed_entries(db, feed_id, rss):
    logger.debug(f"Processing feed ID {feed_id}")
    time_limit = datetime.now(timezone.utc) - POST_WINDOW

    for entry in reversed(rss.entries):
        try:
            if hasattr(entry, 'published'):
                published_date = parse_date_with_timezone(entry.published)
            elif hasattr(entry, 'updated'):
                published_date = parse_date_with_timezone(entry.updated)
            else:
                published_date = datetime.now(timezone.utc)
        except ValueError as e:
            logger.error(f"Date parsing error: {e} for entry: {entry}")
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
        logger.debug(f"  Adding article {article_url}")
        db.add_article(feed_id, article_url, headline, published_date, None)

def process_messages_and_mentions(api, db, bot_username):
    logger.info("Polling for messages.")

    # Process private messages
    private_messages = api.get_private_messages(unread_only=True)
    for pm in private_messages:
        logger.info(f"Received private message from {pm['creator']['name']}: {pm['private_message']['content']}")
        response = process_commands(api, db, pm['private_message']['content'], pm['creator']['name'], bot_username)
        api.mark_private_message_as_read(pm['private_message']['id'])
        api.send_private_message(pm['creator']['id'], response)

    # Process mentions
    #mentions = api.get_mentions()
    #for mention in mentions:
    #    logger.info(f"Received mention from {mention['creator']['name']} in post '{mention['post']['name']}': {mention['comment']['content']}")
    #    response = process_commands(api, db, mention['comment']['content'], mention['creator']['name'], bot_username)
    #    api.mark_mention_as_read(mention['person_mention']['id'])
    #    api.create_comment(mention['post']['id'], response, mention['comment']['id'])

def check_moderator(api, user_name, community_name):
    logger.debug(f"Checking {user_name} moderates {community_name}")
    moderators = api.fetch_community_moderators(community_name)
    logger.debug("All data:")
    logger.debug(moderators)
    for mod in moderators:
        if mod['moderator']['name'] == user_name:
            logger.debug(f" Got it: {user_name}")
            return True
    return False

def process_commands(api, db, content, sender_name, bot_username):
    response = []
    for line in content.split('\n'):
        match = re.search(r'\/(\w+)(.*)', line)
        if not match:
            continue

        command = match.group(1)
        args_str = match.group(2)
        args = args_str.strip().split()
        
        logger.info(f"Found command: {command}({', '.join(args)})")
        try:
            if command == 'add':
                response.append("> " + line)
                if len(args) == 2:
                    rss_url, community_name = args
                    community_name = community_name.lstrip('!')
                    if '@' not in community_name:
                        community_name = f"{community_name}@{Config.LEMMY_SERVER}"
                    community_id = api.resolve_community(community_name)
                    if community_id is not None:
                        if check_moderator(api, sender_name, community_name):
                            logger.info("Would succeed")
                        else:
                            logger.info("Would fail")
                            response.append(f"{sender_name} must be a moderator of !{community_name} to make changes.")
                        community_id = api.fetch_community_id(community_name)
                        if community_id is None:
                            response.append(f"Could not find community !{community_name}")
                        else:
                            db.add_feed(rss_url, community_name, community_id, bot_username=bot_username)
                            response.append(f"Added {rss_url} to !{community_name}")
                    else:
                        response.append(f"Could not find !{community_name}")
                else:
                    response.append("Invalid number of arguments for /add command.")
            elif command == 'delete':
                response.append("> " + line)
                if len(args) == 2:
                    rss_url, community = args
                    community = community.lstrip('!')
                    if check_moderator(api, sender_name, community):
                        logger.info("Would succeed")
                        changes = db.remove_feed(community_name=community, feed_url=rss_url)
                        if changes == 0:
                            response.append(f"No feed {rss_url} found in !{community}")
                        else:
                            response.append(f"Deleted {changes} feed{'s' if changes > 1 else ''} from !{community}")
                    else:
                        logger.info("Would fail")
                        response.append(f"{sender_name} must be a moderator of !{community} to make changes.")
                else:
                    response.append("Invalid number of arguments for /delete command.")
            elif command == 'list':
                response.append("> " + line)
                if len(args) == 1:
                    count = 0
                    community = args[0]
                    all_feeds = db.list_feeds()
                    for feed in all_feeds:
                        if '@' in feed[2]:
                            feed_community = feed[2]
                        else:
                            feed_community = f"{feed[2]}@{Config.LEMMY_SERVER}"
                        logger.debug(f"  Compare {feed_community} {community}")
                        if feed_community == community:
                            logger.debug("    match!")
                            count += 1
                            response.append("* " + feed[1])

                    if count == 0:
                        response.append(f"No feeds found connected to !{community}")
                    else:
                        # We want a single newline only
                        response[-count] = f"Feeds active for !{community}:\n" + response[-count]
                else:
                    response.append("Invalid number of arguments for /list command.")
            elif command == 'help':
                response.append("> " + line)
                response.append(get_help_text())
            else:
                response.append("> " + line)
                response.append(f"Unknown command: {command}")
        except Exception as e:
            logger.error(f"Error processing command '{command}': {str(e)}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            response.append(f"An error occurred while processing the '{command}' command. Please try again later or contact the bot administrator if the problem persists.")

    if not response:
        response.append("No commands found. Did you mean to send me RSS commands?")
        response.append(get_help_text())

    full_response = "\n\n".join(response)
    logger.debug(f"Sending response: {full_response}")
    return full_response

def get_help_text():
    return """
Available commands:
* /add {rss_url} {community}@{instance} - Add a new RSS feed
* /delete {rss_url} {community}@{instance} - Delete an existing RSS feed
* /list {community}@{instance} - List all feeds for a community
* /help - Show this help message

You can include multiple commands in a single message, each on a new line.
    """

def process_headline(headline):
    # Replace newlines with spaces
    new_headline = re.sub('\n', ' ', headline)

    # Process styling tags
    styling_map = {
        'em': ('𝘢', '𝘈'),       # Italic
        'strong': ('𝗮', '𝗔'),   # Bold
        'sub': '₀₁₂₃₄₅₆₇₈₉',    # Subscript
        'sup': '⁰¹²³⁴⁵⁶⁷⁸⁹'     # Superscript
    }

    def replace_styled_text(match):
        tag = match.group(1)
        content = match.group(2)
        if tag not in styling_map:
            return content
        
        styled_text = ''
        for char in content:
            if char.isalpha():
                if char.islower():
                    styled_text += chr(ord(styling_map[tag][0]) + (ord(char) - ord('a')))
                else:
                    styled_text += chr(ord(styling_map[tag][1]) + (ord(char) - ord('A')))
            elif char.isdigit() and tag in ['sub', 'sup']:
                styled_text += styling_map[tag][int(char)]
            else:
                styled_text += char
        return styled_text

    new_headline = re.sub(r'<(em|strong|sub|sup)>(.*?)</\1>', replace_styled_text, new_headline)

    # Remove other HTML tags
    new_headline = re.sub(r'<.*?>', '', new_headline)

    # Replace &amp; with &
    new_headline = re.sub(r'&amp;', '&', new_headline)

    # Remove content after |
    new_headline = re.sub(r' *\|.*', '', new_headline)

    # Remove "Pluralistic: " prefix and date
    new_headline = re.sub(r'^Pluralistic: +(.*?) +\(\d+ \w+ \d+\)$', r'\1', new_headline)

    # Unescape any remaining HTML entities
    new_headline = html.unescape(new_headline)

    return new_headline

def fetch_and_post(community_filter=None):
    db = RSSFeedDB('rss_feeds.db')

    lemmy_apis = {
        'free': LemmyCommunicator(username=Config.LEMMY_FREE_BOT, logger=logger),
        'paywall': LemmyCommunicator(username=Config.LEMMY_PAYWALL_BOT, logger=logger),
        'bot': LemmyCommunicator(username=Config.LEMMY_BOT_BOT, logger=logger)
    }

    while True:
        feeds = db.list_feeds()

        # Sleep until the nearest next_check time
        next_check_times = [parse_date_with_timezone(feed[5]) for feed in feeds if feed[5]]
        if next_check_times:
            next_loop = min(next_check_times)
        else:
            next_loop = datetime.now(timezone.utc) + MIN_BACKOFF

        logger.info(f"Sleeping until {next_loop}")

        while datetime.now(timezone.utc) < next_loop:
            time.sleep(MESSAGE_POLL_INTERVAL.total_seconds())
            for bot_username, api in lemmy_apis.items():
                process_messages_and_mentions(api, db, bot_username)
        else:
            for bot_username, api in lemmy_apis.items():
                process_messages_and_mentions(api, db, bot_username)

        hit_servers = set()

        for feed in feeds:
            feed_id, feed_url, community_name, community_id, last_updated, next_check, etag, bot_username = feed
            lemmy_api = lemmy_apis[bot_username]

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

            # Check for unposted articles
            unposted_article = db.get_unposted_article(feed_id)
            fetched_rss = None

            if not unposted_article:
                # If no unposted articles, fetch new ones
                logger.debug("  Network fetch")
                fetched_rss, last_updated, etag = network_fetch(feed_url, last_updated, etag)
                
                if fetched_rss:
                    logger.debug("  Process feed entries")
                    process_feed_entries(db, feed_id, fetched_rss)
                    unposted_article = db.get_unposted_article(feed_id)
                    logger.debug(f"  Unposted article: {unposted_article}")

            if unposted_article:
                article_id, _, article_url, headline, _, lemmy_post_id = unposted_article

                new_headline = process_headline(headline)
                if new_headline != headline:
                    logger.debug(f"  Fixing {headline}")
                    headline = new_headline

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
                    db.update_article_post_id(article_id, lemmy_post_id)
                    logger.debug(f"    Posted successfully! Lemmy post ID: {lemmy_post_id}")
                else:
                    logger.warning("    Could not post to Lemmy")

            if db.get_unposted_article(feed_id):
                next_check = datetime.now(timezone.utc) + MIN_BACKOFF
                logger.debug(f"    More to post, next_check reset to {next_check}")
                db.update_feed_timestamps(feed_id, last_updated, etag, next_check)
            else:                            
                next_check = get_backoff_next_check(db, feed, fetched_rss.entries if fetched_rss else None)
                logger.debug(f"    Nothing to post, next_check reset to {next_check}")
                db.update_feed_timestamps(feed_id, last_updated, etag, next_check)

def main():
    parser = argparse.ArgumentParser(description='Fetch and post RSS feeds to Lemmy.')
    parser.add_argument('-c', '--communities', type=str, help='Comma-separated list of community IDs to update')

    args = parser.parse_args()

    community_filter = args.communities.split(',') if args.communities else None

    while True:
        try:
            fetch_and_post(community_filter)
        except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as err:
            logger.error(f"Connection error occurred: {err}")
            logger.exception(err)
            logger.error("Retrying in 60 seconds...")
            time.sleep(60)
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            logger.exception(e)
            break
        else:
            # This block will only execute if no exception was raised
            logger.info("fetch_and_post completed successfully")
            break

if __name__ == "__main__":
    main()
