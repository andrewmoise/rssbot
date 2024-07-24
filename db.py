import sqlite3
from contextlib import closing

class RSSFeedDB:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize the database with the required tables if not already present."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rss_feeds (
                    id INTEGER PRIMARY KEY,
                    feed_url TEXT UNIQUE,
                    community_name TEXT,
                    community_id INTEGER,
                    last_checked TIMESTAMP,
                    process_id INTEGER
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rss_articles (
                    id INTEGER PRIMARY KEY,
                    feed_id INTEGER,
                    article_url TEXT UNIQUE,
                    headline TEXT,
                    fetched_timestamp TIMESTAMP,
                    lemmy_post_id INTEGER,
                    FOREIGN KEY (feed_id) REFERENCES rss_feeds(id)
                )
            ''')
            conn.commit()

    def add_feed(self, feed_url, community_name, community_id):
        """Add a new RSS feed to the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO rss_feeds (feed_url, community_name, community_id)
                VALUES (?, ?, ?)
            ''', (feed_url, community_name, community_id))
            conn.commit()

    def update_feed(self, feed_url, last_checked, process_id=None):
        """Update details of an existing RSS feed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE rss_feeds
                SET last_checked = ?, process_id = ?
                WHERE feed_url = ?
            ''', (last_checked, process_id, feed_url))
            conn.commit()

    def add_article(self, feed_id, article_url, headline, fetched_timestamp):
        """Add a new article related to a specific RSS feed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO rss_articles (feed_id, article_url, headline, fetched_timestamp)
                VALUES (?, ?, ?, ?)
            ''', (feed_id, article_url, headline, fetched_timestamp))
            conn.commit()

    def get_articles_by_feed(self, feed_id):
        """Retrieve all articles for a specific feed."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM rss_articles WHERE feed_id = ?
            ''', (feed_id,))
            return cursor.fetchall()

    def list_feeds(self):
        """List all RSS feeds."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM rss_feeds')
            return cursor.fetchall()
