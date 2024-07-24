import argparse
import feedparser
from db import RSSFeedDB  # Import the RSSFeedDB class from your database handling module
from lemmy import LemmyCommunicator  # Ensure you have this module set up to communicate with Lemmy

def list_feeds(db):
    feeds = db.list_feeds()
    for feed in feeds:
        print(f"Community: {feed[2]}, RSS URL: {feed[1]}")

def add_feed(db, feed_url, community_name, lemmy_api, appoint_mod, create_community, create_db_entry):
    # Fetch and parse the RSS feed
    feed = feedparser.parse(feed_url)
    if not feed.entries:
        print(f"Error: {feed_url} does not appear to be a valid RSS feed.")
        return

    # Extract feed details
    title = feed.feed.get('title', community_name)  # Use community_name as fallback
    description = feed.feed.get('description', '')
    icon = feed.feed.get('image', {}).get('url', None)

    community_id = None
    if create_community:
        # Create the community in Lemmy
        community_details = {
            'title': title,
            'description': description,
            'icon': icon,
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

    if appoint_mod:
        lemmy_api.appoint_mod(community_id, 2)

    if create_db_entry:
        db.add_feed(feed_url, community_name, community_id)
        print(f"Added feed {feed_url} for community {community_name} with Lemmy ID {community_id}.")
    elif not community_id:
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

    db = RSSFeedDB('rss_feeds.db')

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