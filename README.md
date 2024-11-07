# RSS Fetch Bot

A flexible RSS bot for Lemmy that automatically posts updates from RSS/Atom feeds to communities. The bot supports multiple user accounts, feed management, and can be controlled either via command line or through Lemmy's messaging system.

## Features

- Automatic posting of RSS/Atom feed updates to Lemmy communities
- Smart polling with adaptive backoff based on feed update patterns
- Support for multiple bot accounts (e.g., separate accounts for free/paywalled content)
- Feed management via command line or direct messages
- Community-specific and global content filtering
- HTML entity handling and title cleanup
- Moderator-only feed management
- Support for ETag and Last-Modified headers to minimize bandwidth

## Setup

1. Clone the repository
2. Install dependencies:
```bash
pip install feedparser requests dateparser python-dotenv sqlite3
```
3. Create a `.env` file with your settings:
```python
# Lemmy configuration
LEMMY_SERVER=your.server
```

Other configuration variables are also available. See `.env.default` for the full list. Make modifications in `.env` only.

## Usage

### Running the Bot

To start the RSS bot:
```bash
python fetch-and-post.py
```

Optionally, you can specify communities to update:
```bash
python fetch-and-post.py -c community1,community2
```

### Managing Feeds

The `feed-manager.py` script provides command-line feed management:

```bash
# List all feeds
python feed-manager.py list

# Add a new feed
python feed-manager.py add https://example.com/feed.xml communityname

# Delete a feed
python feed-manager.py delete communityname

# Change the feed URL for a community (or change options)
python feed-manager.py update https://new-url.com/feed.xml communityname
```

Additional options:
- `-b {free,paywall,bot}`: Specify which bot account to use
- `-na`: Don't appoint moderators after creating community
- `-nc`: Don't create a new community in Lemmy
- `-ndb`: Don't create a database entry

### Bots

The script is designed to run with multiple bot accounts, to help users in distinguishing or blocking different types of content if they desire. You can use `-b bot` to always post from `bot@{instance}`, which is probably a sensible default if you don't want to use this.

### User Commands

Community moderators can manage feeds by sending private messages to the bot:

```
/add https://example.com/feed.xml community@instance
/delete https://example.com/feed.xml community@instance
/list community@instance
/help
```

## Database Structure

The bot uses SQLite with two main tables:

- `rss_feeds`: Stores feed configurations and metadata
- `rss_articles`: Tracks posted articles to prevent duplicates

## Logging

The bot maintains three log files:
- `rssbot.log`: General debug and info logging
- `error.log`: Error-level messages
- Console output: Info-level messages

## Content Filtering

The bot includes both global and community-specific content filtering:

- Global blacklist patterns in `GLOBAL_BLACKLIST`
- Community-specific patterns in `COMMUNITY_BLACKLIST`

If you are posting from feeds which include any type of spammy content, you will probably want to keep these updated, adding expressions to them for common types of spam you encounter.

Modify these in `fetch-and-post.py` to customize filtering.

## Adaptive Polling

The bot uses smart polling with several backoff strategies, so that it will poll roughly as often as each feed updates. It will not poll more often than once per 5 minutes, or less often than once per 24 hours.

## Contributing

This was a one-off project for a particular installation, but you're welcome to it, if you find it useful. Drop me a line with any questions, or any contributions if you have them.

## License

This project is open source and available under the [AGPL License](LICENSE.md).