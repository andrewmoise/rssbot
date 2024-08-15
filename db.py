import sqlite3
from contextlib import closing
from datetime import datetime

class RSSFeedDB:
    def __init__(self, db_path='rss_feeds.db'):
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
                    last_updated_header TEXT,
                    next_check TIMESTAMP,
                    etag TEXT
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

    def add_feed(self, feed_url, community_name, community_id, last_updated_header=None, etag=None, next_check=None):
        """Add a new RSS feed to the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO rss_feeds (feed_url, community_name, community_id, last_updated_header, etag, next_check)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (feed_url, community_name, community_id, last_updated_header, etag, next_check))
            conn.commit()

    def update_feed_timestamps(self, feed_id, last_updated_header, etag, next_check):
        """Update the last_updated_header, etag, and next_check timestamps for a given feed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE rss_feeds
                SET last_updated_header = ?, etag = ?, next_check = ?
                WHERE id = ?
            ''', (last_updated_header, etag, next_check, feed_id))
            conn.commit()

    def update_feed_url(self, community_name, new_feed_url):
        """Update the feed URL for a given community name."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM rss_feeds WHERE community_name = ?
            ''', (community_name,))
            count = cursor.fetchone()[0]
            if count == 1:
                cursor.execute('''
                    UPDATE rss_feeds
                    SET feed_url = ?
                    WHERE community_name = ?
                ''', (new_feed_url, community_name))
                conn.commit()
            elif count > 1:
                raise ValueError(f"Multiple entries found for community name '{community_name}'. Update operation aborted.")
            else:
                raise ValueError(f"No entry found for community name '{community_name}'. Update operation aborted.")

    def get_article_by_url(self, article_url):
        """Retrieve an article by its URL."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM rss_articles WHERE article_url = ?
            ''', (article_url,))
            return cursor.fetchone()

    def add_article(self, feed_id, article_url, headline, fetched_timestamp, lemmy_post_id):
        """Add a new article related to a specific RSS feed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO rss_articles (feed_id, article_url, headline, fetched_timestamp, lemmy_post_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (feed_id, article_url, headline, fetched_timestamp, lemmy_post_id))
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

    def remove_feed(self, community_name):
        """Remove a feed based on the community name."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM rss_feeds WHERE community_name = ?
            ''', (community_name,))
            cursor.execute('''
                DELETE FROM rss_feeds WHERE feed_url = ?
            ''', (community_name,))
            changes = conn.total_changes
            conn.commit()
        return changes  # Returns the number of rows deleted

def migrate_database():
    """Migrate the database to add the etag column."""
    db_path = 'rss_feeds.db'
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Check if the etag column exists
        cursor.execute("PRAGMA table_info(rss_feeds)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'etag' not in columns:
            # Add the etag column
            cursor.execute('ALTER TABLE rss_feeds ADD COLUMN etag TEXT')
            print("Database migration completed successfully. Added 'etag' column.")
        else:
            print("Database already has the 'etag' column. No migration needed.")
        
        conn.commit()

def main():
    migrate_database()

if __name__ == "__main__":
    main()