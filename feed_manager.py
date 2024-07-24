import argparse
import feedparser
from db import RSSFeedDB  # Import the RSSFeedDB class from your database handling module
from lemmy import LemmyCommunicator  # Ensure you have this module set up to communicate with Lemmy

def list_feeds(db):
    feeds = db.list_feeds()
    for feed in feeds:
        print(f"Community: {feed[2]}, RSS URL: {feed[1]}")

def add_feed(db, feed_url, community_name, lemmy_api):
    # Fetch and parse the RSS feed
    feed = feedparser.parse(feed_url)
    if not feed.entries:
        print(f"Error: {feed_url} does not appear to be a valid RSS feed.")
        return

    # Extract feed details
    title = feed.feed.get('title', community_name)  # Use community_name as fallback
    description = feed.feed.get('description', '')
    icon = feed.feed.get('image', {}).get('url', None)

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
        db.add_feed(feed_url, community_name, community_id)
        print(f"Added feed {feed_url} for community {community_name} with Lemmy ID {community_id}.")
    else:
        print("Failed to create community in Lemmy.")

def delete_feed(db, feed_url):
    db.remove_feed(feed_url)
    print(f"Deleted feed {feed_url}.")

def main():
    parser = argparse.ArgumentParser(description='Manage RSS feeds for Lemmy communities.')
    parser.add_argument('command', choices=['list', 'add', 'delete'], help='Command to execute (list, add, delete)')
    parser.add_argument('feed_url', nargs='?', help='The URL of the RSS feed.')
    parser.add_argument('community_name', nargs='?', help='The name of the Lemmy community for add command.')

    args = parser.parse_args()

    db = RSSFeedDB('rss_feeds.db')

    if args.command == 'list':
        list_feeds(db)
    elif args.command == 'add':
        lemmy_api = LemmyCommunicator()  # Initialize the Lemmy API communicator
        if args.feed_url and args.community_name:
            add_feed(db, args.feed_url, args.community_name, lemmy_api)
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
