import argparse
import feedparser
import requests

from db import RSSFeedDB
from fetch_and_post import USER_AGENT
from fetch_icons import fetch_high_res_icons, find_best_icon
from lemmy import LemmyCommunicator

FREE_MOD_USER=10862
PAYWALL_MOD_USER=10863

def list_feeds(db):
    feeds = db.list_feeds()
    for feed in feeds:
        print(feed[0])
        for token in feed[1:]:
            print(f"  {token}")

def add_feed(db, feed_url, community_name, lemmy_api, is_paywall=False, appoint_mod=True, create_community=True, create_db_entry=True):
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
            if is_paywall:
                lemmy_api.appoint_mod(community_id, PAYWALL_MOD_USER)
            else:
                lemmy_api.appoint_mod(community_id, FREE_MOD_USER)

        if create_db_entry:
            db.add_feed(feed_url, community_name, community_id, is_paywall=is_paywall)
            print(f"Added feed {feed_url} for community {community_name} with Lemmy ID {community_id}. Is paywall: {is_paywall}")
    else:
        print("Skipped database entry due to failed community creation.")

def delete_feed(db, community_name):
    """Delete a feed based on the community name."""
    changes = db.remove_feed(community_name)
    if changes > 0:
        print(f"Deleted feed(s) for community '{community_name}'.")
    else:
        print(f"No feed found for community '{community_name}', no action taken.")

def update_feed(db, community_name, new_feed_url, is_paywall):
    """Update the feed URL and the is_paywall status for a given community name."""
    db.update_feed_url(community_name, new_feed_url, is_paywall)
    print(f"Updated feed URL for community '{community_name}' to '{new_feed_url}'.")
    if is_paywall is not None:
        print(f"Updated is_paywall status to {is_paywall}.")
    else:
        print("Paywall status was not changed.")

def update_mods(db, lemmy_api):
    """Update moderators for all communities based on their paywall status."""
    feeds = db.list_feeds()
    processed_communities = set()
    
    for feed in feeds:
        community_name = feed[2]
        community_id = feed[3]  # Assuming community_id is at index 2
        is_paywall = feed[7]    # Assuming is_paywall is at index 7
        
        print(community_name)

        if community_id not in processed_communities:
            if is_paywall:
                lemmy_api.appoint_mod(community_id, PAYWALL_MOD_USER)  # Appoint paywall mod
                print(f"  Appointed paywall mod for community ID {community_id}")
            else:
                lemmy_api.appoint_mod(community_id, FREE_MOD_USER)  # Appoint free mod
                print(f"  Appointed free mod for community ID {community_id}")
            
            processed_communities.add(community_id)
        else:
            print(f"  Skipped community ID {community_id} (already processed)")
    
    print(f"Updated mods for {len(processed_communities)} unique communities")

def main():
    parser = argparse.ArgumentParser(description='Manage RSS feeds for Lemmy communities.')
    parser.add_argument('-na', '--no-appoint-mod', action='store_true', help='Do not appoint the admin mod after creating the community')
    parser.add_argument('-nc', '--no-create-community', action='store_true', help='Do not create the community in Lemmy')
    parser.add_argument('-ndb', '--no-database-entry', action='store_true', help='Do not create the database entry')
    parser.add_argument('-p', '--paywall', action='store_true', help='Set the feed as a paywall (for add and update commands)')
    parser.add_argument('-np', '--no-paywall', action='store_true', help='Set the feed as not a paywall (for update command)')
    parser.add_argument('command', choices=['list', 'add', 'delete', 'update', 'update_mods'], help='Command to execute')
    parser.add_argument('feed_url', nargs='?', help='The URL of the RSS feed.')
    parser.add_argument('community_name', nargs='?', help='The name of the Lemmy community for add or update commands.')

    args = parser.parse_args()

    db = RSSFeedDB()
    lemmy_api = LemmyCommunicator()

    if args.command == 'list':
        list_feeds(db)
    elif args.command == 'add':
        if args.feed_url and args.community_name:
            add_feed(db, args.feed_url, args.community_name, lemmy_api, 
                     is_paywall=args.paywall,
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
            if args.paywall and args.no_paywall:
                print("Error: Cannot specify both --paywall and --no-paywall.")
            else:
                is_paywall = True if args.paywall else (False if args.no_paywall else None)
                update_feed(db, args.community_name, args.feed_url, is_paywall)
        else:
            print("Missing arguments for update. Please provide a feed URL and community name.")
    elif args.command == 'update_mods':
        update_mods(db, lemmy_api)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()