import argparse
import feedparser
from db import RSSFeedDB
from lemmy import LemmyCommunicator
from fetch_icons import fetch_high_res_icons, find_best_icon

def list_feeds(db):
    feeds = db.list_feeds()
    for feed in feeds:
        print(f"Community: {feed[2]}, RSS URL: {feed[1]}")

def add_feed(db, feed_url, community_name, lemmy_api, appoint_mod=True, create_community=True, create_db_entry=True):
    # Fetch and parse the RSS feed
    feed = feedparser.parse(feed_url)
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
            lemmy_api.appoint_mod(community_id, 2)

        if create_db_entry:
            db.add_feed(feed_url, community_name, community_id)
            print(f"Added feed {feed_url} for community {community_name} with Lemmy ID {community_id}.")
    else:
        print("Skipped database entry due to failed community creation.")

def delete_feed(db, feed_url):
    db.remove_feed(feed_url)
    print(f"Deleted feed {feed_url}.")

def main():
    parser = argparse.ArgumentParser(description='Manage RSS feeds for Lemmy communities.')
    parser.add_argument('-na', '--no-appoint-mod', action='store_true', help='Do not appoint the admin mod after creating the community')
    parser.add_argument('-nc', '--no-create-community', action='store_true', help='Do not create the community in Lemmy')
    parser.add_argument('-ndb', '--no-database-entry', action='store_true', help='Do not create the database entry')
    parser.add_argument('command', choices=['list', 'add', 'delete'], help='Command to execute')
    parser.add_argument('feed_url', nargs='?', help='The URL of the RSS feed.')
    parser.add_argument('community_name', nargs='?', help='The name of the Lemmy community for add command.')

    args = parser.parse_args()

    db = RSSFeedDB()

    if args.command == 'list':
        list_feeds(db)
    elif args.command == 'add':
        if args.feed_url and args.community_name:
            lemmy_api = LemmyCommunicator()
            add_feed(db, args.feed_url, args.community_name, lemmy_api, not args.no_appoint_mod, not args.no_create_community, not args.no_database_entry)
        else:
            print("Missing arguments for add. Please provide a feed URL and community name.")
    elif args.command == 'delete':
        if args.feed_url:
            delete_feed(db, args.feed_url)
        else:
            print("Missing argument for delete. Please provide a feed URL.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()