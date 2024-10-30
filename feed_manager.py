import argparse
import feedparser
import requests
from urllib.parse import urlparse

from config import Config
from db import RSSFeedDB
from fetch_and_post import USER_AGENT
from fetch_icons import fetch_high_res_icons, find_best_icon
from lemmy import LemmyCommunicator

def list_feeds(db):
    feeds = db.list_feeds()
    for feed in feeds:
        print(feed[0])
        for token in feed[1:]:
            print(f"  {token}")

def parse_actor_id(actor_id):
    """Parse an actor ID into instance and username."""
    username, instance = actor_id.split('@')
    return instance, username

def create_lemmy_api_for_user(instance, username):
    """Create a LemmyCommunicator instance for a specific user on a specific instance."""
    return LemmyCommunicator(username, instance)

def subscribe_to_community(lemmy_api, community_name):
    """Subscribe to a community using the given LemmyCommunicator instance."""
    try:
        community_id = lemmy_api.fetch_community_id(f"{community_name}@{Config.LEMMY_SERVER}")
        lemmy_api.subscribe_to_community(community_id)
        print(f"Subscribed to {community_name}@{Config.LEMMY_SERVER} from {lemmy_api.server}")
    except Exception as e:
        print(f"Failed to subscribe to {community_name}@{Config.LEMMY_SERVER} from {lemmy_api.server}: {str(e)}")

def appoint_mods(lemmy_api, community_name, community_id, bot_username):
    if Config.LEMMY_ADDITIONAL_MODS == "":
        additional_mods = []
    else:
        additional_mods = Config.LEMMY_ADDITIONAL_MODS.split(',')
    
    # Subscribe and appoint mods
    for mod_actor_id in additional_mods:
        instance, username = parse_actor_id(mod_actor_id)
        mod_lemmy_api = create_lemmy_api_for_user(instance, username)
        
        # Subscribe to the community
        subscribe_to_community(mod_lemmy_api, community_name)
        
        # Appoint as mod
        mod_id = lemmy_api.fetch_user_id(mod_actor_id)
        if mod_id is None:
            raise Exception(f"Can't find ID for {mod_actor_id}")
        lemmy_api.appoint_mod(community_id, mod_id)
    
    # Appoint the main bot
    mod_user_id = lemmy_api.fetch_user_id(bot_username)
    lemmy_api.appoint_mod(community_id, mod_user_id)

def add_feed(db, feed_url, community_name, lemmy_api, bot_username, appoint_mod=True, create_community=True, create_db_entry=True):
    # Fetch and parse the RSS feed
    request_headers = {'User-Agent': USER_AGENT}
    response = requests.get(feed_url, headers=request_headers, timeout=30)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    
    if not feed.entries:
        print(f"Error: {feed_url} does not appear to be a valid RSS feed.")
        return

    # Extract feed details
    title = feed.feed.get('title', community_name)  # Use community_name as fallback
    description = feed.feed.get('description', '')
    default_icon = feed.feed.get('image', {}).get('url', None)

    # Fetch and determine the best high-resolution icon
    domain = feed_url.split('/')[2].split('.')
    website_url = feed_url.split('/')[0] + '//' + domain[-2] + '.' + domain[-1]

    print(f"Website URL: {website_url}")

    # Fetch and determine the best high-resolution icon
    icons = fetch_high_res_icons(website_url)
    best_icon = find_best_icon(icons) or default_icon  # Use the best icon or the default if none found
    
    community_id = None
    if create_community:
        # Create the community in Lemmy
        community_details = {
            'title': title,
            'description': description,
            'icon': best_icon,
            'posting_restricted_to_mods': True
        }
        community = lemmy_api.create_community(name=community_name, **community_details)
        community_id = community.get('id')
        if community_id:
            print(f"Created community {community_name} with Lemmy ID {community_id}.")
        else:
            print("Failed to create community in Lemmy.")
    else:
        community_id = lemmy_api.fetch_community_id(community_name)

    if community_id:
        if appoint_mod:
            appoint_mods(lemmy_api, community_name, community_id, bot_username)

        if create_db_entry:
            db.add_feed(feed_url, community_name, community_id, bot_username=bot_username)
            print(f"Added feed {feed_url} for community {community_name} with Lemmy ID {community_id}. Bot account: {bot_username}")
    else:
        print("Skipped database entry due to failed community creation.")

def delete_feed(db, filter):
    """Delete a feed based on the community name."""
    print(f"Deleting feeds for {filter}")

    changes = db.remove_feed(community_name=filter)
    print(f"  {changes} by community name")
    
    changes = db.remove_feed(feed_url=filter)
    print(f"  {changes} by feed URL")

def update_feed(db, community_name, new_feed_url, bot_username):
    db.update_feed_url(community_name, new_feed_url, bot_username)
    print(f"Updated feed URL for community '{community_name}' to '{new_feed_url}'.")
    print(f"Updated bot account to {bot_username}")

def update_mods(db, lemmy_api, filter_feed_url=None, filter_community_name=None):
    feeds = db.list_feeds()
    processed_communities = set()
    
    for feed in feeds:
        feed_url = feed[1]
        community_name = feed[2]

        if filter_feed_url is not None and feed_url != filter_feed_url:
            continue
        if filter_community_name is not None and community_name != filter_community_name:
            continue

        community_id = feed[3]
        bot_username = feed[7]  # Assuming bot_username is at index 7
        
        if community_id not in processed_communities:
            appoint_mods(lemmy_api, community_name, community_id, bot_username)
            processed_communities.add(community_id)
        else:
            print(f"  Skipped community ID {community_id} (already processed)")
    
    print(f"Updated mods for {len(processed_communities)} unique communities")

def main():
    parser = argparse.ArgumentParser(description='Manage RSS feeds for Lemmy communities.')
    parser.add_argument('-na', '--no-appoint-mod', action='store_true', help='Do not appoint the admin mod after creating the community')
    parser.add_argument('-nc', '--no-create-community', action='store_true', help='Do not create the community in Lemmy')
    parser.add_argument('-ndb', '--no-database-entry', action='store_true', help='Do not create the database entry')
    parser.add_argument('-b', '--bot-username', choices=['free', 'paywall', 'bot'], default='free', help='Specify the bot username')
    parser.add_argument('command', choices=['list', 'add', 'delete', 'update', 'update_mods'], help='Command to execute')
    parser.add_argument('feed_url', nargs='?', help='The URL of the RSS feed.')
    parser.add_argument('community_name', nargs='?', help='The name of the Lemmy community for add or update commands.')

    args = parser.parse_args()

    db = RSSFeedDB()
    lemmy_api = LemmyCommunicator(Config.LEMMY_BOT_BOT)

    if args.command == 'list':
        list_feeds(db)
    elif args.command == 'add':
        if args.feed_url and args.community_name:
            add_feed(db, args.feed_url, args.community_name, lemmy_api, 
                     bot_username=args.bot_username,
                     appoint_mod=not args.no_appoint_mod, 
                     create_community=not args.no_create_community, 
                     create_db_entry=not args.no_database_entry)
        else:
            print("Missing arguments for add. Please provide a feed URL and community name.")
    elif args.command == 'delete':
        if args.feed_url: # Not really the feed URL
            delete_feed(db, args.feed_url)
        else:
            print("Missing argument for delete. Please provide a community name.")
    elif args.command == 'update':
        if args.feed_url and args.community_name:
            update_feed(db, args.community_name, args.feed_url, args.bot_username)
        else:
            print("Missing arguments for update. Please provide a feed URL and community name.")
    elif args.command == 'update_mods':
        update_mods(db, lemmy_api, args.feed_url, args.community_name)
        if args.feed_url is not None and args.community_name is None:
            update_mods(db, lemmy_api, None, args.feed_url)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()