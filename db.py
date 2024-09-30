import sqlite3
from contextlib import closing
from datetime import datetime

class RSSFeedDB:
    def __init__(self, db_path='rss_feeds.db'):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rss_feeds (
                    id INTEGER PRIMARY KEY,
                    feed_url TEXT,
                    community_name TEXT,
                    community_id INTEGER,
                    last_updated_header TEXT,
                    next_check TIMESTAMP,
                    etag TEXT,
                    bot_username TEXT NOT NULL,
                    UNIQUE(feed_url, community_id)
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

    def add_feed(self, feed_url, community_name, community_id, last_updated_header=None, etag=None, next_check=None, bot_username=None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO rss_feeds (feed_url, community_name, community_id, last_updated_header, etag, next_check, bot_username)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (feed_url, community_name, community_id, last_updated_header, etag, next_check, bot_username))
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
    def update_feed_url(self, community_name, new_feed_url, bot_username=None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM rss_feeds WHERE community_name = ?
            ''', (community_name,))
            count = cursor.fetchone()[0]
            if count == 1:
                if bot_username:
                    cursor.execute('''
                        UPDATE rss_feeds
                        SET feed_url = ?, bot_username = ?
                        WHERE community_name = ?
                    ''', (new_feed_url, bot_username, community_name))
                else:
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

    def update_article_post_id(self, article_id, lemmy_post_id):
        """Update the posted_timestamp for an existing article."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE rss_articles
                SET lemmy_post_id = ?
                WHERE id = ?
            ''', (lemmy_post_id, article_id))
            conn.commit()

    def get_articles_by_feed(self, feed_id, limit=None):
        """
        Retrieve articles for a specific feed, sorted by id in descending order.
        
        :param feed_id: The ID of the feed to retrieve articles for.
        :param limit: Optional. The maximum number of articles to return.
        :return: A list of articles.
        """
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            query = '''
                SELECT * FROM rss_articles 
                WHERE feed_id = ? 
                ORDER BY id DESC
            '''
            if limit is not None:
                query += ' LIMIT ?'
                cursor.execute(query, (feed_id, limit))
            else:
                cursor.execute(query, (feed_id,))
            return cursor.fetchall()

    def get_unposted_article(self, feed_id):
        """Get the first article with NULL posted_timestamp for a given feed."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM rss_articles 
                WHERE feed_id = ? AND lemmy_post_id IS NULL
                ORDER BY id ASC
                LIMIT 1
            ''', (feed_id,))
            return cursor.fetchone()

    def list_feeds(self):
        """List all RSS feeds."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM rss_feeds')
            return cursor.fetchall()

    def remove_feed(self, community_name=None, feed_url=None):
        """Remove a feed based on the community name and/or feed URL."""
        if community_name is None and feed_url is None:
            raise ValueError("Cannot remove a feed without limits specified")

        query = 'DELETE FROM rss_feeds WHERE'
        params = []

        if community_name is not None:
            query += ' community_name = ?'
            params.append(community_name)

        if feed_url is not None:
            if params:
                query += ' AND'
            query += ' feed_url = ?'
            params.append(feed_url)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            changes = conn.total_changes
            conn.commit()
        return changes  # Returns the number of rows deleted

def migrate_database():
    db_path = 'rss_feeds.db'
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Check if the unique constraint exists
        cursor.execute('''
            SELECT COUNT(*) FROM sqlite_master 
            WHERE type='index' AND name='idx_feed_url_community_id'
        ''')
        constraint_exists = cursor.fetchone()[0] > 0
        
        if not constraint_exists:
            # Create a new table with the desired structure
            cursor.execute('''
                CREATE TABLE rss_feeds_new (
                    id INTEGER PRIMARY KEY,
                    feed_url TEXT,
                    community_name TEXT,
                    community_id INTEGER,
                    last_updated_header TEXT,
                    next_check TIMESTAMP,
                    etag TEXT,
                    bot_username TEXT NOT NULL,
                    UNIQUE(feed_url, community_id)
                )
            ''')
            
            # Copy data from the old table to the new table
            cursor.execute('''
                INSERT OR REPLACE INTO rss_feeds_new 
                SELECT id, feed_url, community_name, community_id, last_updated_header, next_check, etag, bot_username 
                FROM rss_feeds
            ''')
            
            # Drop the old table and rename the new one
            cursor.execute('DROP TABLE rss_feeds')
            cursor.execute('ALTER TABLE rss_feeds_new RENAME TO rss_feeds')
            
            print("Database migration completed successfully.")
        else:
            print("Database is up to date. No migration needed.")
        
        conn.commit()

def main():
    migrate_database()

if __name__ == "__main__":
    main()