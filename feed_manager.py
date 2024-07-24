import argparse
import sys
from db import RSSFeedDB  # Import the RSSFeedDB class from your database handling module

def list_feeds(db):
    feeds = db.list_feeds()
    for feed in feeds:
        print(f"Community: {feed[2]}, RSS URL: {feed[1]}")

def add_feed(db, feed_url, community_name):
    db.add_feed(feed_url, community_name)
    print(f"Added feed {feed_url} for community {community_name}.")

def delete_feed(db, feed_url):
    db.remove_feed(feed_url)
    print(f"Deleted feed {feed_url}.")

def main():
    parser = argparse.ArgumentParser(description='Manage RSS feeds for Lemmy communities.')
    parser.add_argument('command', choices=['list', 'add', 'delete'], help='Command to execute (list, add, delete)')
    parser.add_argument('feed_url', nargs='?', help='The URL of the RSS feed.')
    parser.add_argument('community_name', nargs='?', help='The name of the Lemmy community for add command.')

    args = parser.parse_args()

    db = RSSFeedDB('path_to_your_database.db')

    if args.command == 'list':
        list_feeds(db)
    elif args.command == 'add':
        if args.feed_url and args.community_name:
            add_feed(db, args.feed_url, args.community_name)
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
