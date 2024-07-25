import feedparser
from datetime import datetime
from lemmy import LemmyCommunicator
from db import RSSFeedDB

def fetch_and_post():
    db = RSSFeedDB('rss_feeds.db')
    lemmy_api = LemmyCommunicator()

    feeds = db.list_feeds()
    for feed in feeds:
        feed_id = feed[0]
        feed_url = feed[1]
        community_id = feed[3]

        print(feed_url)
        rss = feedparser.parse(feed_url)
        print('  done\n')
        current_time = datetime.now()

        for entry in rss.entries:
            article_url = entry.link
            headline = entry.title

            # Check if the article is already in the database
            if not db.get_article_by_url(article_url):
                # Post the article to Lemmy
                post = lemmy_api.create_post(
                    community_id=community_id,
                    name=headline,
                    url=article_url
                    #body=''  # Optional: Add a default body or use a description if available
                )
                lemmy_post_id = post['id']

                # Add the article to the database
                db.add_article(feed_id, article_url, headline, current_time, lemmy_post_id)
                print(f"{feed_url}\n  {headline}\n")

    print('All done!')
                
def main():
    fetch_and_post()

if __name__ == "__main__":
    main()
